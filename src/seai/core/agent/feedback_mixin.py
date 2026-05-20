""""""
from ..evolution_service import EvolutionService
from ..feedback_loop import FeedbackSeverity
from ..feedback_loop import FeedbackSource
from loguru import logger
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
import json
import sys
import time

class FeedbackMixin:
    async def _handle_tool_failure_feedback(self, source, signals, rule):
        logger.info(f"反馈处理: 工具失败 - {len(signals)} 个信号")
        failed_tools = set()
        for s in signals:
            tool_name = s.metadata.get("tool_name", "unknown")
            failed_tools.add(tool_name)
        if failed_tools:
            for tool_name in failed_tools:
                await self._auto_fix_tool(tool_name)
        return {"status": "ok", "signals_processed": len(signals), "failed_tools": list(failed_tools)}

    async def _handle_light_check_feedback(self, source, signals, rule):
        logger.info(f"反馈处理: 轻量检查 - {len(signals)} 个信号")
        await self._light_check("[反馈驱动] 自动质量检查")
        return {"status": "ok", "signals_processed": len(signals)}

    async def _handle_deep_evolve_feedback(self, source, signals, rule):
        logger.info(f"反馈处理: 深度进化 - {len(signals)} 个信号")
        try:
            result = await self.deep_evolve()
            if self._feedback_loop:
                self._feedback_loop.emit(
                    source=FeedbackSource.EVOLUTION_RESULT,
                    title="反馈驱动的深度进化完成",
                    detail=str(result.get("analysis", ""))[:200],
                    metadata={"success": result.get("success", False)},
                )
            return result
        except Exception as e:
            logger.error(f"反馈驱动进化失败: {e}")
            return {"status": "error", "error": str(e)}

    async def _handle_constraint_violation_feedback(self, source, signals, rule):
        logger.warning(f"反馈处理: 约束违规 - {len(signals)} 个信号")
        violations = [
            {"title": s.title, "detail": s.detail, "time": s.timestamp}
            for s in signals[-5:]
        ]
        return {"status": "alert", "violations": violations}

    async def _micro_reflect(self, query: str, response_text: str = ""):
        if hasattr(self, '_reflection_engine'):
            await self._reflection_engine.micro_reflect(
                query, response_text,
                llm_provider=self.llm_provider,
                memory_store=self.memory_store,
                kg_provider=self.knowledge_graph_manager,
                error_handler=self._error_handler,
                feedback_loop=self._feedback_loop,
                evolution_tester=self._evolution_tester,
                data_dir=self.data_dir,
            )
            return
        await self._legacy_micro_reflect(query, response_text)

    async def _legacy_micro_reflect(self, query: str, response_text: str = ""):
        """后备微反思实现"""
        if self.memory_store:
            self.memory_store.add_memory(f"用户查询: {query}")
            current_profile = self.memory_store.get_user_profile() or ""
            detected_interests = self._extract_user_interests(query)
            if detected_interests:
                for interest in detected_interests:
                    if interest not in current_profile:
                        self.memory_store.update_user_profile(
                            (current_profile + f"\n- {interest}").strip()
                        )
        if self.knowledge_graph_manager and len(query) > 10:
            try:
                self.knowledge_graph_manager.add_knowledge(
                    text=f"[对话] {query[:200]}",
                    node_type="conversation",
                    importance=0.5
                )
            except Exception:
                logger.warning("KG add knowledge failed")
        recent_evo_records = self._get_recent_evolution_records(3)
        skill_effects = self._get_skill_usage_effects()

        if response_text and len(response_text) > 50:
            uncertainty_signals = ["不确定", "可能", "也许", "建议尝试", "maybe", "perhaps", "I'm not sure"]
            signal_count = sum(1 for s in uncertainty_signals if s in response_text)
            if signal_count >= 3:
                if hasattr(self.memory_store, 'add_long_term_memory_with_links'):
                    self.memory_store.add_long_term_memory_with_links(
                        f"[需改进] 查询: {query[:100]} | 回答含{signal_count}个不确定信号",
                        mem_type="improvement_signal"
                    )
                logger.info(f"微反思: 检测到回答含{signal_count}个不确定信号，已记录改进信号")

            error_indicators = ["错误", "失败", "无法", "不支持", "error", "failed", "cannot", "unable"]
            error_count = sum(1 for s in error_indicators if s in response_text.lower())
            if error_count >= 2:
                if hasattr(self.memory_store, 'add_long_term_memory_with_links'):
                    self.memory_store.add_long_term_memory_with_links(
                        f"[需改进] 查询: {query[:100]} | 回答含{error_count}个错误指示词",
                        mem_type="improvement_signal"
                    )

        if self._error_handler:
            recent_critical = len([e for e in self._error_handler.recent_errors[-10:]
                                   if e.get("severity") in ("high", "critical")])
            if recent_critical >= 3:
                logger.info(f"微反思: 检测到{recent_critical}个严重错误，建议触发深度进化")
                if self._feedback_loop:
                    self._feedback_loop.emit(
                        source=FeedbackSource.MICRO_REFLECT,
                        title=f"检测到{recent_critical}个严重错误",
                        detail="建议触发深度进化",
                        metadata={"critical_count": recent_critical},
                    )

        if self._feedback_loop and response_text:
            quality_signals = sum(1 for s in ["不确定", "maybe", "perhaps"] if s in response_text)
            error_signals = sum(1 for s in ["错误", "失败", "error", "failed"] if s in response_text.lower())
            total_signals = quality_signals + error_signals
            if total_signals >= 3:
                severity = FeedbackSeverity.HIGH if error_signals >= 2 else FeedbackSeverity.MEDIUM
                self._feedback_loop.emit(
                    source=FeedbackSource.MICRO_REFLECT,
                    title=f"响应质量需要改进",
                    detail=f"quality_signals={quality_signals}, error_signals={error_signals}",
                    metadata={"query": query[:100]},
                    severity=severity,
                )

        await self._auto_extract_todos(query)

    async def _light_check(self, query: str = ""):
        """轻量自检：技能健康检查 + 自动禁用低分技能 + 工具可用性检查 + 对话前自检协议"""
        if self.skill_repository:
            skills = self.skill_repository.get_all_skills()
            for s in skills:
                score = s.get("score", 0)
                name = s.get("name", "")
                if score < 0.2 and self.skill_repository.is_skill_enabled(name):
                    self.skill_repository.set_enabled(name, False)
                    logger.warning(f"自检: 已自动禁用低分技能 {name} (评分:{score:.2f})")
                elif score < 0.3:
                    logger.warning(f"自检: 发现低分技能 {name} (评分:{score:.2f})")

        if self.tool_executor and hasattr(self.tool_executor, 'check_tools_availability'):
            try:
                unavailable = self.tool_executor.check_tools_availability()
                if unavailable:
                    logger.warning(f"自检: 以下工具不可用: {unavailable}")
            except Exception:
                logger.warning("Tool availability check failed")

        if self.memory_store and hasattr(self.memory_store, 'get_stats'):
            try:
                stats = self.memory_store.get_stats()
                total = stats.get("total_memories", 0)
                if total > 10000:
                    logger.info(f"自检: 记忆库较大({total}条)，建议触发深度进化整理")
            except Exception:
                logger.warning("Memory stats check failed")

        if query and self._prompt_engine:
            self._self_check_context = self._build_self_check(query)
        else:
            self._self_check_context = ""

    async def _auto_extract_todos(self, query: str):
        if hasattr(self, '_reflection_engine') and self._reflection_engine is not None:
            return await self._reflection_engine.auto_extract_todos(
                query, llm_provider=self.llm_provider, memory_store=self.memory_store
            )

    def _get_recent_evolution_records(self, limit: int = 3) -> List[Dict]:
        if hasattr(self, '_reflection_engine') and self._reflection_engine is not None:
            return self._reflection_engine.get_recent_evolution_records(limit, self.data_dir)
        records = []
        evo_dir = Path(self.config.get_system_config().data_dir) / "evolution"
        if evo_dir.exists():
            for f in sorted(evo_dir.glob("*_EVO.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    records.append(data)
                except Exception:
                    logger.warning("Evolution record load failed")
        return records

    def _get_skill_usage_effects(self) -> Dict[str, Any]:
        if hasattr(self, '_reflection_engine') and self._reflection_engine is not None:
            return self._reflection_engine.get_skill_usage_effects(self._evolution_tester)
        effects = {}
        if self._evolution_tester:
            try:
                effects = self._evolution_tester.get_skill_scores()
            except Exception:
                logger.warning("Skill scores load failed")
        return effects

    async def deep_evolve(self) -> Dict[str, Any]:
        """执行深度进化（委托给 EvolutionService），返回 dict"""
        if not self._evolution_service:
            return {"success": False, "errors": ["进化服务未初始化"]}
        return await self._evolution_service.deep_evolve()

    async def evolve(self) -> str:
        """执行深度进化，返回 JSON 字符串（API 兼容）"""
        result = await self.deep_evolve()
        return json.dumps(result, indent=2, ensure_ascii=False)
