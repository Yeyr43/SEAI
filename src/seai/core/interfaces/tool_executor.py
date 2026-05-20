"""
工具执行器接口
定义统一的工具执行规范，支持多种执行模式
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List


class ToolExecutor(ABC):
    """工具执行器抽象接口"""
    
    @abstractmethod
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行工具"""
        pass
    
    @abstractmethod
    def get_tool_definitions(self) -> List[Dict]:
        """获取工具定义列表"""
        pass
    
    @abstractmethod
    def register_tool(self, name: str, func, description: str = "", params: Dict = None):
        """注册工具"""
        pass
    
    @abstractmethod
    def unregister_tool(self, name: str):
        """注销工具"""
        pass
    
    @abstractmethod
    def get_available_tools(self) -> List[str]:
        """获取可用工具列表"""
        pass
    
    @abstractmethod
    def validate_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """验证工具调用"""
        pass


class ToolExecutorFactory:
    """工具执行器工厂类"""
    
    @staticmethod
    def create_executor(executor_type: str = "default", **kwargs) -> ToolExecutor:
        """通用工厂方法"""
        if executor_type == "default":
            from ..tool_registry import ToolRegistry
            return ToolRegistry(kwargs.get("security_manager"))
        elif executor_type == "sandbox":
            from ..sandbox import SandboxExecutor
            raise NotImplementedError(
                "SandboxToolExecutor 尚未实现，沙箱模式暂不可用。"
                "请使用 executor_type='default' 或自行实现 SandboxToolExecutor。"
            )
        else:
            raise ValueError(f"不支持的工具执行器类型: {executor_type}")