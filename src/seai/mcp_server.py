#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SEAI MCP Server 包装器
将 SEAI 核心能力暴露为 MCP 工具，供外部 AI 客户端调用
"""
import json
import asyncio
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seai-mcp")

MCP_TOOLS = [
    {
        "name": "seai_chat",
        "description": "向 SEAI 发送消息并获取回复",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "用户消息内容"},
                "session_id": {"type": "string", "description": "会话 ID（可选）"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "seai_search_memory",
        "description": "搜索 SEAI 长期记忆",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
                "search_mode": {
                    "type": "string",
                    "enum": ["semantic", "text", "hybrid"],
                    "description": "搜索模式",
                    "default": "semantic",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "seai_list_skills",
        "description": "列出所有已安装的技能",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seai_execute_skill",
        "description": "执行指定技能",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "技能名称"},
                "params": {"type": "object", "description": "技能参数"},
            },
            "required": ["skill_name"],
        },
    },
    {
        "name": "seai_trigger_evolve",
        "description": "手动触发 SEAI 深度进化",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "seai_get_status",
        "description": "获取 SEAI 运行状态",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class SEAIMCPServer:
    def __init__(self, agent=None):
        self._agent = agent
        self._tools = MCP_TOOLS

    def set_agent(self, agent):
        self._agent = agent

    def get_tools(self):
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if not self._agent:
            return json.dumps({"error": "SEAI agent 未初始化"})

        try:
            if tool_name == "seai_chat":
                message = arguments.get("message", "")
                session_id = arguments.get("session_id", "")
                result = await self._agent.chat(message, session_id=session_id)
                return json.dumps({"response": result}, ensure_ascii=False)

            elif tool_name == "seai_search_memory":
                query = arguments.get("query", "")
                top_k = arguments.get("top_k", 5)
                search_mode = arguments.get("search_mode", "semantic")
                if self._agent.memory_store:
                    results = self._agent.memory_store.search(query, top_k=top_k, search_mode=search_mode)
                    return json.dumps({"results": results}, ensure_ascii=False)
                return json.dumps({"results": []})

            elif tool_name == "seai_list_skills":
                if self._agent.skill_repository:
                    skills = self._agent.skill_repository.get_all_skills()
                    return json.dumps({"skills": skills}, ensure_ascii=False)
                return json.dumps({"skills": []})

            elif tool_name == "seai_execute_skill":
                skill_name = arguments.get("skill_name", "")
                params = arguments.get("params", {})
                if self._agent.skill_repository:
                    result = await self._agent.skill_repository.execute_skill(skill_name, params)
                    return json.dumps({"result": result}, ensure_ascii=False)
                return json.dumps({"error": "技能仓库未初始化"})

            elif tool_name == "seai_trigger_evolve":
                if hasattr(self._agent, 'deep_evolve'):
                    result = await self._agent.deep_evolve()
                    return json.dumps(result, ensure_ascii=False)
                return json.dumps({"error": "深度进化不可用"})

            elif tool_name == "seai_get_status":
                status = {
                    "agent_ready": self._agent is not None,
                    "llm_ready": self._agent.llm_provider is not None if self._agent else False,
                    "memory_ready": self._agent.memory_store is not None if self._agent else False,
                    "skills_count": len(self._agent.skill_repository.get_all_skills()) if self._agent and self._agent.skill_repository else 0,
                }
                return json.dumps(status, ensure_ascii=False)

            else:
                return json.dumps({"error": f"未知工具: {tool_name}"})

        except Exception as e:
            logger.error(f"MCP 工具调用异常 [{tool_name}]: {e}")
            return json.dumps({"error": str(e)})


async def main():
    server = SEAIMCPServer()
    print(json.dumps({"tools": server.get_tools()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())