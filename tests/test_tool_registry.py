"""
ToolRegistry 单元测试
"""
import pytest
from seai.core.tool_registry import ToolRegistry, safe_calculator


class TestSafeCalculator:
    """安全计算器单元测试"""

    def test_basic_arithmetic(self):
        assert safe_calculator("2 + 3") == "5"
        assert safe_calculator("10 - 4") == "6"
        assert safe_calculator("3 * 7") == "21"
        assert safe_calculator("8 / 2") == "4.0"

    def test_negative_numbers(self):
        assert safe_calculator("-5 + 3") == "-2"
        assert safe_calculator("10 + -3") == "7"

    def test_complex_expression(self):
        assert safe_calculator("2 + 3 * 4") == "14"
        assert safe_calculator("(2 + 3) * 4") == "20"

    def test_invalid_expression(self):
        with pytest.raises((ValueError, SyntaxError, Exception)):
            safe_calculator("import os")
        with pytest.raises((ValueError, SyntaxError, Exception)):
            safe_calculator("__import__('os')")
        with pytest.raises((ValueError, SyntaxError, Exception)):
            safe_calculator("open('file')")


class TestToolRegistry:
    """工具注册表单元测试"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    def test_initialization(self, registry):
        assert registry is not None
        assert len(registry._tools) > 0
        assert len(registry._definitions) > 0

    def test_default_tools_registered(self, registry):
        default_tools = ["calculator", "read_file", "write_file", "list_files", "web_search", "echo"]
        for tool in default_tools:
            assert tool in registry._tools, f"默认工具 {tool} 未注册"

    def test_register_custom_tool(self, registry):
        def custom_tool(args):
            return f"custom: {args.get('text', '')}"

        registry.register("custom_test", custom_tool, "自定义测试工具",
                          {"type": "object", "properties": {"text": {"type": "string"}}})

        assert "custom_test" in registry._tools
        assert any(d["function"]["name"] == "custom_test" for d in registry._definitions)

    @pytest.mark.asyncio
    async def test_execute_existing_tool(self, registry):
        result = await registry.execute_tool("echo", {"message": "hello world"})
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self, registry):
        with pytest.raises(ValueError):
            await registry.execute_tool("nonexistent_tool_xyz", {})

    @pytest.mark.asyncio
    async def test_calculator_tool(self, registry):
        result = await registry.execute_tool("calculator", {"expression": "2 + 3"})
        assert "5" in result

    def test_get_tool_definitions(self, registry):
        definitions = registry.get_tool_definitions()
        assert isinstance(definitions, list)
        assert len(definitions) > 0
        for d in definitions:
            assert "type" in d
            assert d["type"] == "function"
            assert "function" in d
            assert "name" in d["function"]

    def test_unregister_tool(self, registry):
        registry.register("temp_tool", lambda args: "temp", "临时工具")
        assert "temp_tool" in registry._tools
        registry.unregister_tool("temp_tool")
        assert "temp_tool" not in registry._tools

    def test_get_available_tools(self, registry):
        tools = registry.get_available_tools()
        assert isinstance(tools, list)
        assert "calculator" in tools
        assert "echo" in tools

    @pytest.mark.asyncio
    async def test_execute_compat(self, registry):
        result = await registry.execute("echo", {"message": "compat test"})
        assert "compat test" in result

    def test_register_tool_interface(self, registry):
        registry.register_tool("iface_test", lambda args: "ok", "接口测试")
        assert "iface_test" in registry._tools
