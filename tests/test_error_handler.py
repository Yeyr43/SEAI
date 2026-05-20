"""
SmartErrorHandler 单元测试
"""
import pytest
import tempfile
from pathlib import Path
from seai.core.error_handler import SmartErrorHandler, ErrorDiagnosis, ErrorPattern


class TestSmartErrorHandler:
    """智能错误处理器单元测试"""

    @pytest.fixture
    def handler(self, tmp_path):
        return SmartErrorHandler(tmp_path)

    def test_initialization(self, handler):
        assert handler is not None
        assert len(handler.error_patterns) > 0
        assert isinstance(handler.error_stats, dict)
        assert isinstance(handler.recent_errors, list)

    def test_handle_known_error(self, handler):
        try:
            open("/nonexistent/path/file.txt")
        except FileNotFoundError as e:
            diagnosis = handler.handle_error(e, {"operation": "read_file"})

        assert isinstance(diagnosis, ErrorDiagnosis)
        assert diagnosis.error_type == "file_not_found"
        assert diagnosis.severity in ("critical", "high", "medium", "low")
        assert len(diagnosis.prevention_suggestions) > 0

    def test_handle_unknown_error(self, handler):
        try:
            raise RuntimeError("some completely unknown error pattern xyz123")
        except RuntimeError as e:
            diagnosis = handler.handle_error(e, {})

        assert isinstance(diagnosis, ErrorDiagnosis)
        assert diagnosis.error_type == "unknown"
        assert diagnosis.severity == "medium"

    def test_error_recording(self, handler):
        try:
            raise ValueError("test value error")
        except ValueError as e:
            handler.handle_error(e, {"test": True})

        assert len(handler.recent_errors) > 0
        assert handler.recent_errors[-1]["error_type"] == "ValueError"
        assert handler.recent_errors[-1]["context"]["test"] is True

    def test_error_stats_accumulation(self, handler):
        for _ in range(3):
            try:
                raise ValueError("test")
            except ValueError as e:
                handler.handle_error(e, {})

        assert handler.error_stats.get("ValueError", 0) == 3

    def test_recent_errors_limit(self, handler):
        for i in range(150):
            try:
                raise ValueError(f"error {i}")
            except ValueError as e:
                handler.handle_error(e, {})

        assert len(handler.recent_errors) <= 100

    def test_pattern_learning(self, handler):
        unique_msg = "unique_pattern_xyz_abc_123_test"
        try:
            raise RuntimeError(unique_msg)
        except RuntimeError as e:
            diagnosis = handler.handle_error(e, {})

        assert diagnosis.error_type == "unknown"
        learned = any(p.pattern and unique_msg[:50] in p.pattern for p in handler.error_patterns)
        assert learned

    def test_severity_determination(self, handler):
        try:
            raise MemoryError("out of memory")
        except MemoryError as e:
            diagnosis = handler.handle_error(e, {})
        assert diagnosis.severity == "critical"

    def test_context_preservation(self, handler):
        context = {"user_id": "123", "session": "abc", "query": "test query"}
        try:
            raise KeyError("missing_key")
        except KeyError as e:
            handler.handle_error(e, context)

        assert handler.recent_errors[-1]["context"] == context

    def test_error_pattern_file_persistence(self, tmp_path):
        handler1 = SmartErrorHandler(tmp_path)
        initial_count = len(handler1.error_patterns)

        handler2 = SmartErrorHandler(tmp_path)
        assert len(handler2.error_patterns) >= initial_count
