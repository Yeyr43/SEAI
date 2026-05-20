"""
进化系统单元测试
覆盖：EvolutionTester、JSON Schema 校验、deep_evolve、_auto_fix_tool
"""
import pytest
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from seai.core.evolution_tester import EvolutionTester, EvolutionTestCase, EvolutionTestResult
from seai.core.evolution_service import EvolutionService
from seai.core.agent import SEAgent
from seai.core.config import ConfigManager, config_manager


class TestEvolutionTester:
    """进化试验场单元测试"""

    @pytest.fixture
    def tester(self, tmp_path):
        return EvolutionTester(tmp_path)

    def test_add_test_case(self, tester):
        tester.add_test_case("test_skill", {"input": "hello"}, "hello world")
        assert "test_skill" in tester.test_cases
        assert len(tester.test_cases["test_skill"]) == 1
        assert tester.test_cases["test_skill"][0].skill_name == "test_skill"

    def test_add_multiple_cases(self, tester):
        for i in range(3):
            tester.add_test_case(f"skill_{i}", {"input": str(i)}, f"output_{i}")
        assert len(tester.test_cases) == 3

    def test_record_from_execution_success(self, tester):
        tester.record_from_execution("new_skill", {"input": "test"}, "success output", True)
        assert "new_skill" in tester.test_cases
        assert len(tester.test_cases["new_skill"]) == 1

    def test_record_from_execution_failure(self, tester):
        tester.record_from_execution("bad_skill", {"input": "test"}, "", False)
        assert "bad_skill" not in tester.test_cases

    def test_record_max_5_cases(self, tester):
        for i in range(7):
            tester.record_from_execution("capped", {"i": i}, f"output_{i}", True)
        assert len(tester.test_cases["capped"]) <= 5

    def test_test_skill_improvement_no_cases(self, tester):
        result = tester.test_skill_improvement(
            "unknown", {"name": "old"}, {"name": "new"},
            skill_executor=lambda d, a: "output"
        )
        assert result.passed is True
        assert result.test_cases_count == 0

    def test_test_skill_improvement_with_cases(self, tester):
        tester.add_test_case("calc", {"expr": "1+1"}, "2")
        tester.add_test_case("calc", {"expr": "2*3"}, "6")

        def executor(definition, args):
            if definition.get("name") == "old":
                return "error"
            return "result: 2"

        result = tester.test_skill_improvement(
            "calc",
            {"name": "old"},
            {"name": "new"},
            skill_executor=executor
        )
        assert result.test_cases_count == 2
        assert isinstance(result.old_score, float)
        assert isinstance(result.new_score, float)

    def test_score_match_exact(self, tester):
        score = tester._score_match("hello world", "hello world")
        assert score == 1.0

    def test_score_match_partial(self, tester):
        score = tester._score_match("hello world", "hello")
        assert score == 1.0

    def test_score_match_no_match(self, tester):
        score = tester._score_match("hello", "goodbye")
        assert score == 0.0

    def test_score_match_empty(self, tester):
        assert tester._score_match("", "pattern") == 0.0
        assert tester._score_match("output", "") == 0.0

    def test_get_skill_test_stats(self, tester):
        tester.add_test_case("stats_skill", {"a": 1}, "result")
        stats = tester.get_skill_test_stats("stats_skill")
        assert stats["skill_name"] == "stats_skill"
        assert stats["test_case_count"] == 1

    def test_persistence(self, tmp_path):
        tester1 = EvolutionTester(tmp_path)
        tester1.add_test_case("persist", {"x": 1}, "y")
        tester2 = EvolutionTester(tmp_path)
        assert "persist" in tester2.test_cases
        assert len(tester2.test_cases["persist"]) == 1


class TestJSONSchemaValidation:
    """JSON Schema 校验单元测试"""

    @pytest.fixture
    def agent(self):
        agent = SEAgent()
        return agent

    def test_valid_full_optimization(self, agent):
        data = {
            "analysis": "测试分析",
            "update_skills": [
                {"name": "test", "content": "SKILL content", "command": "echo test", "description": "测试技能"}
            ],
            "update_memory": [
                {"action": "add", "text": "测试记忆"}
            ]
        }
        result = agent._validate_optimization_json(json.dumps(data))
        assert result is not None
        assert result["analysis"] == "测试分析"

    def test_valid_skills_only(self, agent):
        data = {
            "analysis": "仅技能更新",
            "update_skills": [
                {"name": "skill1", "content": "content1"}
            ]
        }
        result = agent._validate_optimization_json(json.dumps(data))
        assert result is not None

    def test_valid_memory_only(self, agent):
        data = {
            "analysis": "仅记忆更新",
            "update_memory": [
                {"action": "archive", "text": "归档内容"}
            ]
        }
        result = agent._validate_optimization_json(json.dumps(data))
        assert result is not None

    def test_missing_required_skill_name(self, agent):
        data = {
            "analysis": "缺少技能名",
            "update_skills": [
                {"content": "no name"}
            ]
        }
        result = agent._validate_optimization_json(json.dumps(data))
        assert result is None

    def test_invalid_memory_action(self, agent):
        data = {
            "analysis": "无效操作",
            "update_memory": [
                {"action": "invalid_action", "text": "test"}
            ]
        }
        result = agent._validate_optimization_json(json.dumps(data))
        assert result is None

    def test_empty_optimization(self, agent):
        data = {"analysis": "无操作"}
        result = agent._validate_optimization_json(json.dumps(data))
        assert result is None

    def test_json_with_extra_text(self, agent):
        raw = '这是解释文字\n{"analysis": "test", "update_skills": [{"name": "s", "content": "c"}]}\n更多文字'
        result = agent._validate_optimization_json(raw)
        assert result is not None
        assert result["analysis"] == "test"

    def test_json_with_trailing_comma(self, agent):
        raw = '{"analysis": "test", "update_skills": [{"name": "s", "content": "c",}],}'
        result = agent._validate_optimization_json(raw)
        assert result is not None

    def test_no_json_block(self, agent):
        result = agent._validate_optimization_json("纯文本无JSON")
        assert result is None

    def test_malformed_json(self, agent):
        result = agent._validate_optimization_json('{"analysis": "test", broken}')
        assert result is None


