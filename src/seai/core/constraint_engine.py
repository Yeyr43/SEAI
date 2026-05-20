"""
SEAI Harness 工程 - 行为边界约束引擎
支持文件操作边界、网络访问边界、计算资源边界、策略热更新
Provider 模式支持动态注册自定义约束规则
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from copy import deepcopy
from loguru import logger


class BoundaryType(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    NETWORK_DOMAIN = "network_domain"
    NETWORK_PORT = "network_port"
    COMPUTE_TIME = "compute_time"
    COMPUTE_MEMORY = "compute_memory"
    SUB_AGENT_COUNT = "sub_agent_count"
    TOKEN_BUDGET = "token_budget"


@dataclass
class BoundaryRule:
    boundary_type: BoundaryType
    allowed: List[str] = field(default_factory=list)
    blocked: List[str] = field(default_factory=list)
    max_value: Optional[float] = None
    max_depth: int = 10
    enabled: bool = True
    description: str = ""


@dataclass
class ConstraintCheck:
    passed: bool
    boundary_type: BoundaryType
    value: str
    message: str = ""
    timestamp: float = 0.0


class ConstraintEngine:
    """行为边界约束引擎 - 实施 Harness 工程中的约束条件层"""

    DEFAULT_RULES = {
        BoundaryType.FILE_READ: BoundaryRule(
            boundary_type=BoundaryType.FILE_READ,
            allowed=["src/", "tests/", "data/", "prompts/", "skills/", "data/"],
            blocked=[".env", ".git/", "*.key", "*.pem", "*.pfx", "credentials.*", "secrets.*"],
            max_depth=15,
            description="文件读取边界",
        ),
        BoundaryType.FILE_WRITE: BoundaryRule(
            boundary_type=BoundaryType.FILE_WRITE,
            allowed=["src/", "tests/", "data/", "output/", "data/"],
            blocked=[".env", "*.key", "*.pem", "*.pfx", "config.json", "*.exe", "*.dll"],
            max_depth=10,
            description="文件写入边界",
        ),
        BoundaryType.FILE_DELETE: BoundaryRule(
            boundary_type=BoundaryType.FILE_DELETE,
            allowed=["output/", "temp/", "data/evo/"],
            blocked=["*"],
            description="文件删除边界",
        ),
        BoundaryType.NETWORK_DOMAIN: BoundaryRule(
            boundary_type=BoundaryType.NETWORK_DOMAIN,
            allowed=["api.github.com", "pypi.org", "docs.python.org", "*.readthedocs.io"],
            blocked=["localhost", "127.0.0.1", "0.0.0.0", "internal.*"],
            description="网络访问域名边界",
        ),
        BoundaryType.NETWORK_PORT: BoundaryRule(
            boundary_type=BoundaryType.NETWORK_PORT,
            allowed=["443", "80", "8080", "3000", "5000", "8000"],
            blocked=["22", "23", "25", "110", "143", "3306", "5432", "6379", "27017"],
            description="网络端口边界",
        ),
        BoundaryType.COMPUTE_TIME: BoundaryRule(
            boundary_type=BoundaryType.COMPUTE_TIME,
            max_value=300.0,
            description="计算超时限制(秒)",
        ),
        BoundaryType.COMPUTE_MEMORY: BoundaryRule(
            boundary_type=BoundaryType.COMPUTE_MEMORY,
            max_value=512.0,
            description="内存限制(MB)",
        ),
        BoundaryType.SUB_AGENT_COUNT: BoundaryRule(
            boundary_type=BoundaryType.SUB_AGENT_COUNT,
            max_value=3,
            description="最大子 Agent 数",
        ),
        BoundaryType.TOKEN_BUDGET: BoundaryRule(
            boundary_type=BoundaryType.TOKEN_BUDGET,
            max_value=3000,
            description="单子 Agent Token 预算",
        ),
    }

    def __init__(self, config_path: Path = None):
        self._rules: Dict[BoundaryType, BoundaryRule] = {}
        for bt, rule in self.DEFAULT_RULES.items():
            self._rules[bt] = BoundaryRule(
                boundary_type=rule.boundary_type,
                allowed=list(rule.allowed),
                blocked=list(rule.blocked),
                max_value=rule.max_value,
                max_depth=rule.max_depth,
                enabled=rule.enabled,
                description=rule.description,
            )
        self._violations: List[ConstraintCheck] = []
        self._config_path = config_path
        self._providers: Dict[str, Callable] = {}
        self._load_custom_rules()

    def register_provider(self, name: str, provider: Callable):
        self._providers[name] = provider
        logger.info(f"注册约束提供者: {name}")

    def unregister_provider(self, name: str):
        self._providers.pop(name, None)

    def check_query(self, query: str) -> ConstraintCheck:
        for name, provider in self._providers.items():
            try:
                result = provider(query)
                if isinstance(result, ConstraintCheck) and not result.passed:
                    return result
            except Exception as e:
                logger.warning(f"约束提供者 {name} 执行异常: {e}")
        return ConstraintCheck(passed=True, boundary_type=BoundaryType.FILE_READ, value=query)

    def _load_custom_rules(self):
        if self._config_path and self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    custom = json.load(f)
                for key, value in custom.items():
                    try:
                        bt = BoundaryType(key)
                        if bt in self._rules:
                            rule = self._rules[bt]
                            if "allowed" in value:
                                rule.allowed = value["allowed"]
                            if "blocked" in value:
                                rule.blocked = value["blocked"]
                            if "max_value" in value:
                                rule.max_value = value["max_value"]
                            if "enabled" in value:
                                rule.enabled = value["enabled"]
                            if "description" in value:
                                rule.description = value["description"]
                    except ValueError:
                        logger.warning(f"未知的边界类型: {key}")
                logger.info(f"已加载 {len(custom)} 条自定义约束规则")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"加载约束规则文件失败: {e}")

    def save_rules(self):
        if self._config_path:
            data = {}
            for bt, rule in self._rules.items():
                data[bt.value] = {
                    "allowed": rule.allowed,
                    "blocked": rule.blocked,
                    "max_value": rule.max_value,
                    "enabled": rule.enabled,
                    "description": rule.description,
                }
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def check_file_access(self, path: str, operation: str = "read") -> ConstraintCheck:
        boundary_type = {
            "read": BoundaryType.FILE_READ,
            "write": BoundaryType.FILE_WRITE,
            "delete": BoundaryType.FILE_DELETE,
        }.get(operation, BoundaryType.FILE_READ)

        rule = self._rules.get(boundary_type)
        if not rule or not rule.enabled:
            return ConstraintCheck(passed=True, boundary_type=boundary_type, value=path)

        normalized = str(Path(path)).replace("\\", "/")

        for blocked_pattern in rule.blocked:
            if self._match_pattern(normalized, blocked_pattern):
                is_explicitly_allowed = any(
                    self._match_prefix(normalized, ap) for ap in rule.allowed
                ) if rule.allowed else False
                if not is_explicitly_allowed:
                    check = ConstraintCheck(
                        passed=False,
                        boundary_type=boundary_type,
                        value=path,
                        message=f"路径被阻止: {blocked_pattern}",
                        timestamp=time.time(),
                    )
                    self._violations.append(check)
                    return check

        if not rule.allowed:
            check = ConstraintCheck(
                passed=False,
                boundary_type=boundary_type,
                value=path,
                message="无允许的路径规则",
                timestamp=time.time(),
            )
            self._violations.append(check)
            return check

        depth = len(Path(normalized).parts)
        if depth > rule.max_depth:
            check = ConstraintCheck(
                passed=False,
                boundary_type=boundary_type,
                value=path,
                message=f"路径深度 {depth} 超过限制 {rule.max_depth}",
                timestamp=time.time(),
            )
            self._violations.append(check)
            return check

        for allowed_pattern in rule.allowed:
            if self._match_prefix(normalized, allowed_pattern):
                return ConstraintCheck(passed=True, boundary_type=boundary_type, value=path)

        check = ConstraintCheck(
            passed=False,
            boundary_type=boundary_type,
            value=path,
            message=f"路径不在允许列表中",
            timestamp=time.time(),
        )
        self._violations.append(check)
        return check

    def check_network_access(self, host: str, port: int = 443) -> ConstraintCheck:
        domain_rule = self._rules.get(BoundaryType.NETWORK_DOMAIN)
        if domain_rule and domain_rule.enabled:
            for blocked_pattern in domain_rule.blocked:
                if self._match_pattern(host, blocked_pattern):
                    check = ConstraintCheck(
                        passed=False,
                        boundary_type=BoundaryType.NETWORK_DOMAIN,
                        value=f"{host}:{port}",
                        message=f"域名被阻止: {blocked_pattern}",
                        timestamp=time.time(),
                    )
                    self._violations.append(check)
                    return check

            for allowed_pattern in domain_rule.allowed:
                if self._match_pattern(host, allowed_pattern):
                    break
            else:
                if domain_rule.allowed:
                    check = ConstraintCheck(
                        passed=False,
                        boundary_type=BoundaryType.NETWORK_DOMAIN,
                        value=f"{host}:{port}",
                        message=f"域名不在允许列表中",
                        timestamp=time.time(),
                    )
                    self._violations.append(check)
                    return check

        port_rule = self._rules.get(BoundaryType.NETWORK_PORT)
        if port_rule and port_rule.enabled:
            port_str = str(port)
            if port_str in port_rule.blocked:
                check = ConstraintCheck(
                    passed=False,
                    boundary_type=BoundaryType.NETWORK_PORT,
                    value=f"{host}:{port}",
                    message=f"端口被阻止: {port}",
                    timestamp=time.time(),
                )
                self._violations.append(check)
                return check

            if port_rule.allowed and port_str not in port_rule.allowed:
                check = ConstraintCheck(
                    passed=False,
                    boundary_type=BoundaryType.NETWORK_PORT,
                    value=f"{host}:{port}",
                    message=f"端口不在允许列表中: {port}",
                    timestamp=time.time(),
                )
                self._violations.append(check)
                return check

        return ConstraintCheck(passed=True, boundary_type=BoundaryType.NETWORK_DOMAIN, value=f"{host}:{port}")

    def check_resource(self, resource_type: BoundaryType, value: float) -> ConstraintCheck:
        rule = self._rules.get(resource_type)
        if not rule or not rule.enabled:
            return ConstraintCheck(passed=True, boundary_type=resource_type, value=str(value))

        if rule.max_value is not None and value > rule.max_value:
            check = ConstraintCheck(
                passed=False,
                boundary_type=resource_type,
                value=str(value),
                message=f"超出限制: {value} > {rule.max_value}",
                timestamp=time.time(),
            )
            self._violations.append(check)
            return check

        return ConstraintCheck(passed=True, boundary_type=resource_type, value=str(value))

    def get_rule(self, boundary_type: BoundaryType) -> Optional[BoundaryRule]:
        return self._rules.get(boundary_type)

    def update_rule(self, boundary_type: BoundaryType, updates: dict):
        rule = self._rules.get(boundary_type)
        if rule:
            for key, value in updates.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)

    def get_violations(self, clear: bool = False) -> List[ConstraintCheck]:
        result = list(self._violations)
        if clear:
            self._violations.clear()
        return result

    def get_stats(self) -> dict:
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
            "violation_count": len(self._violations),
            "provider_count": len(self._providers),
            "providers": list(self._providers.keys()),
            "rules": {
                bt.value: {
                    "enabled": r.enabled,
                    "allowed_count": len(r.allowed),
                    "blocked_count": len(r.blocked),
                    "max_value": r.max_value,
                }
                for bt, r in self._rules.items()
            }
        }

    @staticmethod
    def _match_pattern(path: str, pattern: str) -> bool:
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            return path.lower().endswith(pattern[1:].lower())
        if pattern.startswith("*."):
            return path.lower().endswith(pattern[1:].lower())
        if "*" in pattern:
            prefix = pattern[:pattern.index("*")]
            suffix = pattern[pattern.index("*") + 1:]
            if prefix and suffix:
                return path.startswith(prefix) and path.endswith(suffix)
            if prefix:
                return path.startswith(prefix)
            if suffix:
                return path.endswith(suffix)
            return True
        return path == pattern or path.lower() == pattern.lower()

    @staticmethod
    def _match_prefix(path: str, allowed: str) -> bool:
        return path.startswith(allowed) or path.startswith(allowed + "/")