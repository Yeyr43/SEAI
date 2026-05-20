"""
Tool Loop Engine — 完整的工具调用引擎
职责：工具循环、流式处理、文本模式兼容、工具筛选、执行重试、反馈记录
从 SEAgent 提取，避免 agent.py 臃肿
"""
import asyncio
import json
import re as _re
import time
import uuid
from typing import List, Dict, Any, Optional, AsyncGenerator, Callable
from loguru import logger

from .tool_selector import (
    TOOL_TO_MEM_TYPE, TOOL_STORAGE_MODE, detect_intent, _build_tool_categories,
)
from .tool_formatter import build_text_tool_prompt, parse_text_tool_calls, normalize_messages


class ToolLoopEngine:
    """完整的工具调用引擎：工具循环、流式/同步处理、文本模式兼容"""

    def __init__(self, llm_provider=None, tool_executor=None, skill_system=None,
                 skill_repository=None, memory_store=None, error_handler=None,
                 evolution_service=None, conversation_service=None, feedback_loop=None,
                 data_dir=None, circuit_breaker=None, security=None):
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.skill_system = skill_system
        self.skill_repository = skill_repository
        self.memory_store = memory_store
        self.error_handler = error_handler
        self.evolution_service = evolution_service
        self.conversation_service = conversation_service
        self.feedback_loop = feedback_loop
        self.data_dir = data_dir
        self.circuit_breaker = circuit_breaker
        self.security = security
        self._tool_cache: Dict[str, Any] = {}
        self._last_tool_call_time: Dict[str, float] = {}
        self._max_tool_cache = 200
        self._skill_first_use: Dict[str, bool] = {}

    # ── 工具格式化（委托给模块级函数）──────────────

    @staticmethod
    def build_text_tool_prompt(tools: List[Dict]) -> str:
        return build_text_tool_prompt(tools)

    @staticmethod
    def parse_text_tool_calls(text: str) -> List[Dict]:
        return parse_text_tool_calls(text)

    @staticmethod
    def normalize_messages(messages: List[Dict]) -> List[Dict]:
        return normalize_messages(messages)

    # ── 工具筛选 ──────────────────────────────────

    def collect_relevant_tools(self, query: str) -> List[Dict]:
        base_tools = self.tool_executor.get_tool_definitions() if self.tool_executor else []
        intent = detect_intent(query)
        dynamic_categories = _build_tool_categories(base_tools)

        if intent == "general":
            pass
        elif intent in dynamic_categories:
            relevant = set(dynamic_categories.get(intent, []))
            relevant.update(dynamic_categories.get("file", []))
            relevant.update(dynamic_categories.get("general", []))
            base_tools = [
                t for t in base_tools
                if t.get("function", {}).get("name") in relevant
            ]

        if self.skill_repository and query:
            query_lower = query.lower()
            query_words = query_lower.split()
            for skill in self.skill_repository.get_all_skills():
                if not self.skill_repository.is_skill_enabled(skill["name"]):
                    continue
                skill_text = skill["name"] + " " + skill.get("description", "")
                skill_text_lower = skill_text.lower()
                if any(kw in skill_text_lower for kw in query_words):
                    tool_name = f"skill_{skill['name']}"
                    skill_first = not self._skill_first_use.get(skill["name"], True)
                    description = skill.get("description", f"执行技能 {skill['name']}")
                    if not skill_first:
                        description = f"{skill['name']}: {skill.get('command', '')}"
                    base_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": description,
                            "parameters": {"type": "object", "properties": {"input": {"type": "string"}}}
                        }
                    })
                    self._skill_first_use[skill["name"]] = False
        return base_tools

    # ── 工具执行重试 ──────────────────────────────

    async def execute_tool_with_retry(self, tool_name: str, arguments: Dict[str, Any],
                                       max_retries: int = 2) -> str:
        ss = self.skill_system
        te = self.tool_executor
        es = self.evolution_service

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if tool_name.startswith("skill_"):
                    skill_name = tool_name[6:]
                    result = str(await ss.execute_skill(skill_name, arguments, security=self.security))
                else:
                    result = str(await te.execute_tool(tool_name, arguments))
                self.log_tool_feedback(tool_name, arguments, result)
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"工具 {tool_name} 执行失败 (尝试 {attempt+1}/{max_retries+1}): {last_error}")
                if attempt < max_retries and self.llm_provider:
                    fix_prompt = f"""工具 {tool_name} 执行失败，错误信息: {last_error}
原始参数: {json.dumps(arguments, ensure_ascii=False)}
请分析错误原因并提供修正后的参数。只输出JSON格式的修正参数，不要其他内容。
示例输出: {{"path": "修正后的路径", "content": "修正后的内容"}}"""
                    try:
                        response = await self.llm_provider.chat([{"role": "user", "content": fix_prompt}])
                        fixed_args = json.loads(response) if isinstance(response, str) else response
                        if isinstance(fixed_args, str):
                            fixed_args = json.loads(fixed_args)
                        if isinstance(fixed_args, dict):
                            arguments = fixed_args
                            logger.info(f"工具 {tool_name} 参数已自动修正: {arguments}")
                    except Exception:
                        logger.warning("Tool auto-fix LLM call failed")

        if es and hasattr(es, 'auto_fix_tool'):
            try:
                fix_result = await es.auto_fix_tool(tool_name, last_error, arguments)
                if fix_result:
                    logger.info(f"工具 {tool_name} 自修复: {fix_result}")
            except Exception:
                logger.warning("Tool auto-fix failed")

        raise last_error

    # ── 工具反馈 ──────────────────────────────────

    def log_tool_feedback(self, tool_name: str, input_args: dict, output: str):
        ms = self.memory_store
        if not ms:
            return

        mem_type = "text"
        if tool_name in TOOL_TO_MEM_TYPE:
            try:
                mem_type = TOOL_TO_MEM_TYPE[tool_name](input_args)
            except Exception:
                mem_type = "text"

        storage_mode = TOOL_STORAGE_MODE.get(tool_name, "auto")

        if tool_name in ("encode_image", "encode_audio") and output and len(output) > 200:
            media_id = uuid.uuid4().hex[:12]
            media_type = "image_analysis" if tool_name == "encode_image" else "audio_analysis"
            path_hint = input_args.get("path", "")
            success = ms.store_media(media_id, media_type, output,
                {"tool": tool_name, "path": path_hint, "timestamp": time.time()})
            summary = f"[{tool_name}] {path_hint} → 已编码并存储 (media_id={media_id})"
            if success and hasattr(ms, 'add_long_term_memory_with_links'):
                ms.add_long_term_memory_with_links(
                    summary, mem_type=media_type, storage_mode="original", media_id=media_id
                )
        else:
            preview = output[:300] if output else "(空)"
            if hasattr(ms, 'add_long_term_memory_with_links'):
                ms.add_long_term_memory_with_links(
                    f"[工具] {tool_name}({json.dumps(input_args, ensure_ascii=False)[:100]}) → {preview}",
                    mem_type=mem_type, storage_mode=storage_mode
                )

    # ── 响应验证 ──────────────────────────────────

    async def verify_response(self, messages: List[Dict], response: str) -> None:
        if not response or len(response) < 20:
            return
        try:
            check_msgs = list(messages[-6:]) if len(messages) > 6 else list(messages)
            check_msgs.append({
                "role": "system",
                "content": "检查上一轮工具执行结果：如果没有完成用户任务，请继续调用工具。如果已完成，回复 DONE。"
            })
            check_msgs.append({"role": "assistant", "content": response})
            if self.llm_provider:
                verification = await self.llm_provider.chat(check_msgs)
                if verification and "done" in str(verification).strip().lower():
                    logger.info("响应验证: 任务已完成")
        except Exception:
            logger.warning("响应验证失败")

    # ═══════════════════════════════════════════
    # 核心工具循环
    # ═══════════════════════════════════════════

    async def run_tool_loop(self, messages: List[Dict], tools: List[Dict],
                            max_rounds: int = 12) -> str:
        current_messages = self.normalize_messages(messages)
        _native_mode = True
        _text_tool_prompt_appended = False
        _native_failed = False

        for _round in range(max_rounds):
            if _native_mode:
                if _native_failed:
                    _native_mode = False
                    current_messages = self.normalize_messages(messages)
                    text_prompt = self.build_text_tool_prompt(tools)
                    current_messages.append({"role": "system", "content": text_prompt})
                    _text_tool_prompt_appended = True
                    continue

                try:
                    result = await self.llm_provider.chat_with_tools(
                        current_messages, tools, stream=False
                    )
                    self.circuit_breaker.on_success() if self.circuit_breaker else None
                except Exception as e:
                    if self.circuit_breaker:
                        self.circuit_breaker.on_failure()
                    logger.warning(f"原生 function calling 失败: {e}，切换为文本模式")
                    _native_failed = True
                    _native_mode = False
                    current_messages = self.normalize_messages(messages)
                    text_prompt = self.build_text_tool_prompt(tools)
                    current_messages.append({"role": "system", "content": text_prompt})
                    _text_tool_prompt_appended = True
                    continue

                if isinstance(result, str):
                    if _round == 0 and tools:
                        logger.info("首轮未调用工具，注入强制工具调用指令重试")
                        current_messages.append({
                            "role": "system",
                            "content": (
                                "你尚未调用任何工具函数。要完成用户请求，你必须立即调用对应的工具函数。"
                                "不要描述你打算做什么——直接调用工具。"
                            )
                        })
                        continue
                    if tools and not _text_tool_prompt_appended:
                        logger.info("原生 function calling 不可用，切换为文本模式")
                        _native_mode = False
                        current_messages = self.normalize_messages(messages)
                        text_prompt = self.build_text_tool_prompt(tools)
                        current_messages.append({"role": "system", "content": text_prompt})
                        _text_tool_prompt_appended = True
                        continue
                    return result

                if isinstance(result, dict) and result.get("tool_calls"):
                    tool_calls_data = result["tool_calls"]
                    assistant_content = result.get("content") or ""
                else:
                    content = result.get("content", "") if isinstance(result, dict) else ""
                    if _round == 0 and tools:
                        logger.info("首轮未调用工具(dict)，注入强制工具调用指令重试")
                        current_messages.append({
                            "role": "system",
                            "content": "你尚未调用任何工具函数。必须立即调用工具。不要描述——直接调用。"
                        })
                        continue
                    if tools and not _text_tool_prompt_appended:
                        logger.info("原生 function calling 不可用，切换为文本模式")
                        _native_mode = False
                        current_messages = self.normalize_messages(messages)
                        text_prompt = self.build_text_tool_prompt(tools)
                        current_messages.append({"role": "system", "content": text_prompt})
                        _text_tool_prompt_appended = True
                        continue
                    return content if content else ""
            else:
                try:
                    result = await self.llm_provider.chat(current_messages)
                    if self.circuit_breaker:
                        self.circuit_breaker.on_success()
                except Exception as e:
                    if self.circuit_breaker:
                        self.circuit_breaker.on_failure()
                    logger.error(f"文本模式 LLM 调用异常: {e}")
                    return f"处理异常: {str(e)}"

                if not isinstance(result, str):
                    result = str(result)

                tool_calls_data = self.parse_text_tool_calls(result)
                if tool_calls_data:
                    logger.info(
                        f"文本模式解析到 {len(tool_calls_data)} 个工具调用: "
                        f"{[tc['function']['name'] for tc in tool_calls_data]}"
                    )
                    clean_result = _re.sub(
                        r'```tool_call\s*\n.*?```', '', result,
                        flags=_re.DOTALL | _re.IGNORECASE
                    ).strip()
                    assistant_content = clean_result
                else:
                    logger.info("文本模式完成（无工具调用）")
                    return result

            if tool_calls_data:
                if _native_mode:
                    assistant_msg = {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": tool_calls_data
                    }
                    if isinstance(result, dict) and result.get("reasoning_content"):
                        assistant_msg["reasoning_content"] = result["reasoning_content"]
                    current_messages.append(assistant_msg)

                    for tc in tool_calls_data:
                        tool_name = tc["function"]["name"]
                        try:
                            tool_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                        except (json.JSONDecodeError, TypeError):
                            tool_args = {}
                        try:
                            tool_result = await self.execute_tool_with_retry(tool_name, tool_args)
                        except Exception as e:
                            tool_result = f"工具执行失败: {str(e)}"
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": str(tool_result)
                        })
                else:
                    if assistant_content:
                        current_messages.append({
                            "role": "assistant",
                            "content": assistant_content
                        })
                    results_parts = ["[工具执行结果]\n"]
                    for tc in tool_calls_data:
                        tool_name = tc["function"]["name"]
                        try:
                            tool_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                        except (json.JSONDecodeError, TypeError):
                            tool_args = {}
                        try:
                            tool_result = await self.execute_tool_with_retry(tool_name, tool_args)
                        except Exception as e:
                            tool_result = f"工具执行失败: {str(e)}"
                        results_parts.append(
                            f"工具 {tool_name}({json.dumps(tool_args, ensure_ascii=False)}) 返回:\n{tool_result}\n"
                        )
                    current_messages.append({
                        "role": "user",
                        "content": "\n".join(results_parts)
                    })
                current_messages = self.normalize_messages(current_messages)
                continue

        try:
            current_messages.append({
                "role": "system",
                "content": "你已调用多轮工具，请基于已有的工具执行结果，用文字简洁地回答用户的原始问题。不要使用工具。"
            })
            final = await self.llm_provider.chat(current_messages)
            return final if final else "工具调用完成，但未能生成总结。"
        except Exception:
            return "工具调用达到最大轮次限制，请简化你的请求。"

    # ═══════════════════════════════════════════
    # 流式处理
    # ═══════════════════════════════════════════

    async def process_stream(self, messages: List[Dict], tools: List[Dict]) -> AsyncGenerator[str, None]:
        TOOL_CALL_MARKER = _re.compile(r'__TOOL_CALLS__(.*?)__/TOOL_CALLS__')
        FALLBACK_FLAG = "所有LLM端点均已尝试失败"

        current_messages = self.normalize_messages(messages)
        force_injected = False

        for _round in range(10):
            collected_text = []
            tool_calls_json = None
            needs_fallback = False

            try:
                if tools:
                    gen = self.llm_provider.chat_with_tools(current_messages, tools, stream=True)
                else:
                    gen = self.llm_provider.chat_stream(current_messages)

                async for chunk in gen:
                    if chunk.startswith(FALLBACK_FLAG) and tools:
                        needs_fallback = True
                        break

                    collected_text.append(chunk)
                    m = TOOL_CALL_MARKER.search(chunk)
                    if m:
                        tool_calls_json = m.group(1)
                        clean = TOOL_CALL_MARKER.sub('', chunk)
                        if clean.strip():
                            yield clean
                    elif tools:
                        if '__TOOL_CALLS__' not in chunk and '__/TOOL_CALLS__' not in chunk:
                            yield chunk
                        elif not TOOL_CALL_MARKER.search(chunk):
                            yield chunk
                    else:
                        yield chunk

                if needs_fallback:
                    logger.warning("流式工具调用失败，回退到同步 tool_loop")
                    result = await self.run_tool_loop(current_messages, tools)
                    if result:
                        yield result
                    return

                if self.circuit_breaker:
                    self.circuit_breaker.on_success()
            except Exception as e:
                if self.circuit_breaker:
                    self.circuit_breaker.on_failure()
                logger.error(f"流式LLM异常: {e}")
                yield f"流式处理异常: {str(e)}"
                return

            full_text = "".join(collected_text)

            if tool_calls_json and tools:
                try:
                    tool_calls_data = json.loads(tool_calls_json)
                except json.JSONDecodeError:
                    tool_calls_data = []

                assistant_content = TOOL_CALL_MARKER.sub('', full_text).strip()
                current_messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls_data
                })

                for tc in tool_calls_data:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}
                    try:
                        tool_result = await self.execute_tool_with_retry(tool_name, tool_args)
                    except Exception as e:
                        tool_result = f"工具执行失败: {str(e)}"
                    current_messages.append({
                        "role": "user",
                        "content": f"[工具 {tool_name}({json.dumps(tool_args, ensure_ascii=False)}) 返回]\n{tool_result}"
                    })
                continue

            if full_text.strip():
                return

            if tools and not force_injected:
                force_injected = True
                current_messages.append({
                    "role": "system",
                    "content": (
                        "你有可用的工具函数。要完成用户的请求，请直接调用工具函数，"
                        "不要只描述你打算做什么。立即调用相应的工具函数来执行操作。"
                    )
                })
                continue

            return

        if current_messages:
            try:
                current_messages.append({
                    "role": "system",
                    "content": "请基于以上对话，用文字简洁地回答用户。不要使用工具。"
                })
                final = await self.llm_provider.chat(current_messages)
                if final:
                    yield final
            except Exception:
                yield "流式处理达到最大轮次限制。"

    # ═══════════════════════════════════════════
    # 同步处理
    # ═══════════════════════════════════════════

    async def process_sync(self, messages: List[Dict], tools: List[Dict]) -> str:
        if not self.llm_provider:
            return "LLM 提供者未初始化"
        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            return "LLM 服务暂时不可用（熔断保护已触发），请稍后重试"
        result = await self.run_tool_loop(messages, tools)
        if tools and result and not result.startswith("工具调用达到最大轮次"):
            await self.verify_response(messages, result)
        return result