class TestDeepEvolve:
    """深度进化单元测试"""

    @pytest.fixture
    def mock_agent(self, tmp_path):
        agent = SEAgent()
        agent.llm_provider = MagicMock()
        agent.llm_provider.chat = AsyncMock()
        agent.memory_store = MagicMock()
        agent.skill_repository = MagicMock()
        agent.skill_repository.get_all_skills = MagicMock(return_value=[])
        agent.skill_repository.get_skill_score = MagicMock(return_value=0.5)
        agent.skill_repository.is_skill_enabled = MagicMock(return_value=True)
        agent._error_handler = MagicMock()
        agent._error_handler.error_stats = {}
        agent._error_handler.recent_errors = []
        agent._evolution_tester = MagicMock()
        agent._evolution_service = EvolutionService(
            llm_provider=agent.llm_provider,
            skill_repository=agent.skill_repository,
            memory_store=agent.memory_store,
            error_handler=agent._error_handler,
            evolution_tester=agent._evolution_tester,
            data_dir=tmp_path,
            config=MagicMock(),
        )
        return agent

    @pytest.mark.asyncio
    async def test_deep_evolve_no_llm(self, mock_agent):
        mock_agent.llm_provider = None
        mock_agent._evolution_service.llm_provider = None
        result = await mock_agent.deep_evolve()
        assert result["success"] is False
        assert "LLM 提供者未初始化" in result["errors"]

    @pytest.mark.asyncio
    async def test_deep_evolve_validation_failure(self, mock_agent):
        mock_agent.llm_provider.chat.return_value = "无效输出"
        result = await mock_agent.deep_evolve()
        assert result["success"] is False
        assert any("校验失败" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_deep_evolve_skill_update_passes_tester(self, mock_agent):
        optimization = {
            "analysis": "优化低分技能",
            "update_skills": [
                {"name": "bad_skill", "content": "fixed content", "command": "fixed_cmd", "description": "修复后"}
            ]
        }
        mock_agent.llm_provider.chat.return_value = json.dumps(optimization)

        mock_agent.skill_repository.get_all_skills.return_value = [
            {"name": "bad_skill", "content": "old content", "command": "old_cmd"}
        ]
        mock_agent.skill_repository.get_skill_score = MagicMock(return_value=0.2)
        mock_agent.skill_repository.is_skill_enabled = MagicMock(return_value=True)
        mock_agent.skill_repository.update_skill = MagicMock()

        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.old_score = 0.3
        mock_result.new_score = 0.8
        mock_agent._evolution_tester.test_skill_improvement.return_value = mock_result

        result = await mock_agent.deep_evolve()
        assert result["success"] is True
        assert len(result["skill_changes"]) == 1
        assert result["skill_changes"][0]["validated"] is True

    @pytest.mark.asyncio
    async def test_deep_evolve_skill_update_fails_tester(self, mock_agent):
        optimization = {
            "analysis": "优化失败",
            "update_skills": [
                {"name": "bad_skill", "content": "worse content", "command": "bad_cmd"}
            ]
        }
        mock_agent.llm_provider.chat.return_value = json.dumps(optimization)

        mock_agent.skill_repository.get_all_skills.return_value = [
            {"name": "bad_skill", "content": "old content", "command": "old_cmd"}
        ]

        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.old_score = 0.5
        mock_result.new_score = 0.2
        mock_agent._evolution_tester.test_skill_improvement.return_value = mock_result

        result = await mock_agent.deep_evolve()
        assert any("未通过试验场验证" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_deep_evolve_memory_update(self, mock_agent):
        optimization = {
            "analysis": "记忆归档",
            "update_memory": [
                {"action": "add", "text": "新知识"},
                {"action": "archive", "text": "归档知识"}
            ]
        }
        mock_agent.llm_provider.chat.return_value = json.dumps(optimization)

        result = await mock_agent.deep_evolve()
        assert result["success"] is True
        assert len(result["memory_changes"]) == 2

    @pytest.mark.asyncio
    async def test_deep_evolve_exception_handling(self, mock_agent):
        mock_agent.llm_provider.chat.side_effect = Exception("LLM 调用失败")
        result = await mock_agent.deep_evolve()
        assert result["success"] is False
        assert "LLM 调用失败" in result["errors"]


class TestAutoFixTool:
    """工具自修复单元测试"""

    @pytest.fixture
    def mock_agent(self, tmp_path):
        agent = SEAgent()
        agent.llm_provider = MagicMock()
        agent.llm_provider.chat = AsyncMock()
        agent.skill_repository = MagicMock()
        agent.skill_repository.get_all_skills = MagicMock(return_value=[])
        agent.skill_repository.get_skill_score = MagicMock(return_value=0.5)
        agent.skill_repository.is_skill_enabled = MagicMock(return_value=True)
        agent._error_handler = MagicMock()
        agent._error_handler.error_stats = {}
        agent._error_handler.recent_errors = []
        mock_diagnosis = MagicMock()
        mock_diagnosis.severity = "medium"
        mock_diagnosis.probable_cause = "测试原因"
        mock_diagnosis.immediate_fix = "测试修复建议"
        agent._error_handler.handle_error.return_value = mock_diagnosis
        agent._evolution_tester = MagicMock()
        agent._evolution_service = EvolutionService(
            llm_provider=agent.llm_provider,
            skill_repository=agent.skill_repository,
            memory_store=MagicMock(),
            error_handler=agent._error_handler,
            evolution_tester=agent._evolution_tester,
            data_dir=tmp_path,
            config=MagicMock(),
        )
        return agent

    @pytest.mark.asyncio
    async def test_auto_fix_no_llm(self, mock_agent):
        mock_agent.llm_provider = None
        mock_agent._evolution_service.llm_provider = None
        result = await mock_agent._auto_fix_tool("test_tool", Exception("error"), {"arg": "val"})
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_fix_no_fix_type(self, mock_agent):
        mock_agent.llm_provider.chat.return_value = json.dumps({
            "analysis": "无法修复",
            "fix_type": "no_fix"
        })
        result = await mock_agent._auto_fix_tool("broken_tool", Exception("fatal"), {})
        assert result is not None
        assert "无法自动修复" in result

    @pytest.mark.asyncio
    async def test_auto_fix_validation_failure(self, mock_agent):
        mock_agent.llm_provider.chat.return_value = "invalid json"
        result = await mock_agent._auto_fix_tool("tool", Exception("err"), {})
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_fix_skill_update_passes(self, mock_agent):
        fix_data = {
            "analysis": "修复命令路径",
            "fix_type": "skill_update",
            "update_skills": [
                {"name": "broken_skill", "content": "fixed SKILL.md", "command": "fixed_cmd"}
            ]
        }
        mock_agent.llm_provider.chat.return_value = json.dumps(fix_data)

        mock_agent.skill_repository.get_all_skills.return_value = [
            {"name": "broken_skill", "content": "old", "command": "old_cmd"}
        ]
        mock_agent.skill_repository.update_skill = MagicMock()

        mock_result = MagicMock()
        mock_result.passed = True
        mock_agent._evolution_tester.test_skill_improvement.return_value = mock_result

        result = await mock_agent._auto_fix_tool("broken_skill", FileNotFoundError("cmd not found"), {"input": "test"})
        assert result is not None
        assert "已自动修复" in result

    @pytest.mark.asyncio
    async def test_auto_fix_tester_rejects(self, mock_agent):
        fix_data = {
            "analysis": "错误修复",
            "fix_type": "skill_update",
            "update_skills": [
                {"name": "skill", "content": "bad fix", "command": "bad_cmd"}
            ]
        }
        mock_agent.llm_provider.chat.return_value = json.dumps(fix_data)

        mock_agent.skill_repository.get_all_skills.return_value = [
            {"name": "skill", "content": "old", "command": "old_cmd"}
        ]

        mock_result = MagicMock()
        mock_result.passed = False
        mock_agent._evolution_tester.test_skill_improvement.return_value = mock_result

        result = await mock_agent._auto_fix_tool("skill", Exception("error"), {})
        assert result is None

    @pytest.mark.asyncio
    async def test_auto_fix_with_error_handler(self, mock_agent):
        fix_data = {
            "analysis": "路径修复",
            "fix_type": "skill_update",
            "update_skills": [
                {"name": "skill", "content": "fixed", "command": "/usr/bin/cmd"}
            ]
        }
        mock_agent.llm_provider.chat.return_value = json.dumps(fix_data)

        mock_agent.skill_repository.get_all_skills.return_value = [
            {"name": "skill", "content": "old", "command": "cmd"}
        ]
        mock_agent.skill_repository.update_skill = MagicMock()

        mock_result = MagicMock()
        mock_result.passed = True
        mock_agent._evolution_tester.test_skill_improvement.return_value = mock_result

        result = await mock_agent._auto_fix_tool("skill", FileNotFoundError("not found"), {"input": "test"})
        assert result is not None
        mock_agent._error_handler.handle_error.assert_called_once()
