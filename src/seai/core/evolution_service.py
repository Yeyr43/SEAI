"""
SEAI 进化服务 - 从 SEAgent 中提取的自进化逻辑
负责深度进化、工具自修复、技能策展、优化指令校验、进化记录导出
"""
import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path
from loguru import logger


OPTIMIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "update_skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "command": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["name", "content"]
            }
        },
        "update_memory": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "update", "delete", "archive"]},
                    "text": {"type": "string"},
                    "node_id": {"type": "string"}
                }
            }
        },
        "update_config": {"type": "object"},
        "analysis": {"type": "string"}
    }
}


class EvolutionService:
    """进化服务 - 管理技能优化、记忆整理、工具自修复、进化记录导出"""

    def __init__(
        self,
        llm_provider=None,
        skill_repository=None,
        memory_store=None,
        error_handler=None,
        evolution_tester=None,
        data_dir: Path = None,
        config=None,
        session_manager=None,
    ):
        self.llm_provider = llm_provider
        self.skill_repository = skill_repository
        self.memory_store = memory_store
        self.error_handler = error_handler
        self.evolution_tester = evolution_tester
        self.data_dir = data_dir
        self.config = config
        self.session_manager = session_manager
        self._evolution_history: List[dict] = []
        self._max_history = 50

    def _collect_recent_conversations(self, limit: int = 50) -> List[Dict]:
        """收集最近N条对话记录（跨会话）"""
        conversations = []
        if not self.session_manager or not self.data_dir:
            return conversations

        sessions_dir = self.data_dir / "sessions"
        if not sessions_dir.exists():
            return conversations

        all_messages = []
        for f in sorted(sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                session_id = data.get("session_id", f.stem)
                title = data.get("title", "未命名")
                for msg in data.get("messages", []):
                    all_messages.append({
                        "session_id": session_id,
                        "session_title": title,
                        "role": msg.get("role", ""),
                        "content": msg.get("content", "")[:300],
                    })
            except Exception as e:
                logger.warning(f"读取会话文件失败 [{f.name}]: {e}")

        all_messages.sort(key=lambda x: x.get("session_id", ""), reverse=True)
        return all_messages[-limit:]

    def _collect_skill_packages(self) -> List[Dict]:
        """收集技能包信息"""
        skills = []
        if self.skill_repository:
            for skill in self.skill_repository.get_all_skills():
                skills.append({
                    "name": skill.get("name", ""),
                    "description": skill.get("description", "")[:200],
                    "command": skill.get("command", "")[:200],
                    "enabled": self.skill_repository.is_skill_enabled(skill.get("name", "")),
                    "score": self.skill_repository.get_skill_score(skill.get("name", "")) if hasattr(self.skill_repository, 'get_skill_score') else None,
                })
        return skills

    def _collect_patches(self) -> List[Dict]:
        """收集补丁信息"""
        patches = []
        if not self.data_dir:
            return patches

        patches_dir = self.data_dir / "patches"
        if patches_dir.exists():
            for f in sorted(patches_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    patches.append({
                        "file": f.name,
                        "description": data.get("description", "")[:200],
                        "applied_at": data.get("applied_at", ""),
                    })
                except Exception as e:
                    logger.warning(f"读取补丁文件失败 [{f.name}]: {e}")
        return patches

    def _collect_long_term_memory(self, limit: int = 50) -> List[str]:
        """收集长期记忆"""
        memories = []
        if self.memory_store:
            try:
                if hasattr(self.memory_store, 'get_long_term_memories'):
                    mems = self.memory_store.get_long_term_memories(limit)
                    for m in mems:
                        if isinstance(m, dict):
                            memories.append(m.get("text", m.get("content", ""))[:300])
                        elif isinstance(m, str):
                            memories.append(m[:300])
            except Exception as e:
                logger.warning(f"长期记忆收集失败: {e}")
        return memories

    async def deep_evolve(self) -> Dict[str, Any]:
        """深度进化：结合近50条对话记录、技能包、补丁及长期记忆，生成全面的进化报告

        仅导出一份进化记录，格式为"精确到秒的时间戳+EVO"
        """
        evo_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        evo_filename = f"{evo_timestamp}_EVO"

        result = {
            "success": False,
            "evo_id": evo_filename,
            "evo_timestamp": evo_timestamp,
            "analysis": "",
            "skill_changes": [],
            "memory_changes": [],
            "validation_results": [],
            "errors": []
        }

        if not self.llm_provider:
            result["errors"].append("LLM 提供者未初始化")
            return result

        recent_conversations = self._collect_recent_conversations(50)
        skill_packages = self._collect_skill_packages()
        patches = self._collect_patches()
        long_term_memories = self._collect_long_term_memory(50)

        feedback_dir = self.data_dir / "evo" / "feedback" if self.data_dir else None
        feedback_files = list(feedback_dir.glob("*.json")) if feedback_dir and feedback_dir.exists() else []

        skill_stats = {}
        if self.skill_repository:
            for skill in self.skill_repository.get_all_skills():
                name = skill.get("name", "")
                if hasattr(self.skill_repository, 'get_skill_score'):
                    skill_stats[name] = {
                        "score": self.skill_repository.get_skill_score(name),
                        "enabled": self.skill_repository.is_skill_enabled(name)
                    }

        error_summary = self.error_handler.error_stats if self.error_handler else {}
        recent_errors = self.error_handler.recent_errors[-20:] if self.error_handler else []

        evolution_context = {
            "evo_id": evo_filename,
            "evo_timestamp": evo_timestamp,
            "conversation_count": len(recent_conversations),
            "recent_conversations": recent_conversations[-50:],
            "skill_packages": skill_packages,
            "patches": patches,
            "long_term_memories": long_term_memories[-20:],
            "feedback_count": len(feedback_files),
            "skill_stats": skill_stats,
            "error_summary": error_summary,
            "recent_errors": [
                {"type": e.get("error_type", ""), "message": e.get("error_message", "")[:200]}
                for e in recent_errors
            ],
        }

        prompt = f"""你是 SEAI 的深度进化引擎。基于以下全面的系统状态，生成一份深度进化报告和优化方案。

## 进化上下文
- 进化ID: {evo_filename}
- 进化时间: {evo_timestamp}

## 最近对话记录（{len(recent_conversations)}条）
{json.dumps(recent_conversations[-50:], indent=2, ensure_ascii=False)}

## 技能包状态
{json.dumps(skill_packages, indent=2, ensure_ascii=False)}

## 补丁记录
{json.dumps(patches, indent=2, ensure_ascii=False)}

## 长期记忆摘要
{json.dumps(long_term_memories[-20:], indent=2, ensure_ascii=False)}

## 错误统计
{json.dumps(error_summary, indent=2, ensure_ascii=False)}

## 优化要求
1. 综合分析对话模式、技能使用效果、补丁效果和长期记忆
2. 识别系统薄弱环节和改进机会
3. 为低分技能生成改进方案
4. 识别需要清理或归档的记忆
5. 生成全面的进化报告

## 输出格式
```json
{{
  "analysis": "全面的进化分析报告（必填，详细描述发现的问题、模式和改进方向）",
  "evolution_summary": {{
    "conversation_patterns": "对话模式分析",
    "skill_effectiveness": "技能有效性评估",
    "patch_impact": "补丁影响评估",
    "memory_health": "记忆健康度评估",
    "improvement_areas": ["改进领域1", "改进领域2"],
    "overall_score": 0.0
  }},
  "update_skills": [
    {{
      "name": "技能名",
      "content": "完整的 SKILL.md 内容",
      "command": "执行命令",
      "description": "技能描述"
    }}
  ],
  "update_memory": [
    {{
      "action": "add|update|delete|archive",
      "text": "记忆内容",
      "node_id": "节点ID（update/delete时必填）"
    }}
  ],
  "update_config": {{}}
}}
```

只输出 JSON，不要额外解释。"""

        try:
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            response_text = response if isinstance(response, str) else response.get("content", "")

            optimization = self._validate_optimization_json(response_text)
            if not optimization:
                result["errors"].append("进化输出校验失败，优化指令被拒绝")
                result["analysis"] = response_text[:500]
                self._export_evo_record(evo_filename, result)
                return result

            result["analysis"] = optimization.get("analysis", "")
            result["evolution_summary"] = optimization.get("evolution_summary", {})

            if "update_skills" in optimization:
                for skill_update in optimization["update_skills"]:
                    skill_name = skill_update.get("name", "")
                    new_content = skill_update.get("content", "")

                    old_definition = {}
                    if self.skill_repository:
                        skills = self.skill_repository.get_all_skills()
                        for s in skills:
                            if s.get("name") == skill_name:
                                old_definition = s
                                break

                    new_definition = {
                        "name": skill_name,
                        "content": new_content,
                        "command": skill_update.get("command", ""),
                        "description": skill_update.get("description", "")
                    }

                    test_result = None
                    if self.evolution_tester and old_definition:
                        test_result = self.evolution_tester.test_skill_improvement(
                            skill_name=skill_name,
                            old_definition=old_definition,
                            new_definition=new_definition,
                            skill_executor=lambda d, args: self._simulate_skill(d, args)
                        )

                    if test_result and not test_result.passed:
                        result["errors"].append(
                            f"技能 {skill_name} 优化未通过试验场验证 "
                            f"(旧分: {test_result.old_score}, 新分: {test_result.new_score})"
                        )
                        result["validation_results"].append({
                            "skill": skill_name,
                            "passed": False,
                            "old_score": test_result.old_score,
                            "new_score": test_result.new_score
                        })
                        continue

                    if self.skill_repository and hasattr(self.skill_repository, 'update_skill'):
                        self.skill_repository.update_skill(skill_name, new_content)
                        result["skill_changes"].append({
                            "skill": skill_name,
                            "action": "updated",
                            "validated": test_result is not None,
                            "old_score": test_result.old_score if test_result else None,
                            "new_score": test_result.new_score if test_result else None
                        })
                        logger.info(f"技能 {skill_name} 已优化（试验场验证通过）")

            if "update_memory" in optimization and self.memory_store:
                for mem_update in optimization["update_memory"]:
                    action = mem_update.get("action", "")
                    text = mem_update.get("text", "")
                    node_id = mem_update.get("node_id", "")

                    if action == "add" and text:
                        self.memory_store.add_memory(text)
                        result["memory_changes"].append({"action": "add", "text": text[:100]})
                    elif action == "archive" and text:
                        if hasattr(self.memory_store, 'add_long_term_memory_with_links'):
                            self.memory_store.add_long_term_memory_with_links(text, mem_type="evolution")
                        else:
                            self.memory_store.add_memory(f"[进化归档] {text}")
                        result["memory_changes"].append({"action": "archive", "text": text[:100]})

            if feedback_files:
                for f in feedback_files[:50]:
                    try:
                        f.unlink()
                    except Exception as e:
                        logger.warning(f"反馈文件删除失败 [{f.name}]: {e}")
                logger.info(f"已清理 {len(feedback_files)} 个反馈文件")

            result["success"] = len(result["errors"]) == 0

        except Exception as e:
            logger.error(f"深度进化异常: {e}")
            result["errors"].append(str(e))

        self._export_evo_record(evo_filename, result)

        self._evolution_history.append({
            "timestamp": time.time(),
            "evo_id": evo_filename,
            "success": result["success"],
            "skill_changes": len(result["skill_changes"]),
            "memory_changes": len(result["memory_changes"]),
            "errors": len(result["errors"]),
        })
        if len(self._evolution_history) > self._max_history:
            self._evolution_history = self._evolution_history[-self._max_history:]

        return result

    def _export_evo_record(self, evo_filename: str, result: Dict[str, Any]):
        """导出进化记录文件（格式：精确到秒的时间戳+EVO）"""
        if not self.data_dir:
            return

        evo_dir = self.data_dir / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)

        evo_record = {
            "evo_id": evo_filename,
            "evo_timestamp": result.get("evo_timestamp", ""),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "success": result.get("success", False),
            "analysis": result.get("analysis", ""),
            "evolution_summary": result.get("evolution_summary", {}),
            "skill_changes": result.get("skill_changes", []),
            "memory_changes": result.get("memory_changes", []),
            "validation_results": result.get("validation_results", []),
            "errors": result.get("errors", []),
            "context": {
                "conversation_count": len(self._collect_recent_conversations(50)),
                "skill_count": len(self._collect_skill_packages()),
                "patch_count": len(self._collect_patches()),
                "memory_count": len(self._collect_long_term_memory(50)),
            }
        }

        evo_path = evo_dir / f"{evo_filename}.json"
        try:
            evo_path.write_text(json.dumps(evo_record, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"进化记录已导出: {evo_path}")
        except Exception as e:
            logger.error(f"进化记录导出失败: {e}")

    async def auto_fix_tool(self, tool_name: str, error: Exception, input_args: Dict) -> Optional[str]:
        if not self.llm_provider:
            return None

        error_info = {
            "tool": tool_name,
            "error_type": type(error).__name__,
            "error_message": str(error)[:500],
            "input_args": {k: str(v)[:200] for k, v in (input_args or {}).items()}
        }

        if self.error_handler:
            diagnosis = self.error_handler.handle_error(error, {
                "tool": tool_name,
                "args": str(input_args)[:200]
            })
            error_info["diagnosis"] = {
                "severity": diagnosis.severity,
                "probable_cause": diagnosis.probable_cause,
                "immediate_fix": diagnosis.immediate_fix
            }

        prompt = f"""你是 SEAI 的工具自修复引擎。分析以下工具失败并生成修复方案。

## 失败信息
{json.dumps(error_info, indent=2, ensure_ascii=False)}

## 输出格式
```json
{{
  "analysis": "失败原因分析",
  "fix_type": "skill_update|config_change|code_patch|no_fix",
  "update_skills": [
    {{
      "name": "技能名",
      "content": "修复后的 SKILL.md 内容",
      "command": "修复后的命令"
    }}
  ]
}}
```

只输出 JSON。如果无法自动修复，fix_type 设为 "no_fix"。"""

        try:
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            response_text = response if isinstance(response, str) else response.get("content", "")

            fix_data = self._validate_optimization_json(response_text)
            if not fix_data:
                logger.warning(f"工具 {tool_name} 自修复输出校验失败")
                return None

            fix_type = fix_data.get("fix_type", "no_fix")
            if fix_type == "no_fix":
                return f"工具 {tool_name} 无法自动修复: {fix_data.get('analysis', '')}"

            if "update_skills" in fix_data:
                for skill_update in fix_data["update_skills"]:
                    skill_name = skill_update.get("name", "")
                    new_content = skill_update.get("content", "")

                    old_definition = {}
                    if self.skill_repository:
                        for s in self.skill_repository.get_all_skills():
                            if s.get("name") == skill_name:
                                old_definition = s
                                break

                    new_definition = {
                        "name": skill_name,
                        "content": new_content,
                        "command": skill_update.get("command", "")
                    }

                    if self.evolution_tester and old_definition:
                        test_result = self.evolution_tester.test_skill_improvement(
                            skill_name=skill_name,
                            old_definition=old_definition,
                            new_definition=new_definition,
                            skill_executor=lambda d, args: self._simulate_skill(d, args)
                        )
                        if test_result and not test_result.passed:
                            logger.warning(
                                f"工具 {tool_name} 自修复未通过试验场: "
                                f"旧分={test_result.old_score}, 新分={test_result.new_score}"
                            )
                            return None

                    if self.skill_repository and hasattr(self.skill_repository, 'update_skill'):
                        self.skill_repository.update_skill(skill_name, new_content)
                        logger.info(f"工具 {tool_name} 自修复成功: 技能 {skill_name} 已更新")
                        return f"工具 {tool_name} 已自动修复: {fix_data.get('analysis', '')}"

            return None

        except Exception as e:
            logger.error(f"工具自修复异常: {e}")
            return None

    async def curator_check(self) -> int:
        now = time.time()
        thirty_days_ago = now - 30 * 86400
        archived_count = 0
        if not self.skill_repository:
            return 0
        for skill in self.skill_repository.get_all_skills():
            name = skill.get("name", "")
            stats = getattr(self.skill_repository, 'stats', {}).get(name, {})
            last_used = stats.get("last_used", 0)
            score = self.skill_repository.get_skill_score(name)
            if last_used < thirty_days_ago and score < 0.3 and not stats.get("pinned", False):
                if hasattr(self.skill_repository, 'archive_skill'):
                    if self.skill_repository.archive_skill(name):
                        archived_count += 1
                        logger.info(f"Curator: 归档低活跃技能 {name} (评分:{score:.2f})")
        if archived_count > 0 and self.data_dir:
            log_entry = {"timestamp": now, "archived_count": archived_count, "check_type": "curator_auto"}
            log_path = self.data_dir / "curator_log.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        return archived_count

    @staticmethod
    def _validate_optimization_json(raw_output: str) -> Optional[Dict]:
        json_match = re.search(r'\{[\s\S]*\}', raw_output)
        if not json_match:
            logger.warning("进化输出中未找到 JSON 块")
            return None

        json_str = json_match.group(0)
        json_str = json_str.replace("'", '"')

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"进化输出 JSON 解析失败: {e}")
            try:
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)
                data = json.loads(json_str)
            except json.JSONDecodeError:
                return None

        try:
            import jsonschema
            jsonschema.validate(instance=data, schema=OPTIMIZATION_SCHEMA)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"进化输出 Schema 校验失败: {e}")
            return None

        if "update_skills" not in data and "update_memory" not in data and "update_config" not in data:
            if data.get("fix_type") == "no_fix":
                return data
            logger.warning("进化输出无有效优化指令")
            return None

        return data

    def _simulate_skill(self, definition: Dict, args: Dict) -> str:
        content = definition.get("content", definition.get("sop", ""))
        if not content:
            return ""
        lines = content.split("\n")
        return "\n".join(lines[:20])

    def get_stats(self) -> dict:
        return {
            "evolution_count": len(self._evolution_history),
            "last_evolution": self._evolution_history[-1] if self._evolution_history else None,
            "success_rate": sum(1 for e in self._evolution_history if e["success"]) / max(len(self._evolution_history), 1),
        }