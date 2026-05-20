""""""
from .. import net
from ..context_retriever import ContextRetriever
from ..sub_agent import AgentRole
from ..sub_agent import CompressedResult
from ..sub_agent import SubTask
from ..tool_loop import ToolLoopEngine
from loguru import logger
from typing import AsyncGenerator
from typing import Dict
from typing import List
import sys
import time

class ExecutionMixin:
    async def process_query(
        self,
        query: str,
        history: List[Dict] = None,
        stream: bool = False,
        thinking_enabled: bool = True,
        web_search: bool = False
    ) -> AsyncGenerator[str, None]:
        """处理用户查询（核心方法 - 集成多 Agent 路由 + Token 优化 + 多模态记忆 + 智能错误处理）"""
        self.thinking_enabled = thinking_enabled
        net.set_enabled(web_search)

        if self._prompt_engine:
            self.current_role = self._prompt_engine.detect_role(query)

        try:
            await self._light_check(query)

            # 通过执行管道路由（确保中间件链运行约束检查、熔断、日志、指标）
            if stream:
                strategy_name = "stream"
            elif self._should_use_multi_agent(query, history):
                strategy_name = "multi"
            else:
                strategy_name = "single"

            if stream:
                full_response = []
                async for chunk in self._pipeline.execute_stream(query, history or [], strategy_name=strategy_name):
                    full_response.append(chunk)
                    yield chunk
                response_text = "".join(full_response)
            else:
                response_text = await self._pipeline.execute(query, history or [], strategy_name=strategy_name)
                yield response_text

            if self.thinking_enabled:
                await self._micro_reflect(query, response_text)

            messages = self._build_messages(query, history or [])
            self._log_token_usage(query, self._estimate_tokens(messages), messages)

        except Exception as e:
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {
                    "query": query[:200],
                    "stream": stream,
                    "thinking_enabled": thinking_enabled,
                    "web_search": web_search
                })
                logger.error(f"错误诊断 [{diagnosis.severity}]: {diagnosis.error_type} - {diagnosis.probable_cause}")
                yield f"处理请求时发生错误: {diagnosis.immediate_fix}"
            else:
                logger.error(f"未处理异常: {e}")
                yield f"处理请求时发生错误: {str(e)}"

    def _should_use_multi_agent(self, query: str, history: List[Dict] = None) -> bool:
        if not self._multi_agent_config.get("enabled", False):
            return False
        if not self._complexity_estimator:
            return False
        if not self.llm_provider:
            return False
        return self._complexity_estimator.should_delegate(query, history)

    async def _process_multi_agent(
        self,
        query: str,
        history: List[Dict],
        stream: bool = False,
    ) -> AsyncGenerator[str, None]:
        try:
            plan = await self._task_decomposer.decompose(query)

            if plan.get("strategy") != "delegate" or not plan.get("subtasks"):
                logger.info("多 Agent 判定为直接处理，回退单 Agent 模式")
                messages = self._build_messages(query, history)
                tools = self._collect_relevant_tools(query)
                if stream:
                    async for chunk in self._process_stream(messages, tools):
                        yield chunk
                else:
                    response = await self._process_sync(messages, tools)
                    yield response
                return

            subtasks_data = plan.get("subtasks", [])
            subtasks = []
            for st in subtasks_data:
                role_str = st.get("agent", "explorer")
                try:
                    role = AgentRole(role_str)
                except ValueError:
                    role = AgentRole.EXPLORER

                subtasks.append(SubTask(
                    agent_role=role,
                    description=st.get("description", query),
                    context=st.get("context", ""),
                    depends_on=st.get("depends_on", []),
                    max_tokens=self._multi_agent_config["token_budget_per_sub_agent"],
                ))

            async def execute_subtask(task: SubTask) -> CompressedResult:
                agent = self._agent_pool.acquire(task.agent_role)
                try:
                    result = await agent.execute(
                        task_description=task.description,
                        context=task.context,
                        max_tokens=task.max_tokens,
                    )
                    return result
                finally:
                    self._agent_pool.release(agent.agent_id)

            executed = await self._parallel_scheduler.execute(subtasks, execute_subtask)

            results = [t.result for t in executed if t.result is not None]

            total_tokens = sum(r.token_used for r in results)
            total_time = sum(r.elapsed_ms for r in results)
            logger.info(
                f"多 Agent 执行完成: {len(results)} 子任务, "
                f"{total_tokens} tokens, {total_time:.0f}ms"
            )

            merged = await self._result_merger.merge(query, results)
            yield merged

            for r in results:
                await self._micro_reflect(
                    f"[子Agent:{r.agent_role.value}] {query[:100]}",
                    r.summary[:500],
                )

        except Exception as e:
            logger.error(f"多 Agent 执行异常，回退单 Agent 模式: {e}")
            messages = self._build_messages(query, history)
            tools = self._collect_relevant_tools(query)
            if stream:
                async for chunk in self._process_stream(messages, tools):
                    yield chunk
            else:
                response = await self._process_sync(messages, tools)
                yield response

    def _build_messages(self, query: str, history: List[Dict]) -> List[Dict]:
        if hasattr(self, '_message_builder'):
            return self._message_builder.build_messages(
                query, history,
                locale=self.current_locale,
                thinking_enabled=self.thinking_enabled,
                web_search_enabled=net.is_enabled(),
            )
        return self._legacy_build_messages(query, history)

    def _legacy_build_messages(self, query: str, history: List[Dict]) -> List[Dict]:
        """后备实现（引擎未初始化时使用）"""
        messages = []
        system_prompt = self._build_static_system_prompt()
        if self._self_check_context:
            system_prompt = self._self_check_context + "\n\n---\n\n" + system_prompt
        messages.append({"role": "system", "content": system_prompt})
        layer1, layer2, layer3 = self._build_layered_context(query, history)
        context_parts = []
        if layer1:
            context_parts.append("## 当前会话最近对话（最高权重 ∎∎∎ — 必须优先参考）\n" + layer1)
        if layer2:
            context_parts.append("## 历史相关对话（高权重 ∎∎ — 全部会话检索）\n" + layer2)
        if layer3:
            context_parts.append("## 长记忆与知识库（中权重 ∎ — 背景参考）\n" + layer3)
        if context_parts:
            messages.append({"role": "system", "content": "\n\n".join(context_parts)})
        media_blocks = self._get_media_blocks_for_query(query)
        auto_blocks = self._auto_encode_media_paths(query)
        all_blocks = media_blocks + auto_blocks
        if all_blocks:
            messages.append({"role": "user", "content": [{"type": "text", "text": query}] + all_blocks})
        else:
            messages.append({"role": "user", "content": query})
        return messages

    def _build_static_system_prompt(self) -> str:
        if self._prompt_composer:
            return self._prompt_composer.build_static_system_prompt(
                locale=self.current_locale,
                thinking_enabled=self.thinking_enabled,
                web_search_enabled=net.is_enabled(),
            )
        return ""

    def _build_self_check(self, query: str) -> str:
        if self._prompt_composer:
            return self._prompt_composer.build_self_check(query, self.current_locale)
        return query

    @staticmethod

    def _build_layered_context(self, query: str, history: List[Dict]) -> tuple:
        if self._context_retriever:
            return self._context_retriever.build_layered_context(query, history)
        return "", "", ""

    def _search_cross_session_relevant(
        self, query: str, current_session_id: str = "", top_k: int = 20
    ) -> List[Dict]:
        if self._context_retriever:
            return self._context_retriever.search_cross_session_relevant(
                query, current_session_id=current_session_id, top_k=top_k
            )
        return []

    def _auto_encode_media_paths(self, query: str) -> list:
        if self._media_encoder:
            return self._media_encoder.auto_encode_media_paths(query)
        return []

    def _get_media_blocks_for_query(self, query: str) -> list:
        if self._media_encoder:
            return self._media_encoder.get_media_blocks_for_query(query)
        return []

    def _collect_relevant_tools(self, query: str) -> List[Dict]:
        """委托给 ToolLoopEngine"""
        return self._tool_loop_engine.collect_relevant_tools(query)
    
    @staticmethod

    async def _run_tool_loop(self, messages: List[Dict], tools: List[Dict], max_rounds: int = 12) -> str:
        return await self._tool_loop_engine.run_tool_loop(messages, tools, max_rounds)

    async def _process_sync(self, messages: List[Dict], tools: List[Dict]) -> str:
        return await self._tool_loop_engine.process_sync(messages, tools)

    async def _process_stream(self, messages: List[Dict], tools: List[Dict]) -> AsyncGenerator[str, None]:
        async for chunk in self._tool_loop_engine.process_stream(messages, tools):
            yield chunk

    async def _verify_response(self, messages: List[Dict], response: str) -> None:
        return await self._tool_loop_engine.verify_response(messages, response)

    def _build_text_tool_prompt(tools: List[Dict]) -> str:
        from ..tool_loop import ToolLoopEngine
        return ToolLoopEngine.build_text_tool_prompt(tools)

    @staticmethod

    def _parse_text_tool_calls(text: str) -> List[Dict]:
        from ..tool_loop import ToolLoopEngine
        return ToolLoopEngine.parse_text_tool_calls(text)

    @staticmethod

    def _normalize_messages(messages: List[Dict]) -> List[Dict]:
        from ..tool_loop import ToolLoopEngine
        return ToolLoopEngine.normalize_messages(messages)

    def _pair_conversations(self, messages: List[Dict]) -> List[Dict]:
        return ContextRetriever.pair_conversations(messages)

    @staticmethod

    def _score_relevance(query: str, text: str) -> float:
        return ContextRetriever.score_relevance(query, text)

    @staticmethod

    def _compress_message(text: str, max_len: int = 400) -> str:
        return ContextRetriever.compress_message(text, max_len)
