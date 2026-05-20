"""
智能错误处理模块
自动诊断错误、提供修复建议、学习错误模式
集成统一错误协议 (SEAIError) 和事件总线
"""
import re
import json
import traceback
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from loguru import logger


@dataclass
class ErrorDiagnosis:
    """错误诊断结果"""
    error_type: str
    severity: str  # low, medium, high, critical
    probable_cause: str
    immediate_fix: str
    prevention_suggestions: List[str]
    related_errors: List[str]


@dataclass
class ErrorPattern:
    """错误模式"""
    pattern: str
    error_type: str
    fix_suggestion: str
    occurrence_count: int
    last_occurrence: datetime


DEFAULT_ERROR_PATTERNS = [
    {
        'pattern': r'FileNotFoundError.*No such file or directory',
        'error_type': 'file_not_found',
        'fix_suggestion': '检查文件路径是否正确，确保文件存在',
        'occurrence_count': 0,
    },
    {
        'pattern': r'PermissionError.*Permission denied',
        'error_type': 'permission_denied',
        'fix_suggestion': '检查文件/目录权限，确保有读写权限',
        'occurrence_count': 0,
    },
    {
        'pattern': r'ConnectionError.*Connection refused',
        'error_type': 'connection_refused',
        'fix_suggestion': '检查网络连接和目标服务状态',
        'occurrence_count': 0,
    },
    {
        'pattern': r'TimeoutError.*timed out',
        'error_type': 'timeout',
        'fix_suggestion': '增加超时时间或检查网络状况',
        'occurrence_count': 0,
    },
    {
        'pattern': r'MemoryError.*out of memory',
        'error_type': 'out_of_memory',
        'fix_suggestion': '优化内存使用或增加系统内存',
        'occurrence_count': 0,
    },
    {
        'pattern': r'KeyError.*not found',
        'error_type': 'key_error',
        'fix_suggestion': '检查字典键是否存在，添加默认值处理',
        'occurrence_count': 0,
    },
    {
        'pattern': r'ValueError.*invalid literal',
        'error_type': 'value_error',
        'fix_suggestion': '检查输入数据格式和类型',
        'occurrence_count': 0,
    },
    {
        'pattern': r'ModuleNotFoundError.*No module named',
        'error_type': 'module_not_found',
        'fix_suggestion': '安装缺失的依赖包：pip install <package>',
        'occurrence_count': 0,
    },
    {
        'pattern': r'AttributeError.*object has no attribute',
        'error_type': 'attribute_error',
        'fix_suggestion': '检查对象属性和方法是否存在',
        'occurrence_count': 0,
    },
    {
        'pattern': r'JSONDecodeError.*Expecting value',
        'error_type': 'json_decode_error',
        'fix_suggestion': '检查JSON格式是否正确，修复语法错误',
        'occurrence_count': 0,
    },
]


