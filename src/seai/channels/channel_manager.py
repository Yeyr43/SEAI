# ════════════════════════════════════════════════
# channels/channel_manager.py - 渠道管理器
# ══════════════════════════════════════════════════
import asyncio
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from .base_channel import BaseChannel, ChannelMessage
from .message_protocol import MessageConverter, MessageQueue

class ChannelManager:
    """渠道管理器 - 适配现有SEAI架构"""
    
    def __init__(self, agent, config_dir: Path):
        self.agent = agent
        self.config_dir = config_dir
        self.channels: Dict[str, BaseChannel] = {}
        self.message_queue = MessageQueue(max_size=1000)
        self._is_running = False
        self._background_tasks = set()
        self.logger = logging.getLogger("ChannelManager")
    
    async def initialize(self):
        """初始化渠道管理器"""
        # 加载渠道配置
        channel_configs = self._load_channel_configs()
        
        # 初始化渠道
        for config in channel_configs:
            if config.get("enabled", True):
                await self._register_channel(config)
    
    async def _register_channel(self, config: Dict[str, Any]):
        """注册渠道"""
        channel_type = config.get("channel_type")
        
        try:
            # 根据类型创建渠道实例
            if channel_type == "telegram":
                from .telegram.adapter import TelegramAdapter
                channel = TelegramAdapter(config)
            else:
                self.logger.warning(f"未知渠道类型: {channel_type}")
                return
            
            # 启动渠道
            if await channel.start():
                self.channels[channel_type] = channel
                self.logger.info(f"渠道 {channel_type} 启动成功")
            else:
                self.logger.error(f"渠道 {channel_type} 启动失败")
        
        except Exception as e:
            self.logger.error(f"注册渠道 {channel_type} 失败: {e}")
    
    async def start(self):
        """启动渠道管理器"""
        if self._is_running:
            return
        
        self._is_running = True
        
        # 启动消息处理任务
        task = asyncio.create_task(self._process_messages())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # 启动渠道监听任务
        for channel_type, channel in self.channels.items():
            task = asyncio.create_task(self._listen_channel(channel_type, channel))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        
        self.logger.info("渠道管理器启动成功")
    
    async def stop(self):
        """停止渠道管理器"""
        self._is_running = False
        
        # 停止所有渠道
        for channel in self.channels.values():
            await channel.stop()
        
        # 取消后台任务
        for task in self._background_tasks:
            task.cancel()
        
        self.logger.info("渠道管理器已停止")
    
    async def _listen_channel(self, channel_type: str, channel: BaseChannel):
        """监听渠道消息"""
        while self._is_running and channel.is_running:
            try:
                async for message in channel.receive_messages():
                    # 将消息加入队列
                    if self.message_queue.enqueue(message):
                        self.logger.debug(f"收到来自 {channel_type} 的消息")
                    else:
                        self.logger.warning("消息队列已满，丢弃消息")
            
            except Exception as e:
                self.logger.error(f"监听渠道 {channel_type} 时出错: {e}")
                await asyncio.sleep(5)  # 等待后重试
    
    async def _process_messages(self):
        """处理消息队列"""
        while self._is_running:
            try:
                # 从队列获取消息
                message = self.message_queue.dequeue()
                if not message:
                    await asyncio.sleep(0.1)
                    continue
                
                # 转换为智能体格式
                agent_message = MessageConverter.to_agent_format(message)
                
                # 处理消息 - 使用现有agent.chat方法
                response = await self.agent.chat(
                    agent_message["content"],
                    session_id=f"{message.channel_type}_{message.user_id}"
                )
                
                # 转换响应并发送
                channel_response = MessageConverter.from_agent_format(response, message)
                await self._send_to_channel(channel_response)
            
            except Exception as e:
                self.logger.error(f"处理消息时出错: {e}")
    
    async def _send_to_channel(self, response: Dict[str, Any]):
        """发送响应到渠道"""
        channel_type = response.get("channel_type")
        user_id = response.get("user_id")
        content = response.get("content")
        
        if channel_type in self.channels:
            channel = self.channels[channel_type]
            try:
                await channel.send_message(user_id, content)
                self.logger.debug(f"响应已发送到 {channel_type}")
            except Exception as e:
                self.logger.error(f"发送响应到 {channel_type} 失败: {e}")
    
    def _load_channel_configs(self) -> List[Dict[str, Any]]:
        """加载渠道配置"""
        config_file = self.config_dir / "channels.json"
        
        if not config_file.exists():
            # 创建默认配置
            default_configs = [
                {
                    "channel_type": "telegram",
                    "enabled": False,
                    "bot_token": "",
                    "webhook_url": ""
                }
            ]
            
            import json
            config_file.write_text(json.dumps(default_configs, indent=2), encoding="utf-8")
            return default_configs
        
        import json
        return json.loads(config_file.read_text(encoding="utf-8"))
    
    async def get_channel_status(self) -> Dict[str, Any]:
        """获取所有渠道状态"""
        status = {}
        
        for channel_type, channel in self.channels.items():
            try:
                health = await channel.health_check()
                info = await channel.get_channel_info()
                
                status[channel_type] = {
                    "running": channel.is_running,
                    "healthy": health,
                    "info": info
                }
            except Exception as e:
                status[channel_type] = {
                    "running": False,
                    "healthy": False,
                    "error": str(e)
                }
        
        return status