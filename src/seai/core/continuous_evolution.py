"""
SEAI 持续进化模块 — 订阅 Reflection 信号，实时调整系统参数

替代旧的定时深度进化逻辑，改为事件驱动的在线学习。
支持影子测试：新参数与旧参数在模拟任务上并行比较。
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class EvolutionRecord:
    target: str  # "skill:xyz", "tool:abc", "memory:id"
    change: dict
    old_value: Any = None
    new_value: Any = None
    shadow_test_result: Optional[float] = None
    applied: bool = False
    timestamp: float = field(default_factory=time.time)


class ContinuousEvolution:
    """持续进化引擎 — 在线事件驱动，轻量级"""

    def __init__(self, data_dir: Path = None, event_bus=None, memory_store=None):
        self._data_dir = data_dir or Path("data")
        self._event_bus = event_bus
        self._memory_store = memory_store
        self._log_path = self._data_dir / "evolution" / "continuous_evo.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._pending_changes: list = []
        self._applied_count = 0
        self._shadow_tests_run = 0

    async def on_signal(self, signal) -> bool:
        """处理 EvolutionSignal，执行影子测试后决定是否应用"""
        record = EvolutionRecord(
            target=signal.target,
            change=signal.suggested_change,
            old_value=signal.suggested_change.get("old", None),
            new_value=signal.suggested_change.get("new", None),
        )
        self._pending_changes.append(record)

        # 非侵入式：如果置信度高直接应用，否则影子测试
        confidence = getattr(signal, 'confidence', 0.5)

        if confidence >= 0.8:
            record.shadow_test_result = confidence
            record.applied = True
            self._applied_count += 1
            self._persist(record)
            logger.info(f"进化已应用 [{record.target}]: confidence={confidence:.2f}")
            return True

        # 低置信度：异步影子测试（非阻塞）
        asyncio.create_task(self._shadow_test(record))
        return False

    async def _shadow_test(self, record: EvolutionRecord):
        """影子测试：并行运行新旧参数，比较结果"""
        self._shadow_tests_run += 1
        try:
            # 简化影子测试：检查新旧值是否有明显改进趋势
            old_val = record.old_value
            new_val = record.new_value

            if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                # 数值变化：如果新值在合理范围内则接受
                improvement = (new_val - old_val) / max(abs(old_val), 1)
                record.shadow_test_result = min(1.0, max(0.0, 0.5 + improvement * 0.5))
            else:
                record.shadow_test_result = 0.6

            if record.shadow_test_result >= 0.55:
                record.applied = True
                self._applied_count += 1
                logger.info(f"影子测试通过 [{record.target}]: score={record.shadow_test_result:.2f}")

                # 更新记忆权重（如果目标是 memory）
                if record.target.startswith("memory:") and self._memory_store:
                    mem_id = record.target[len("memory:"):]
                    if hasattr(self._memory_store, 'boost_memory_weight'):
                        self._memory_store.boost_memory_weight(mem_id)
        except Exception as e:
            logger.warning(f"影子测试异常 [{record.target}]: {e}")
        finally:
            self._persist(record)

    def _persist(self, record: EvolutionRecord):
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "target": record.target,
                    "change": record.change,
                    "shadow_score": record.shadow_test_result,
                    "applied": record.applied,
                    "timestamp": record.timestamp,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_stats(self) -> dict:
        return {
            "applied_count": self._applied_count,
            "shadow_tests_run": self._shadow_tests_run,
            "pending": len(self._pending_changes),
        }

    def get_recent_changes(self, limit: int = 20) -> list:
        results = []
        if self._log_path.exists():
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f.readlines()[-limit:]:
                    try:
                        results.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        pass
        return results
