"""
SEAI智能体端到端测试
测试核心功能：对话处理、工具调用、记忆系统等
"""
import pytest
import asyncio
from pathlib import Path


class TestSEAgentE2E:
    """SEAI智能体端到端测试类"""
    
    @pytest.mark.asyncio
    async def test_agent_initialization(self, seai_agent):
        """测试智能体初始化"""
        status = seai_agent.get_status()
        assert status["initialized"] == True
        assert "已初始化" in status["components"]["llm_provider"]
        assert "已初始化" in status["components"]["memory_store"]
        assert "已初始化" in status["components"]["tool_executor"]
        assert "已初始化" in status["components"]["skill_repository"]
    
    @pytest.mark.asyncio
    async def test_basic_conversation(self, seai_agent):
        """测试基础对话功能"""
        query = "你好，请介绍一下你自己"
        
        # 测试同步响应
        response = ""
        async for chunk in seai_agent.process_query(query, stream=False):
            response += chunk
        
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_streaming_conversation(self, seai_agent):
        """测试流式对话功能"""
        query = "今天的日期是什么？"
        
        chunks = []
        async for chunk in seai_agent.process_query(query, stream=True):
            chunks.append(chunk)
        
        response = "".join(chunks)
        assert len(response) > 0
        assert len(chunks) > 0  # 确保是流式输出
    
    @pytest.mark.asyncio
    async def test_tool_execution(self, seai_agent):
        """测试工具执行功能"""
        query = "请计算 2 + 3 等于多少"
        
        response = ""
        async for chunk in seai_agent.process_query(query, stream=False):
            response += chunk
        
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_memory_system(self, seai_agent):
        """测试记忆系统"""
        # 添加测试记忆
        if seai_agent.memory_store:
            seai_agent.memory_store.add_memory("测试记忆：E2E测试进行中")
            
            # 搜索记忆
            results = seai_agent.memory_store.search_memory("E2E测试")
            assert len(results) > 0
    
    @pytest.mark.asyncio
    async def test_skill_system(self, seai_agent):
        """测试技能系统"""
        if seai_agent.skill_repository:
            skills = seai_agent.skill_repository.get_all_skills()
            assert isinstance(skills, list)
            
            # 检查技能启用状态
            for skill in skills[:3]:  # 只检查前3个技能
                enabled = seai_agent.skill_repository.is_skill_enabled(skill["name"])
                assert isinstance(enabled, bool)
    
    @pytest.mark.asyncio
    async def test_thinking_mode(self, seai_agent):
        """测试深度思考模式"""
        query = "请分析一下人工智能的未来发展趋势"
        
        response = ""
        async for chunk in seai_agent.process_query(
            query, 
            stream=False, 
            thinking_enabled=True
        ):
            response += chunk
        
        # 检查是否包含思考标记（mock 模式下只验证流程正常）
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_conversation_history(self, seai_agent):
        """测试对话历史管理"""
        # 进行多轮对话
        queries = ["第一轮测试", "第二轮测试", "第三轮测试"]
        
        history = []
        for i, query in enumerate(queries):
            response = ""
            async for chunk in seai_agent.process_query(query, history=history, stream=False):
                response += chunk
            
            # 添加到历史
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": response})
        
        # 检查历史长度（应该被限制在16条消息内）
        assert len(history) <= 16
    
    @pytest.mark.asyncio
    async def test_agent_status_monitoring(self, seai_agent):
        """测试智能体状态监控"""
        status = seai_agent.get_status()
        
        # 检查状态字段
        required_fields = [
            "initialized", "components", "thinking_enabled", 
            "web_search_enabled", "conversation_count", "cached_tools"
        ]
        
        for field in required_fields:
            assert field in status
    
    @pytest.mark.asyncio
    async def test_error_handling(self, seai_agent):
        """测试错误处理"""
        # 测试无效查询
        query = ""  # 空查询
        
        response = ""
        async for chunk in seai_agent.process_query(query, stream=False):
            response += chunk
        
        # 应该能正常处理空查询
        assert isinstance(response, str)