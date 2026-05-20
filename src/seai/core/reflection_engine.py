"""
Reflection Engine — 从 SEAgent 提取的反思与自进化逻辑
职责：微反思、意图检测、兴趣提取、待办提取
"""
import json
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from loguru import logger


class ReflectionEngine:
    """管理微反思、意图检测、用户兴趣提取、待办提取"""

    def __init__(self, llm_provider=None, memory_store=None, error_handler=None,
                 feedback_loop=None, evolution_tester=None, kg_provider=None,
                 data_dir=None, config=None):
        self.llm_provider = llm_provider
        self.memory_store = memory_store
        self.error_handler = error_handler
        self.feedback_loop = feedback_loop
        self.evolution_tester = evolution_tester
        self.kg_provider = kg_provider
        self.data_dir = data_dir
        self.config = config

    def detect_intent(self, query: str) -> str:
        query_lower = query.lower()

        coding_keywords = ["代码", "编程", "写个", "开发", "debug", "调试", "bug", "函数",
                           "class", "def ", "import", "javascript", "python", "java",
                           "golang", "rust", "typescript", "写一段", "实现"]
        search_keywords = ["搜索", "搜寻", "查找", "查询", "搜", "查", "上网",
                           "search", "find", "look up", "新闻", "最新",
                           "谷歌", "百度", "what is", "who is", "how to"]
        analysis_keywords = ["分析", "评估", "review", "检查", "check", "优化",
                             "重构", "refactor", "为什么", "原因"]
        create_keywords = ["创建", "生成", "写一个", "make", "create", "generate",
                           "设计", "design", "build", "新建"]

        if any(kw in query_lower for kw in coding_keywords):
            return "coding"
        if any(kw in query_lower for kw in search_keywords):
            return "search"
        if any(kw in query_lower for kw in analysis_keywords):
            return "analysis"
        if any(kw in query_lower for kw in create_keywords):
            return "creative"
        return "general"

    def extract_user_interests(self, query: str) -> List[str]:
        interests = []
        topic_patterns = [
            (["python", "java", "go", "rust", "javascript", "typescript"], "编程语言"),
            (["机器学习", "深度学习", "AI", "神经网络", "llm", "gpt"], "人工智能"),
            (["前端", "后端", "全栈", "web", "api", "rest"], "Web开发"),
            (["docker", "kubernetes", "k8s", "部署", "devops", "ci/cd"], "DevOps"),
            (["数据库", "sql", "nosql", "redis", "postgresql", "mysql"], "数据库"),
            (["linux", "windows", "macos", "系统", "terminal"], "操作系统"),
            (["算法", "数据结构", "排序", "搜索", "复杂度"], "算法"),
            (["设计模式", "架构", "微服务", "分布式", "高并发"], "系统设计"),
            (["测试", "单元测试", "集成测试", "pytest", "jest"], "软件测试"),
            (["安全", "加密", "认证", "授权", "oauth", "jwt"], "安全"),
        ]
        for keywords, topic in topic_patterns:
            if any(kw in query.lower() for kw in keywords):
                interests.append(topic)
        return interests

    async def auto_extract_todos(self, query: str, llm_provider=None, memory_store=None):
        time_keywords = ["明天", "后天", "下周", "提醒我", "记得", "别忘了", "到时候"]
        if not any(kw in query for kw in time_keywords):
            return

        lp = llm_provider or self.llm_provider
        if not lp:
            return

        try:
            prompt = f"""从以下用户消息中提取待办事项。
用户消息：{query}
如果用户表达了需要在未来某个时间做的事情，提取为待办。
返回JSON格式：
{{"has_todo": true, "todo_content": "简短待办内容", "todo_time": "YYYY-MM-DD HH:MM"}}
如果没有待办：{{"has_todo": false}}"""

            response = await lp.chat([{"role": "user", "content": prompt}])
            data = json.loads(response) if isinstance(response, str) else response

            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    return

            if data.get("has_todo"):
                logger.info(f"自动提取待办: {data.get('todo_content')}")
                ms = memory_store or self.memory_store
                if ms and hasattr(ms, 'add_long_term_memory_with_links'):
                    ms.add_long_term_memory_with_links(
                        f"[待办] {data.get('todo_content', '')} | 时间: {data.get('todo_time', '未指定')}",
                        mem_type="todo"
                    )
        except Exception:
            logger.warning("Todo extraction failed")

    def get_recent_evolution_records(self, limit: int = 3, data_dir: Path = None) -> List[Dict]:
        records = []
        dd = data_dir or self.data_dir
        evo_dir = dd / "evolution" if dd else None
        if evo_dir and evo_dir.exists():
            for f in sorted(evo_dir.glob("*_EVO.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    records.append(data)
                except Exception:
                    logger.warning("Evolution record load failed")
        return records

    def get_skill_usage_effects(self, evolution_tester=None) -> Dict[str, Any]:
        effects = {}
        et = evolution_tester or self.evolution_tester
        if et:
            try:
                effects = et.get_skill_scores()
            except Exception:
                logger.warning("Skill scores load failed")
        return effects

    async def micro_reflect(self, query: str, response_text: str = "",
                             llm_provider=None, memory_store=None, kg_provider=None,
                             error_handler=None, feedback_loop=None,
                             evolution_tester=None, data_dir=None, config=None):
        ms = memory_store or self.memory_store
        lp = llm_provider or self.llm_provider
        kg = kg_provider or self.kg_provider
        eh = error_handler or self.error_handler
        fl = feedback_loop or self.feedback_loop
        et = evolution_tester or self.evolution_tester
        dd = data_dir or self.data_dir

        if ms:
            ms.add_memory(f"用户查询: {query}")
            current_profile = ms.get_user_profile() or ""
            detected_interests = self.extract_user_interests(query)
            if detected_interests:
                for interest in detected_interests:
                    if interest not in current_profile:
                        ms.update_user_profile((current_profile + f"\n- {interest}").strip())

        if kg and len(query) > 10:
            try:
                kg.add_knowledge(
                    text=f"[对话] {query[:200]}",
                    node_type="conversation",
                    importance=0.5
                )
            except Exception:
                logger.warning("KG add knowledge failed")

        recent_evo_records = self.get_recent_evolution_records(3, dd)
        skill_effects = self.get_skill_usage_effects(et)

        if response_text and len(response_text) > 50:
            uncertainty_signals = ["不确定", "可能", "也许", "建议尝试", "maybe", "perhaps", "I'm not sure"]
            signal_count = sum(1 for s in uncertainty_signals if s in response_text)
            if signal_count >= 3:
                if ms and hasattr(ms, 'add_long_term_memory_with_links'):
                    ms.add_long_term_memory_with_links(
                        f"[需改进] 查询: {query[:100]} | 回答含{signal_count}个不确定信号",
                        mem_type="improvement_signal"
                    )
                logger.info(f"微反思: 检测到回答含{signal_count}个不确定信号，已记录改进信号")

            error_indicators = ["错误", "失败", "无法", "不支持", "error", "failed", "cannot", "unable"]
            error_count = sum(1 for s in error_indicators if s in response_text.lower())
            if error_count >= 2:
                if ms and hasattr(ms, 'add_long_term_memory_with_links'):
                    ms.add_long_term_memory_with_links(
                        f"[需改进] 查询: {query[:100]} | 回答含{error_count}个错误指示词",
                        mem_type="improvement_signal"
                    )

        if eh:
            recent_critical = len([e for e in eh.recent_errors[-10:]
                                   if e.get("severity") in ("high", "critical")])
            if recent_critical >= 3:
                logger.info(f"微反思: 检测到{recent_critical}个严重错误，建议触发深度进化")
                if fl:
                    from .feedback_loop import FeedbackSource
                    fl.emit(
                        source=FeedbackSource.MICRO_REFLECT,
                        title=f"检测到{recent_critical}个严重错误",
                        detail="建议触发深度进化",
                        metadata={"critical_count": recent_critical},
                    )

        if fl and response_text:
            from .feedback_loop import FeedbackSource, FeedbackSeverity
            quality_signals = sum(1 for s in ["不确定", "maybe", "perhaps"] if s in response_text)
            error_signals = sum(1 for s in ["错误", "失败", "error", "failed"] if s in response_text.lower())
            total_signals = quality_signals + error_signals
            if total_signals >= 3:
                severity = FeedbackSeverity.HIGH if error_signals >= 2 else FeedbackSeverity.MEDIUM
                fl.emit(
                    source=FeedbackSource.MICRO_REFLECT,
                    title=f"响应质量需要改进",
                    detail=f"quality_signals={quality_signals}, error_signals={error_signals}",
                    metadata={"query": query[:100]},
                    severity=severity,
                )

        await self.auto_extract_todos(query, lp, ms)
