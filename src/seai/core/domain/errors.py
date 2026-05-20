"""
SEAI Unified Error Protocol - Base classes for all module errors.

Provides error codes, severity levels, recoverability flags, and contextual data.
Also includes SmartErrorHandler for automatic error diagnosis and pattern learning.
"""
import re
import json
import traceback
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import time
import uuid

from loguru import logger


# ══════════════════════════════════════════════════
# Error Enums
# ══════════════════════════════════════════════════

class ErrorSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ErrorCategory(str, Enum):
    LLM = "llm"
    TOOL = "tool"
    MEMORY = "memory"
    SKILL = "skill"
    NETWORK = "network"
    FILE_SYSTEM = "file_system"
    CONSTRAINT = "constraint"
    AGENT = "agent"
    CONFIG = "config"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


# ══════════════════════════════════════════════════
# Base Error Classes
# ══════════════════════════════════════════════════

@dataclass
class SEAIError(Exception):
    message: str
    category: ErrorCategory = ErrorCategory.UNKNOWN
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    code: str = "SEAI-0000"
    recoverable: bool = True
    context: Dict[str, Any] = field(default_factory=dict)
    cause: Optional[Exception] = None
    error_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error_id": self.error_id,
            "code": self.code,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "recoverable": self.recoverable,
            "context": self.context,
            "cause": str(self.cause) if self.cause else None,
            "timestamp": self.timestamp,
        }


class LLMError(SEAIError):
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.LLM,
            code=kwargs.pop("code", "SEAI-1001"),
            **kwargs,
        )


class ToolError(SEAIError):
    def __init__(self, message: str, tool_name: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.TOOL,
            code=kwargs.pop("code", "SEAI-2001"),
            context={"tool_name": tool_name, **kwargs.pop("context", {})},
            **kwargs,
        )


class ConstraintError(SEAIError):
    def __init__(self, message: str, boundary_type: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.CONSTRAINT,
            code=kwargs.pop("code", "SEAI-3001"),
            severity=ErrorSeverity.HIGH,
            context={"boundary_type": boundary_type, **kwargs.pop("context", {})},
            **kwargs,
        )


class AgentError(SEAIError):
    def __init__(self, message: str, agent_id: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.AGENT,
            code=kwargs.pop("code", "SEAI-4001"),
            context={"agent_id": agent_id, **kwargs.pop("context", {})},
            **kwargs,
        )


class ConfigError(SEAIError):
    def __init__(self, message: str, config_key: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIG,
            code=kwargs.pop("code", "SEAI-5001"),
            severity=ErrorSeverity.CRITICAL,
            recoverable=False,
            context={"config_key": config_key, **kwargs.pop("context", {})},
            **kwargs,
        )


# ══════════════════════════════════════════════════
# Error Diagnosis & Smart Handler
# ══════════════════════════════════════════════════

@dataclass
class ErrorDiagnosis:
    """Error diagnosis result"""
    error_type: str
    severity: str  # low, medium, high, critical
    probable_cause: str
    immediate_fix: str
    prevention_suggestions: List[str]
    related_errors: List[str]


@dataclass
class ErrorPattern:
    """Error pattern"""
    pattern: str
    error_type: str
    fix_suggestion: str
    occurrence_count: int
    last_occurrence: datetime


