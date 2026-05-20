"""
智能体生命周期管理
管理智能体的初始化、运行、关闭等生命周期事件
支持并行初始化以降低启动延迟
"""
import asyncio
import time
from loguru import logger
from typing import Optional, Dict, Any
from pathlib import Path
from .config import ConfigManager, config_manager
from .interfaces.llm_provider import LLMProvider, LLMProviderFactory
from .interfaces.memory_store import MemoryStore, MemoryStoreFactory
from .interfaces.tool_executor import ToolExecutor, ToolExecutorFactory
from .interfaces.skill_repository import SkillRepository, SkillRepositoryFactory


class AgentLifecycleManager:
    """智能体生命周期管理器"""
    
    def __init__(self, config: ConfigManager = None):
        self.config = config or config_manager
        self.llm_provider: Optional[LLMProvider] = None
        self.memory_store: Optional[MemoryStore] = None
        self.tool_executor: Optional[ToolExecutor] = None
        self.skill_repository: Optional[SkillRepository] = None
        self._agent = None
        self._is_initialized = False
        self._background_tasks = set()
        self._last_deep_evolve_time = 0.0
        self._deep_evolve_interval = 3600.0 * 6
    
    def set_agent(self, agent):
        self._agent = agent

    async def initialize(self) -> bool:
        """初始化智能体组件（并行初始化以降低启动延迟）"""
        start_time = time.time()
        llm_ok = False

        async def init_llm():
            nonlocal llm_ok
            try:
                llm_endpoints = self.config.get_llm_endpoints()
                self.llm_provider = LLMProviderFactory.create_openai_provider(llm_endpoints)
                llm_ok = True
                logger.info("LLM 提供者初始化完成")
            except Exception as e:
                logger.error(f"LLM 提供者初始化失败: {e}")

        async def init_memory():
            try:
                if self.llm_provider:
                    memory_config = self.config.get_memory_config()
                    self.memory_store = MemoryStoreFactory.create_store(
                        store_type="chroma",
                        persist_dir=memory_config.persist_dir,
                        llm_provider=self.llm_provider,
                    )
                    logger.info("记忆存储初始化完成")
            except Exception as e:
                logger.error(f"记忆存储初始化失败: {e}")

        async def init_tool_executor():
            try:
                from .security import SecurityManager
                system_config = self.config.get_system_config()
                security = SecurityManager(
                    workspace=system_config.workspace_dir,
                    skills_dir=system_config.data_dir / "skills",
                )
                security.load_config(self.config._config_cache)
                self.tool_executor = ToolExecutorFactory.create_executor(
                    executor_type="default", security_manager=security
                )
                logger.info("工具执行器初始化完成")
            except Exception as e:
                logger.error(f"工具执行器初始化失败: {e}")

        async def init_skill_repository():
            try:
                system_config = self.config.get_system_config()
                skills_dir = system_config.data_dir / "skills"
                self.skill_repository = SkillRepositoryFactory.create_file_based_repository(skills_dir)
                await self.skill_repository.load_skills()
                logger.info("技能仓储初始化完成")
            except Exception as e:
                logger.error(f"技能仓储初始化失败: {e}")

        await init_llm()

        if llm_ok:
            await asyncio.gather(
                init_memory(),
                init_tool_executor(),
                init_skill_repository(),
                return_exceptions=True,
            )

        try:
            await self._start_background_tasks()
        except Exception as e:
            logger.error(f"后台任务启动失败: {e}")

        self._is_initialized = llm_ok
        elapsed = (time.time() - start_time) * 1000
        if llm_ok:
            logger.info(f"智能体初始化完成 ({elapsed:.0f}ms)")
        return llm_ok
    
    async def shutdown(self):
        for task in self._background_tasks:
            task.cancel()

        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        if self.memory_store and hasattr(self.memory_store, 'client'):
            try:
                self.memory_store.client.close()
            except Exception as e:
                logger.warning("关闭 ChromaDB 客户端时出错: {}", e)

        self._is_initialized = False
        logger.info("智能体已关闭")
    
    async def _start_background_tasks(self):
        """启动后台任务"""
        # 1. 记忆归档任务
        archive_task = asyncio.create_task(self._archive_memories_task())
        self._background_tasks.add(archive_task)
        archive_task.add_done_callback(self._background_tasks.discard)
        
        # 2. 技能统计任务
        stats_task = asyncio.create_task(self._update_skill_stats_task())
        self._background_tasks.add(stats_task)
        stats_task.add_done_callback(self._background_tasks.discard)
        
        # 3. 配置监控任务
        config_task = asyncio.create_task(self._monitor_config_changes_task())
        self._background_tasks.add(config_task)
        config_task.add_done_callback(self._background_tasks.discard)
        
        # 4. 技能自动淘汰检查任务（每24小时）
        curator_task = asyncio.create_task(self._curator_task())
        self._background_tasks.add(curator_task)
        curator_task.add_done_callback(self._background_tasks.discard)

        # 5. 深度进化定时任务（每6小时）
        evolve_task = asyncio.create_task(self._scheduled_deep_evolve_task())
        self._background_tasks.add(evolve_task)
        evolve_task.add_done_callback(self._background_tasks.discard)
    
    async def _archive_memories_task(self):
        """记忆归档后台任务"""
        while True:
            try:
                if self.memory_store:
                    self.memory_store.archive_old_memories()
                await asyncio.sleep(3600)  # 每小时执行一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"记忆归档任务异常: {e}")
                await asyncio.sleep(300)
    
    async def _update_skill_stats_task(self):
        while True:
            try:
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"技能统计任务异常: {e}")
                await asyncio.sleep(300)
    
    async def _monitor_config_changes_task(self):
        last_mtime = self.config.config_path.stat().st_mtime if self.config.config_path.exists() else 0
        
        while True:
            try:
                if self.config.config_path.exists():
                    current_mtime = self.config.config_path.stat().st_mtime
                    if current_mtime > last_mtime:
                        logger.info("检测到配置文件变更，重新加载配置")
                        self.config._load_config()
                        last_mtime = current_mtime
                
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"配置监控任务异常: {e}")
                await asyncio.sleep(60)

    async def _curator_task(self):
        await asyncio.sleep(600)
        while True:
            try:
                if self._agent and hasattr(self._agent, '_curator_check'):
                    archived_count = await self._agent._curator_check()
                    if archived_count > 0:
                        logger.info(f"Curator: 已归档 {archived_count} 个低活跃技能")
                await asyncio.sleep(86400)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"技能淘汰检查异常: {e}")
                await asyncio.sleep(3600)

    async def _scheduled_deep_evolve_task(self):
        await asyncio.sleep(1800)
        while True:
            try:
                if self._agent and hasattr(self._agent, 'deep_evolve'):
                    result = await self._agent.deep_evolve()
                    if result.get("success"):
                        logger.info(f"定时深度进化完成: {result.get('analysis', '')[:100]}")
                    else:
                        logger.warning(f"定时深度进化未完全成功: {result.get('errors', [])}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"定时深度进化异常: {e}")
            await asyncio.sleep(self._deep_evolve_interval)

    def trigger_deep_evolve(self) -> bool:
        self._last_deep_evolve_time = 0.0
        return True
    
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._is_initialized
    
    def get_component_status(self) -> Dict[str, str]:
        """获取组件状态"""
        return {
            "llm_provider": "已初始化" if self.llm_provider else "未初始化",
            "memory_store": "已初始化" if self.memory_store else "未初始化",
            "tool_executor": "已初始化" if self.tool_executor else "未初始化",
            "skill_repository": "已初始化" if self.skill_repository else "未初始化",
            "background_tasks": f"运行中({len(self._background_tasks)})" if self._background_tasks else "未运行"
        }