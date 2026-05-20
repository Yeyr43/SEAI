"""
技能仓储接口
定义统一的技能管理规范，支持多种存储后端
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path


class SkillRepository(ABC):
    """技能仓储抽象接口"""
    
    @abstractmethod
    async def load_skills(self) -> List[Dict]:
        """加载所有技能"""
        pass
    
    @abstractmethod
    async def execute_skill(self, name: str, args: Dict, security_manager=None) -> str:
        """执行技能"""
        pass
    
    @abstractmethod
    def get_all_skills(self) -> List[Dict]:
        """获取所有技能信息"""
        pass
    
    @abstractmethod
    def is_skill_enabled(self, name: str) -> bool:
        """检查技能是否启用"""
        pass
    
    @abstractmethod
    def set_skill_enabled(self, name: str, enabled: bool):
        """设置技能启用状态"""
        pass
    
    @abstractmethod
    def record_skill_usage(self, name: str, success: bool):
        """记录技能使用情况"""
        pass
    
    @abstractmethod
    def get_skill_score(self, name: str) -> float:
        """获取技能评分"""
        pass
    
    @abstractmethod
    def delete_skill(self, name: str):
        """删除技能"""
        pass
    
    @abstractmethod
    def create_skill(self, skill_data: Dict) -> bool:
        """创建新技能"""
        pass


class SkillRepositoryFactory:
    """技能仓储工厂类"""
    
    @staticmethod
    def create_file_based_repository(skills_dir: Path) -> SkillRepository:
        """创建基于文件的技能仓储"""
        from ..skill_system import SkillSystem
        return SkillSystem(skills_dir)
    
    @staticmethod
    def create_database_repository(db_url: str) -> SkillRepository:
        """创建数据库技能仓储"""
        from .database_skill_repository import DatabaseSkillRepository
        return DatabaseSkillRepository(db_url)
    
    @staticmethod
    def create_repository(repository_type: str, **kwargs) -> SkillRepository:
        """通用工厂方法"""
        if repository_type == "file":
            return SkillRepositoryFactory.create_file_based_repository(kwargs.get("skills_dir"))
        elif repository_type == "database":
            return SkillRepositoryFactory.create_database_repository(kwargs.get("db_url"))
        else:
            raise ValueError(f"不支持的技能仓储类型: {repository_type}")