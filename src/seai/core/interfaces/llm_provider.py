"""
LLM 服务提供者接口
定义统一的 LLM 调用规范，支持多种后端实现
"""
from abc import ABC, abstractmethod
from typing import List, Dict, AsyncGenerator, Optional


class LLMProvider(ABC):
    """LLM 服务提供者抽象接口"""
    
    @abstractmethod
    async def chat(self, messages: List[Dict]) -> str:
        """同步对话调用"""
        pass
    
    @abstractmethod
    async def chat_stream(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        """流式对话调用"""
        pass
    
    @abstractmethod
    def chat_with_tools(
        self, 
        messages: List[Dict], 
        tools: List[Dict], 
        stream: bool = False
    ):
        """带工具调用的对话"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[str]:
        """获取可用模型列表"""
        pass
    
    @abstractmethod
    def set_current_model(self, model_name: str):
        """设置当前使用的模型"""
        pass
    
    @abstractmethod
    def get_current_model(self) -> str:
        """获取当前使用的模型"""
        pass


class LLMProviderFactory:
    """LLM 提供者工厂类"""
    
    @staticmethod
    def create_openai_provider(endpoints: List) -> LLMProvider:
        """创建 OpenAI 兼容的提供者"""
        from ..llm_manager import LLMManager
        normalized = []
        for ep in endpoints:
            if isinstance(ep, dict):
                normalized.append(ep)
            else:
                normalized.append({"name": ep.name, "api_base": ep.api_base, "api_key": ep.api_key, "model": ep.model, "priority": getattr(ep, "priority", 0)})
        return LLMManager(normalized)
    
    @staticmethod
    def create_ollama_provider(base_url: str = "http://127.0.0.1:11434") -> LLMProvider:
        """创建 Ollama 提供者"""
        from .ollama_provider import OllamaProvider
        return OllamaProvider(base_url)
    
    @staticmethod
    def create_provider(provider_type: str, **kwargs) -> LLMProvider:
        """通用工厂方法"""
        if provider_type == "openai":
            return LLMProviderFactory.create_openai_provider(kwargs.get("endpoints", []))
        elif provider_type == "ollama":
            return LLMProviderFactory.create_ollama_provider(kwargs.get("base_url"))
        else:
            raise ValueError(f"不支持的 LLM 提供者类型: {provider_type}")