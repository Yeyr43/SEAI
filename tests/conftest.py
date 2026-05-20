"""
测试配置和 fixture
提供单元测试、集成测试所需的共享 fixture
"""
import pytest
import asyncio
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

project_root = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(project_root))

from seai.core.config import config_manager


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir():
    path = Path(tempfile.mkdtemp(prefix="seai_test_"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def mock_llm_provider():
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="Mock LLM response")
    async def _mock_chat_stream(messages):
        yield "Mock "
        yield "stream "
        yield "response"
    provider.chat_stream = _mock_chat_stream
    provider.chat_with_tools = AsyncMock(return_value="Mock LLM response")
    provider.list_models = MagicMock(return_value=["mock-model"])
    provider.current_model = "mock-model"
    return provider


@pytest.fixture
def mock_memory_store():
    store = MagicMock()
    store.search = MagicMock(return_value=[])
    store.add = MagicMock()
    store.archive_old_memories = MagicMock()
    return store


@pytest.fixture
def mock_tool_executor():
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=("output", "", 0))
    return executor


@pytest.fixture
def mock_skill_repository():
    repo = MagicMock()
    repo.get_all_skills = MagicMock(return_value=[])
    repo.load_skills = AsyncMock()
    return repo


@pytest.fixture
def test_config(temp_dir):
    return {
        "test_data_dir": temp_dir,
        "timeout": 30,
        "max_retries": 3,
    }


@pytest.fixture
def seai_agent(mock_llm_provider, temp_dir):
    """Mock 模式的 SEAgent fixture — 不依赖真实 LLM/网络"""
    from seai.core.agent import SEAgent
    from seai.core.lifecycle import AgentLifecycleManager

    agent = SEAgent()

    # Mock lifecycle manager
    mock_lifecycle = AsyncMock(spec=AgentLifecycleManager)
    mock_lifecycle.is_initialized.return_value = True
    mock_lifecycle.get_component_status.return_value = {
        "llm_provider": "已初始化",
        "memory_store": "已初始化",
        "tool_executor": "已初始化",
        "skill_repository": "已初始化",
        "background_tasks": "未运行",
    }
    mock_lifecycle.llm_provider = mock_llm_provider
    mock_lifecycle.memory_store = MagicMock()
    mock_lifecycle.tool_executor = MagicMock()
    mock_lifecycle.skill_repository = MagicMock()

    agent.lifecycle_manager = mock_lifecycle
    agent.llm_provider = mock_llm_provider
    agent.data_dir = temp_dir
    agent.workspace = temp_dir

    agent._init_prompt_engine()
    agent._error_handler = MagicMock()
    agent._init_multi_agent()
    agent._init_pipeline()

    yield agent


@pytest.fixture
def real_seai_agent():
    """真实初始化的 SEAgent fixture — 需要真实 LLM，跳过测试条件自动处理"""
    from seai.core.agent import SEAgent
    import pytest_asyncio
    agent = SEAgent()
    try:
        loop = asyncio.get_event_loop()
        success = loop.run_until_complete(agent.initialize())
        if not success:
            pytest.skip("智能体初始化失败（跳过集成测试）")
    except Exception as e:
        pytest.skip(f"智能体初始化失败: {e}（跳过集成测试）")
    yield agent
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(agent.shutdown())
    except Exception:
        pass