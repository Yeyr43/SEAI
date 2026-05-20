"""
SEAI 智能体核心 — 组合 6 个 mixin 为 SEAgent

模块通过 mixin 模式拆分：
- AgentMixin:      核心属性、工具方法、Token 追踪
- BootstrapMixin:  初始化与组件装配
- ExecutionMixin:  查询执行、多Agent路由、消息构建
- SessionMixin:    会话管理
- FeedbackMixin:   反馈处理、微反思、自检查
- StatusMixin:     状态报告、配置管理
"""

from .agent_mixin import AgentMixin
from .bootstrap_mixin import BootstrapMixin
from .execution_mixin import ExecutionMixin
from .session_mixin import SessionMixin
from .feedback_mixin import FeedbackMixin
from .status_mixin import StatusMixin


class SEAgent(
    AgentMixin,
    BootstrapMixin,
    ExecutionMixin,
    SessionMixin,
    FeedbackMixin,
    StatusMixin,
):
    """SEAI 智能体核心 — 组合自 6 个协作文档"""


__all__ = ["SEAgent"]