DEFAULT_ERROR_PATTERNS = [
    {
        'pattern': r'FileNotFoundError.*No such file or directory',
        'error_type': 'file_not_found',
        'fix_suggestion': 'Check the file path is correct and the file exists',
        'occurrence_count': 0,
    },
    {
        'pattern': r'PermissionError.*Permission denied',
        'error_type': 'permission_denied',
        'fix_suggestion': 'Check file/directory permissions',
        'occurrence_count': 0,
    },
    {
        'pattern': r'ConnectionError.*Connection refused',
        'error_type': 'connection_refused',
        'fix_suggestion': 'Check network connection and target service status',
        'occurrence_count': 0,
    },
    {
        'pattern': r'TimeoutError.*timed out',
        'error_type': 'timeout',
        'fix_suggestion': 'Increase timeout or check network conditions',
        'occurrence_count': 0,
    },
    {
        'pattern': r'MemoryError.*out of memory',
        'error_type': 'out_of_memory',
        'fix_suggestion': 'Optimize memory usage or add system memory',
        'occurrence_count': 0,
    },
    {
        'pattern': r'KeyError.*not found',
        'error_type': 'key_error',
        'fix_suggestion': 'Check dict key exists, add default handling',
        'occurrence_count': 0,
    },
    {
        'pattern': r'ValueError.*invalid literal',
        'error_type': 'value_error',
        'fix_suggestion': 'Check input data format and type',
        'occurrence_count': 0,
    },
    {
        'pattern': r'ModuleNotFoundError.*No module named',
        'error_type': 'module_not_found',
        'fix_suggestion': 'Install missing dependency: pip install <package>',
        'occurrence_count': 0,
    },
    {
        'pattern': r'AttributeError.*object has no attribute',
        'error_type': 'attribute_error',
        'fix_suggestion': 'Check object attributes and methods exist',
        'occurrence_count': 0,
    },
    {
        'pattern': r'JSONDecodeError.*Expecting value',
        'error_type': 'json_decode_error',
        'fix_suggestion': 'Check JSON format is correct, fix syntax errors',
        'occurrence_count': 0,
    },
]


