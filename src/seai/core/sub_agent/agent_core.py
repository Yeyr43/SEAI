"""
子 Agent 核心 — BaseSubAgent, SharedFileCache
"""
import asyncio
import json
import time
import uuid
from typing import Dict, List
from loguru import logger
from .task import AgentRole, CompressedResult, TOKEN_BUDGET_PER_SUB_AGENT
from ..lazy_import import LazyImport

tiktoken_lazy = LazyImport("tiktoken", "pip install tiktoken")

SUB_AGENT_TIMEOUT = 120


class SharedFileCache:
    """子 Agent 间共享的文件内容缓存"""

    def __init__(self, max_entries: int = 50, ttl_seconds: float = 300.0):
        self._cache: Dict[str, tuple] = {}
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

    def get(self, path: str) -> str | None:
        if path not in self._cache:
            return None
        content, timestamp = self._cache[path]
        if time.time() - timestamp > self.ttl_seconds:
            del self._cache[path]
            return None
        return content

    def set(self, path: str, content: str):
        if len(self._cache) >= self.max_entries:
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest]
        self._cache[path] = (content, time.time())

    def clear(self):
        self._cache.clear()


class BaseSubAgent:
    """子 Agent 基类 - 精简版智能体，仅携带最小上下文"""

    ROLE_PROMPTS = {
        AgentRole.EXPLORER: """你是 SEAI 探索 Agent。职责：搜索信息、读取文件、收集数据。
工具：web_search, fetch_url, read_file, list_files
规则：
1. 只做信息收集，不做修改
2. 搜索时优先使用多个关键词
3. 结果以结构化 JSON 返回：{"findings": [...], "sources": [...], "recommendation": "..."}
4. 如果文件不存在或搜索无结果，如实报告""",

        AgentRole.CODER: """你是 SEAI 编码 Agent。职责：代码生成、Bug 修复、测试编写。
工具：read_file, write_file, delete_file, list_files
规则：
1. 生成完整可运行的代码
2. 遵循现有代码风格
3. 添加必要的错误处理
4. 写入前确认路径在白名单内
5. 结果以 JSON 返回：{"files_created": [...], "files_modified": [...], "summary": "..."}""",

        AgentRole.REVIEWER: """你是 SEAI 审查 Agent。职责：代码审查、质量验证、安全检查。
工具：read_file
规则：
1. 检查代码逻辑正确性
2. 检查安全漏洞
3. 检查代码风格一致性
4. 结果以 JSON 返回：{"score": 0-10, "issues": [...], "suggestions": [...], "approved": bool}""",

        AgentRole.TEST_RUNNER: """你是 SEAI 测试 Agent。职责：测试执行、结果分析。
工具：read_file, list_files
规则：
1. 读取测试文件并分析测试逻辑
2. 模拟测试执行并报告预期结果
3. 结果以 JSON 返回：{"tests_total": N, "tests_passed": N, "tests_failed": N, "failures": [...]}""",
    }

    ROLE_TOOLS = {
        AgentRole.EXPLORER: ["web_search", "fetch_url", "read_file", "list_files"],
        AgentRole.CODER: ["read_file", "write_file", "delete_file", "list_files"],
        AgentRole.REVIEWER: ["read_file", "list_files"],
        AgentRole.TEST_RUNNER: ["read_file", "list_files"],
    }

    def __init__(self, role: AgentRole, agent_id: str = None, llm_provider=None,
                 tool_executor=None, file_cache: SharedFileCache = None):
        self.role = role
        self.agent_id = agent_id or uuid.uuid4().hex[:8]
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.file_cache = file_cache or SharedFileCache()
        self._token_used = 0
        self._start_time = 0.0

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        if tiktoken_lazy.available:
            return len(tiktoken_lazy.get().get_encoding("cl100k_base").encode(text))
        return len(text) // 2

    def _build_system_prompt(self, task_description: str, context: str = "") -> str:
        role_prompt = self.ROLE_PROMPTS.get(self.role, "")
        parts = [role_prompt]
        if context:
            parts.append(f"\n## 任务上下文\n{context}")
        parts.append(f"\n## 当前任务\n{task_description}")
        parts.append("\n只输出 JSON 格式结果，不要额外解释。")
        return "\n\n".join(parts)

    def _filter_tools(self, all_tools: List[Dict]) -> List[Dict]:
        allowed = self.ROLE_TOOLS.get(self.role, [])
        if not allowed:
            return []
        return [t for t in all_tools if t.get("function", {}).get("name") in allowed]

    async def execute(self, task_description: str, context: str = "",
                      max_tokens: int = TOKEN_BUDGET_PER_SUB_AGENT) -> CompressedResult:
        self._start_time = time.time()
        self._token_used = 0

        if not self.llm_provider:
            return CompressedResult(
                agent_role=self.role, agent_id=self.agent_id, status="error",
                summary="LLM 提供者未初始化",
                elapsed_ms=(time.time() - self._start_time) * 1000,
            )

        system_prompt = self._build_system_prompt(task_description, context)
        self._token_used += self._estimate_tokens(system_prompt)

        tools = []
        if self.tool_executor:
            all_tools = self.tool_executor.get_tool_definitions()
            tools = self._filter_tools(all_tools)
            self._token_used += sum(self._estimate_tokens(json.dumps(t, ensure_ascii=False)) for t in tools)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_description},
        ]

        if self._token_used >= max_tokens:
            logger.warning(f"子 Agent {self.agent_id} system+tool 已超预算 ({self._token_used} >= {max_tokens})，跳过 API 调用")
            return CompressedResult(
                agent_role=self.role, agent_id=self.agent_id, status="truncated",
                summary="System prompt + tools 已超出 Token 预算上限",
                token_used=self._token_used,
                elapsed_ms=(time.time() - self._start_time) * 1000,
            )

        try:
            response = await asyncio.wait_for(
                self._process_with_tools(messages, tools, max_tokens),
                timeout=SUB_AGENT_TIMEOUT,
            )
            result = self._parse_json_response(response)
            return CompressedResult(
                agent_role=self.role, agent_id=self.agent_id,
                status=result.get("status", "success"),
                summary=result.get("summary", response[:500]),
                files_changed=result.get("files_changed", result.get("files_created", [])) + result.get("files_modified", []),
                test_results=result.get("test_results", result.get("tests", {})),
                warnings=result.get("warnings", []),
                data=result, token_used=self._token_used,
                elapsed_ms=(time.time() - self._start_time) * 1000,
            )
        except asyncio.TimeoutError:
            return CompressedResult(
                agent_role=self.role, agent_id=self.agent_id, status="timeout",
                summary=f"子 Agent {self.role.value} 执行超时 ({SUB_AGENT_TIMEOUT}s)",
                token_used=self._token_used,
                elapsed_ms=(time.time() - self._start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"子 Agent {self.agent_id} 执行异常: {e}")
            return CompressedResult(
                agent_role=self.role, agent_id=self.agent_id, status="error",
                summary=str(e)[:500], token_used=self._token_used,
                elapsed_ms=(time.time() - self._start_time) * 1000,
            )

    async def _process_with_tools(self, messages: List[Dict], tools: List[Dict],
                                   max_tokens: int, max_rounds: int = 3) -> str:
        current_messages = list(messages)
        for _ in range(max_rounds):
            if self._token_used >= max_tokens:
                return json.dumps({"status": "truncated", "summary": "达到 Token 预算上限"})
            input_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in current_messages)
            if input_tokens + 500 > max_tokens - self._token_used:
                logger.warning(f"子 Agent {self.agent_id} 输入过长 ({input_tokens}t)，跳过本轮")
                return json.dumps({"status": "truncated", "summary": f"输入超长 ({input_tokens}t)"})
            try:
                result = await self.llm_provider.chat_with_tools(current_messages, tools, stream=False)
            except Exception as e:
                logger.error(f"子 Agent LLM 调用失败: {e}")
                return json.dumps({"status": "error", "summary": str(e)})

            if isinstance(result, str):
                self._token_used += self._estimate_tokens(result)
                return result
            if isinstance(result, dict):
                content = result.get("content", "")
                self._token_used += self._estimate_tokens(content)
                if result.get("tool_calls"):
                    current_messages.append({"role": "assistant", "content": content, "tool_calls": result["tool_calls"]})
                    for tc in result["tool_calls"]:
                        tool_name = tc["function"]["name"]
                        try:
                            tool_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                        except json.JSONDecodeError:
                            tool_args = {}
                        if tool_name == "read_file" and self.file_cache:
                            path = tool_args.get("path", "")
                            cached = self.file_cache.get(path)
                            tool_result = cached if cached else (await self.tool_executor.execute_tool(tool_name, tool_args) if self.tool_executor else "工具执行器未初始化")
                            if not cached and self.tool_executor:
                                self.file_cache.set(path, tool_result)
                        elif self.tool_executor:
                            tool_result = await self.tool_executor.execute_tool(tool_name, tool_args)
                        else:
                            tool_result = "工具执行器未初始化"
                        self._token_used += self._estimate_tokens(str(tool_result))
                        current_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(tool_result)[:2000]})
                    continue
                if content:
                    return content
                return json.dumps({"status": "empty", "summary": "无有效输出"})
        return json.dumps({"status": "max_rounds", "summary": "达到最大工具调用轮次"})

    def _parse_json_response(self, response: str) -> dict:
        try:
            import re
            json_match = None
            for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
                match = re.search(pattern, response)
                if match:
                    json_match = match.group(0)
                    break
            if json_match:
                return json.loads(json_match)
        except (json.JSONDecodeError, ValueError):
            pass
        return {"status": "success", "summary": response[:500]}


def estimate_query_tokens(query: str, system_prompt: str = "", tools: List[Dict] = None) -> int:
    if tiktoken_lazy.available:
        enc = tiktoken_lazy.get().get_encoding("cl100k_base")
        tokens = len(enc.encode(query))
        tokens += len(enc.encode(system_prompt)) if system_prompt else 0
        if tools:
            tokens += sum(len(enc.encode(json.dumps(t, ensure_ascii=False))) for t in tools)
        return tokens
    tokens = len(query) // 2
    tokens += len(system_prompt) // 2
    if tools:
        tokens += sum(len(json.dumps(t, ensure_ascii=False)) // 2 for t in tools)
    return tokens
