"""
记忆存储接口
定义统一的记忆存储规范，支持多种存储后端
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path


class MemoryStore(ABC):
    """记忆存储抽象接口"""
    
    @abstractmethod
    def add_memory(self, content: str, metadata: Dict = None) -> str:
        """添加短期记忆"""
        pass
    
    @abstractmethod
    def search_memory(self, query: str, top_k: int = 5) -> List[str]:
        """搜索短期记忆"""
        pass
    
    @abstractmethod
    def add_long_term_memory(
        self, 
        summary: str, 
        relations: Dict = None, 
        mem_type: str = "text"
    ) -> str:
        """添加长期记忆"""
        pass
    
    @abstractmethod
    def get_recent_memories(self, limit: int = 10) -> List[Dict]:
        """获取最近记忆"""
        pass
    
    @abstractmethod
    def get_context_for_query(self, query: str, depth: int = 2) -> str:
        """获取查询相关上下文"""
        pass
    
    @abstractmethod
    def get_user_profile(self) -> Optional[str]:
        """获取用户画像"""
        pass
    
    @abstractmethod
    def update_user_profile(self, content: str):
        """更新用户画像"""
        pass
    
    @abstractmethod
    def get_global_knowledge(self) -> Optional[str]:
        """获取全局知识"""
        pass
    
    @abstractmethod
    def archive_old_memories(self):
        """归档旧记忆"""
        pass

    @abstractmethod
    def add_long_term_memory_with_links(
        self,
        summary: str,
        relations: Dict = None,
        mem_type: str = "text",
        storage_mode: str = "auto",
    ) -> str:
        """添加长期记忆（含实体链接）"""
        pass

    @abstractmethod
    def search_by_type(self, query: str, mem_types: list, top_k: int = 5) -> list:
        """按类型检索记忆"""
        pass

    @abstractmethod
    def get_graph_context(self, query: str, depth: int = 2) -> str:
        """获取知识图谱上下文"""
        pass

    @abstractmethod
    def get_memories_by_timerange(
        self,
        start_time: str = None,
        end_time: str = None,
        mem_types: list = None,
        limit: int = 20,
    ) -> list:
        """按时间范围检索记忆"""
        pass

    @abstractmethod
    def store_media(self, media_id: str, media_type: str, media_data: str, metadata: dict = None) -> bool:
        """存储媒体数据（图片/音频 base64 持久化到磁盘）"""
        pass

    @abstractmethod
    def get_media(self, media_id: str) -> Optional[str]:
        """根据 media_id 取回 base64 媒体数据"""
        pass


class MemoryStoreFactory:
    """记忆存储工厂类"""
    
    @staticmethod
    def create_store(store_type: str, **kwargs) -> MemoryStore:
        """通用工厂方法"""
        if store_type == "chroma":
            from ..memory_engine import MemoryEngine
            return MemoryEngine(
                kwargs.get("persist_dir"),
                kwargs.get("llm_provider")
            )
        else:
            raise ValueError(f"不支持的记忆存储类型: {store_type}（当前仅支持 chroma）")