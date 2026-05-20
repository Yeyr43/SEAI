"""
沙箱执行器 单元测试
覆盖：代码安全验证、Python 执行隔离、命令执行、超时控制
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def sandbox():
    try:
        from seai.core.sandbox import SandboxExecutor
        return SandboxExecutor(Path("/tmp/seai_test"))
    except Exception as e:
        pytest.skip(f"SandboxExecutor 初始化失败: {e}")


class TestCodeValidator:
    def test_safe_code_passes(self, sandbox):
        code = "x = 1 + 2\nprint(x)"
        is_safe, warnings = sandbox.validator.validate(code)
        assert is_safe
        assert len(warnings) == 0

    def test_os_system_blocked(self, sandbox):
        code = "import os\nos.system('rm -rf /')"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert any("os.system" in w for w in warnings)

    def test_subprocess_blocked(self, sandbox):
        code = "import subprocess\nsubprocess.run(['ls'])"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert any("subprocess" in w for w in warnings)

    def test_eval_blocked(self, sandbox):
        code = "eval('1+1')"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert any("eval()" in w for w in warnings)

    def test_exec_blocked(self, sandbox):
        code = "exec('import os')"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert any("exec()" in w for w in warnings)

    def test_socket_blocked(self, sandbox):
        code = "import socket\ns = socket.socket()"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert any("socket" in w for w in warnings)

    def test_file_write_blocked(self, sandbox):
        code = "open('/etc/passwd', 'w')"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert any("文件写入" in w for w in warnings)

    def test_safe_math_allowed(self, sandbox):
        code = "import math\nresult = math.sqrt(16)\nprint(result)"
        is_safe, warnings = sandbox.validator.validate(code)
        assert is_safe

    def test_safe_json_allowed(self, sandbox):
        code = "import json\ndata = json.loads('{\"key\": \"value\"}')\nprint(data)"
        is_safe, warnings = sandbox.validator.validate(code)
        assert is_safe

    def test_multiple_dangers(self, sandbox):
        code = "import os, subprocess\nos.system('ls')\nsubprocess.run(['cat', '/etc/passwd'])"
        is_safe, warnings = sandbox.validator.validate(code)
        assert not is_safe
        assert len(warnings) >= 2

    def test_sanitize_dunder_assign(self, sandbox):
        code = "__class__ = 'hack'"
        result = sandbox.validator.sanitize(code)
        assert "__class__" not in result or "BLOCKED" in result


class TestSandboxExecution:
    @pytest.mark.asyncio
    async def test_execute_simple_command(self, sandbox):
        stdout, stderr, code = await sandbox.execute("echo hello", timeout=10)
        assert code == 0
        assert "hello" in stdout

    @pytest.mark.asyncio
    async def test_execute_timeout(self, sandbox):
        stdout, stderr, code = await sandbox.execute("python -c \"import time; time.sleep(30)\"", timeout=1)
        assert code != 0
        assert "超时" in stderr or "timeout" in stderr.lower()

    @pytest.mark.asyncio
    async def test_execute_python_safe(self, sandbox):
        code_text = "print('hello from sandbox')"
        stdout, stderr, code = await sandbox.execute_python(code_text, timeout=10)
        assert code == 0
        assert "hello from sandbox" in stdout

    @pytest.mark.asyncio
    async def test_execute_python_dangerous_blocked(self, sandbox):
        code_text = "import os\nos.system('echo hacked')"
        stdout, stderr, code = await sandbox.execute_python(code_text, timeout=10)
        assert code == -1
        assert "安全检查未通过" in stderr

    @pytest.mark.asyncio
    async def test_execute_python_timeout(self, sandbox):
        code_text = "import time\ntime.sleep(30)"
        stdout, stderr, code = await sandbox.execute_python(code_text, timeout=1)
        assert code == -1
        assert "超时" in stderr

    @pytest.mark.asyncio
    async def test_execute_python_math(self, sandbox):
        code_text = "import math\nprint(math.factorial(5))"
        stdout, stderr, code = await sandbox.execute_python(code_text, timeout=10)
        assert code == 0
        assert "120" in stdout

    @pytest.mark.asyncio
    async def test_validate_code_method(self, sandbox):
        is_safe, warnings = sandbox.validate_code("print('safe')")
        assert is_safe
        is_safe, warnings = sandbox.validate_code("import os; os.system('ls')")
        assert not is_safe