class SmartErrorHandler:
    """Intelligent error handler with pattern matching, diagnosis, and auto-learning"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.errors_dir = data_dir / "errors"
        self.errors_dir.mkdir(exist_ok=True)

        self.error_patterns: List[ErrorPattern] = []
        self._load_error_patterns()

        self.error_stats: Dict[str, int] = {}
        self.recent_errors: List[Dict] = []

        self._initialize_default_patterns()

    def _initialize_default_patterns(self):
        """Initialize default error patterns using module-level constants to avoid duplication"""
        for pattern_data in DEFAULT_ERROR_PATTERNS:
            self.error_patterns.append(ErrorPattern(
                pattern=pattern_data['pattern'],
                error_type=pattern_data['error_type'],
                fix_suggestion=pattern_data['fix_suggestion'],
                occurrence_count=pattern_data['occurrence_count'],
                last_occurrence=datetime.now()
            ))

    def _load_error_patterns(self):
        """Load error patterns from disk"""
        patterns_file = self.errors_dir / "error_patterns.json"
        if patterns_file.exists():
            try:
                with open(patterns_file, 'r', encoding='utf-8') as f:
                    patterns_data = json.load(f)

                for pattern_data in patterns_data:
                    self.error_patterns.append(ErrorPattern(
                        pattern=pattern_data['pattern'],
                        error_type=pattern_data['error_type'],
                        fix_suggestion=pattern_data['fix_suggestion'],
                        occurrence_count=pattern_data['occurrence_count'],
                        last_occurrence=datetime.fromisoformat(pattern_data['last_occurrence'])
                    ))
            except Exception as e:
                print(f"Failed to load error patterns: {e}")

    def _save_error_patterns(self):
        """Save error patterns to disk"""
        patterns_file = self.errors_dir / "error_patterns.json"
        patterns_data = [
            {
                'pattern': pattern.pattern,
                'error_type': pattern.error_type,
                'fix_suggestion': pattern.fix_suggestion,
                'occurrence_count': pattern.occurrence_count,
                'last_occurrence': pattern.last_occurrence.isoformat()
            }
            for pattern in self.error_patterns
        ]

        patterns_file.write_text(json.dumps(patterns_data, indent=2, ensure_ascii=False), encoding='utf-8')

    def handle_error(self, error: Exception, context: Dict[str, Any] = None) -> ErrorDiagnosis:
        """Handle an error and return a diagnosis result"""
        error_message = str(error)
        error_traceback = traceback.format_exc()

        self._record_error(error, error_traceback, context)
        diagnosis = self._diagnose_error(error_message, error_traceback, context)
        self._learn_from_error(error_message, diagnosis)

        return diagnosis

    def _record_error(self, error: Exception, traceback_str: str, context: Dict[str, Any]):
        """Record error information"""
        error_record = {
            'timestamp': datetime.now().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback_str,
            'context': context or {},
            'resolved': False
        }

        self.recent_errors.append(error_record)

        if len(self.recent_errors) > 100:
            self.recent_errors = self.recent_errors[-100:]

        error_type = type(error).__name__
        self.error_stats[error_type] = self.error_stats.get(error_type, 0) + 1

        self._save_error_log(error_record)

    def _save_error_log(self, error_record: Dict):
        """Save error log to file"""
        error_log_file = self.errors_dir / "error_log.jsonl"

        with open(error_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(error_record, ensure_ascii=False) + '\n')

    def _diagnose_error(self, error_message: str, traceback_str: str, context: Dict[str, Any]) -> ErrorDiagnosis:
        """Diagnose an error by matching against known patterns"""
        matched_pattern = None
        for pattern in self.error_patterns:
            if re.search(pattern.pattern, error_message) or re.search(pattern.pattern, traceback_str):
                matched_pattern = pattern
                break

        if matched_pattern:
            return self._create_diagnosis_from_pattern(matched_pattern, context)
        else:
            return self._create_generic_diagnosis(error_message, context)

    def _create_diagnosis_from_pattern(self, pattern: ErrorPattern, context: Dict[str, Any]) -> ErrorDiagnosis:
        """Create diagnosis from a matched pattern"""
        pattern.occurrence_count += 1
        pattern.last_occurrence = datetime.now()

        severity = self._determine_severity(pattern.error_type, context)

        return ErrorDiagnosis(
            error_type=pattern.error_type,
            severity=severity,
            probable_cause=self._get_probable_cause(pattern.error_type, context),
            immediate_fix=pattern.fix_suggestion,
            prevention_suggestions=self._get_prevention_suggestions(pattern.error_type),
            related_errors=self._get_related_errors(pattern.error_type)
        )

    def _create_generic_diagnosis(self, error_message: str, context: Dict[str, Any]) -> ErrorDiagnosis:
        """Create a generic diagnosis for unknown errors"""
        return ErrorDiagnosis(
            error_type='unknown',
            severity='medium',
            probable_cause='Unknown error type, further analysis needed',
            immediate_fix='Check log files for details',
            prevention_suggestions=[
                'Add error logging',
                'Improve input validation',
                'Add exception handling code'
            ],
            related_errors=[]
        )

    def _determine_severity(self, error_type: str, context: Dict[str, Any]) -> str:
        """Determine error severity"""
        critical_errors = {'out_of_memory', 'connection_refused', 'permission_denied'}
        high_errors = {'file_not_found', 'timeout', 'module_not_found'}

        if error_type in critical_errors:
            return 'critical'
        elif error_type in high_errors:
            return 'high'
        else:
            return 'medium'

    def _get_probable_cause(self, error_type: str, context: Dict[str, Any]) -> str:
        """Get the likely cause for an error type"""
        causes = {
            'file_not_found': 'File path error or file does not exist',
            'permission_denied': 'Permission configuration issue',
            'connection_refused': 'Network connection or service status issue',
            'timeout': 'Network latency or slow service response',
            'out_of_memory': 'Insufficient memory resources',
            'key_error': 'Data key does not exist',
            'value_error': 'Data format error',
            'module_not_found': 'Dependency package not installed',
            'attribute_error': 'Object attribute error',
            'json_decode_error': 'JSON format error'
        }

        return causes.get(error_type, 'Unknown cause')

    def _get_prevention_suggestions(self, error_type: str) -> List[str]:
        """Get prevention suggestions for an error type"""
        suggestions = {
            'file_not_found': ['Add file existence check', 'Use relative paths over absolute'],
            'permission_denied': ['Check file permission settings', 'Run with appropriate user permissions'],
            'connection_refused': ['Add connection retry mechanism', 'Implement service health check'],
            'timeout': ['Increase timeout setting', 'Implement async processing'],
            'out_of_memory': ['Optimize memory usage', 'Implement data pagination'],
            'key_error': ['Add key existence check', 'Use get() method instead of direct access'],
            'value_error': ['Strengthen input validation', 'Add data type conversion'],
            'module_not_found': ['Improve dependency management', 'Add package installation check'],
            'attribute_error': ['Add attribute existence check', 'Use hasattr() method'],
            'json_decode_error': ['Add JSON format validation', 'Use try-catch for parse errors']
        }

        return suggestions.get(error_type, ['Add error handling code', 'Improve input validation'])

    def _get_related_errors(self, error_type: str) -> List[str]:
        """Get related error types"""
        related = {
            'file_not_found': ['permission_denied'],
            'permission_denied': ['file_not_found'],
            'connection_refused': ['timeout'],
            'timeout': ['connection_refused']
        }

        return related.get(error_type, [])

    def _learn_from_error(self, error_message: str, diagnosis: ErrorDiagnosis):
        """Learn from errors - create new patterns for unknown error types"""
        if diagnosis.error_type == 'unknown':
            features = self._extract_error_features(error_message)

            new_pattern = ErrorPattern(
                pattern=features.get('pattern', error_message[:100]),
                error_type=f'learned_{len(self.error_patterns)}',
                fix_suggestion=diagnosis.immediate_fix,
                occurrence_count=1,
                last_occurrence=datetime.now()
            )

            self.error_patterns.append(new_pattern)

        self._save_error_patterns()

    def handle_seai_error(self, error) -> ErrorDiagnosis:
        """Handle a SEAIError by using its built-in category and severity"""
        if isinstance(error, SEAIError):
            return ErrorDiagnosis(
                error_type=error.category.value,
                severity=error.severity.value,
                probable_cause=error.message,
                immediate_fix=self._get_fix_for_category(error.category.value),
                prevention_suggestions=self._get_prevention_suggestions(error.category.value),
                related_errors=[],
            )
        return self.handle_error(error)

    def _get_fix_for_category(self, category: str) -> str:
        fixes = {
            "llm": "Check LLM service connection and API key configuration",
            "tool": "Check tool parameters and availability",
            "memory": "Check memory storage path and permissions",
            "skill": "Check skill definition and dependencies",
            "network": "Check network connection and firewall settings",
            "file_system": "Check file path and permissions",
            "constraint": "Check if operation is within allowed boundaries",
            "agent": "Check agent configuration and status",
            "config": "Check configuration file format and path",
            "internal": "Check detailed logs to locate internal error",
        }
        return fixes.get(category, "Check log files for details")

    def get_error_summary(self) -> dict:
        return {
            "total_errors": sum(self.error_stats.values()),
            "error_stats": self.error_stats,
            "recent_errors_count": len(self.recent_errors),
            "pattern_count": len(self.error_patterns),
            "recent_critical": len([
                e for e in self.recent_errors[-20:]
                if e.get("severity") in ("high", "critical")
            ]),
        }

    def _extract_error_features(self, error_message: str) -> Dict[str, str]:
        """Extract error features for pattern learning"""
        features = {}

        file_pattern = r'File "([^"]+)"'
        file_match = re.search(file_pattern, error_message)
        if file_match:
            features['file_path'] = file_match.group(1)

        line_pattern = r'line (\d+)'
        line_match = re.search(line_pattern, error_message)
        if line_match:
            features['line_number'] = line_match.group(1)

        words = error_message.split()
        if len(words) > 3:
            features['pattern'] = ' '.join(words[:3]) + '.*'

        return features

    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics"""
        return {
            'total_errors': sum(self.error_stats.values()),
            'error_types': self.error_stats,
            'recent_errors_count': len(self.recent_errors),
            'most_common_error': max(self.error_stats.items(), key=lambda x: x[1], default=('none', 0))
        }

    def get_error_trend(self, days: int = 7) -> Dict[str, int]:
        """Get error trend data"""
        trend = {}
        today = datetime.now().date()

        for i in range(days):
            date_key = (today - timedelta(days=i)).isoformat()
            trend[date_key] = 0

        return trend


# Global error handler instance
error_handler: SmartErrorHandler = None