class SmartErrorHandler:
    """智能错误处理器"""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.errors_dir = data_dir / "errors"
        self.errors_dir.mkdir(exist_ok=True)
        
        # 错误模式库
        self.error_patterns: List[ErrorPattern] = []
        self._load_error_patterns()
        
        # 错误统计
        self.error_stats: Dict[str, int] = {}
        self.recent_errors: List[Dict] = []
        
        # 预定义错误模式
        self._initialize_default_patterns()

    def _initialize_default_patterns(self):
        """初始化默认错误模式（使用模块级常量避免重复）"""
        for pattern_data in DEFAULT_ERROR_PATTERNS:
            self.error_patterns.append(ErrorPattern(
                pattern=pattern_data['pattern'],
                error_type=pattern_data['error_type'],
                fix_suggestion=pattern_data['fix_suggestion'],
                occurrence_count=pattern_data['occurrence_count'],
                last_occurrence=datetime.now()
            ))
    
    def _load_error_patterns(self):
        """加载错误模式"""
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
                print(f"加载错误模式失败: {e}")
    
    def _save_error_patterns(self):
        """保存错误模式"""
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
        """处理错误并返回诊断结果"""
        error_message = str(error)
        error_traceback = traceback.format_exc()
        
        # 记录错误
        self._record_error(error, error_traceback, context)
        
        # 诊断错误
        diagnosis = self._diagnose_error(error_message, error_traceback, context)
        
        # 学习错误模式
        self._learn_from_error(error_message, diagnosis)
        
        return diagnosis
    
    def _record_error(self, error: Exception, traceback_str: str, context: Dict[str, Any]):
        """记录错误信息"""
        error_record = {
            'timestamp': datetime.now().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback_str,
            'context': context or {},
            'resolved': False
        }
        
        self.recent_errors.append(error_record)
        
        # 限制最近错误数量
        if len(self.recent_errors) > 100:
            self.recent_errors = self.recent_errors[-100:]
        
        # 更新错误统计
        error_type = type(error).__name__
        self.error_stats[error_type] = self.error_stats.get(error_type, 0) + 1
        
        # 保存到文件
        self._save_error_log(error_record)
    
    def _save_error_log(self, error_record: Dict):
        """保存错误日志"""
        error_log_file = self.errors_dir / "error_log.jsonl"
        
        with open(error_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(error_record, ensure_ascii=False) + '\n')
    
    def _diagnose_error(self, error_message: str, traceback_str: str, context: Dict[str, Any]) -> ErrorDiagnosis:
        """诊断错误"""
        # 匹配已知错误模式
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
        """根据模式创建诊断"""
        # 更新模式出现次数
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
        """创建通用诊断"""
        return ErrorDiagnosis(
            error_type='unknown',
            severity='medium',
            probable_cause='未知错误类型，需要进一步分析',
            immediate_fix='检查日志文件获取详细信息',
            prevention_suggestions=[
                '增加错误日志记录',
                '完善输入验证',
                '添加异常处理代码'
            ],
            related_errors=[]
        )
    
    def _determine_severity(self, error_type: str, context: Dict[str, Any]) -> str:
        """确定错误严重性"""
        critical_errors = {'out_of_memory', 'connection_refused', 'permission_denied'}
        high_errors = {'file_not_found', 'timeout', 'module_not_found'}
        
        if error_type in critical_errors:
            return 'critical'
        elif error_type in high_errors:
            return 'high'
        else:
            return 'medium'
    
    def _get_probable_cause(self, error_type: str, context: Dict[str, Any]) -> str:
        """获取可能的原因"""
        causes = {
            'file_not_found': '文件路径错误或文件不存在',
            'permission_denied': '权限配置问题',
            'connection_refused': '网络连接或服务状态问题',
            'timeout': '网络延迟或服务响应慢',
            'out_of_memory': '内存资源不足',
            'key_error': '数据键不存在',
            'value_error': '数据格式错误',
            'module_not_found': '依赖包未安装',
            'attribute_error': '对象属性错误',
            'json_decode_error': 'JSON格式错误'
        }
        
        return causes.get(error_type, '未知原因')
    
    def _get_prevention_suggestions(self, error_type: str) -> List[str]:
        """获取预防建议"""
        suggestions = {
            'file_not_found': ['添加文件存在性检查', '使用相对路径替代绝对路径'],
            'permission_denied': ['检查文件权限设置', '使用适当的用户权限运行'],
            'connection_refused': ['添加连接重试机制', '实现服务健康检查'],
            'timeout': ['增加超时时间设置', '实现异步处理'],
            'out_of_memory': ['优化内存使用', '实现数据分页处理'],
            'key_error': ['添加键存在性检查', '使用get方法替代直接访问'],
            'value_error': ['加强输入验证', '添加数据类型转换'],
            'module_not_found': ['完善依赖管理', '添加包安装检查'],
            'attribute_error': ['添加属性存在性检查', '使用hasattr方法'],
            'json_decode_error': ['添加JSON格式验证', '使用try-catch处理解析错误']
        }
        
        return suggestions.get(error_type, ['增加错误处理代码', '完善输入验证'])
    
    def _get_related_errors(self, error_type: str) -> List[str]:
        """获取相关错误"""
        related = {
            'file_not_found': ['permission_denied'],
            'permission_denied': ['file_not_found'],
            'connection_refused': ['timeout'],
            'timeout': ['connection_refused']
        }
        
        return related.get(error_type, [])
    
    def _learn_from_error(self, error_message: str, diagnosis: ErrorDiagnosis):
        """从错误中学习"""
        # 如果错误类型未知，尝试学习新模式
        if diagnosis.error_type == 'unknown':
            # 提取错误特征
            features = self._extract_error_features(error_message)
            
            # 创建新错误模式
            new_pattern = ErrorPattern(
                pattern=features.get('pattern', error_message[:100]),
                error_type=f'learned_{len(self.error_patterns)}',
                fix_suggestion=diagnosis.immediate_fix,
                occurrence_count=1,
                last_occurrence=datetime.now()
            )
            
            self.error_patterns.append(new_pattern)
        
        # 保存更新后的模式库
        self._save_error_patterns()
    
    def handle_seai_error(self, error) -> ErrorDiagnosis:
        from .seai_error import SEAIError
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
            "llm": "检查 LLM 服务连接和 API Key 配置",
            "tool": "检查工具参数和可用性",
            "memory": "检查记忆存储路径和权限",
            "skill": "检查技能定义和依赖",
            "network": "检查网络连接和防火墙设置",
            "file_system": "检查文件路径和权限",
            "constraint": "检查操作是否在允许边界内",
            "agent": "检查 Agent 配置和状态",
            "config": "检查配置文件格式和路径",
            "internal": "查看详细日志定位内部错误",
        }
        return fixes.get(category, "检查日志文件获取详细信息")

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
        """提取错误特征"""
        features = {}
        
        # 提取文件路径
        file_pattern = r'File "([^"]+)"'
        file_match = re.search(file_pattern, error_message)
        if file_match:
            features['file_path'] = file_match.group(1)
        
        # 提取行号
        line_pattern = r'line (\d+)'
        line_match = re.search(line_pattern, error_message)
        if line_match:
            features['line_number'] = line_match.group(1)
        
        # 创建简单模式
        words = error_message.split()
        if len(words) > 3:
            features['pattern'] = ' '.join(words[:3]) + '.*'
        
        return features
    
    def get_error_stats(self) -> Dict[str, Any]:
        """获取错误统计"""
        return {
            'total_errors': sum(self.error_stats.values()),
            'error_types': self.error_stats,
            'recent_errors_count': len(self.recent_errors),
            'most_common_error': max(self.error_stats.items(), key=lambda x: x[1], default=('none', 0))
        }
    
    def get_error_trend(self, days: int = 7) -> Dict[str, int]:
        """获取错误趋势"""
        trend = {}
        today = datetime.now().date()
        
        for i in range(days):
            date_key = (today - timedelta(days=i)).isoformat()
            trend[date_key] = 0
        
        # 这里需要从错误日志文件中统计
        # 简化实现：返回模拟数据
        return trend


# 全局错误处理器实例
error_handler: SmartErrorHandler = None

