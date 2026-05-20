# ════════════════════════════════════════════════
# channels/base_channel.py - 渠道适配器基类
# ══════════════════════════════════════════════════
from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncGenerator, Optional
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    FILE = "file"
    VIDEO = "video"
    STICKER = "sticker"

class MessagePriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

@dataclass
class ChannelMessage:
    """统一消息协议"""
    message_id: str
    channel_type: str
    user_id: str
    message_type: MessageType
    content: str
    metadata: Dict[str, Any]
    timestamp: datetime
    priority: MessagePriority = MessagePriority.NORMAL
    reply_to: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel_type": self.channel_type,
            "user_id": self.user_id,
            "message_type": self.message_type.value,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority.value,
            "reply_to": self.reply_to
        }

class BaseChannel(ABC):
    """渠道适配器基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.channel_type = config.get("channel_type", "unknown")
        self.enabled = config.get("enabled", True)
        self._is_running = False
    
    @abstractmethod
    async def initialize(self) -> bool:
        """初始化渠道"""
        pass
    
    @abstractmethod
    async def receive_messages(self) -> AsyncGenerator[ChannelMessage, None]:
        """接收消息流"""
        pass
    
    @abstractmethod
    async def send_message(self, user_id: str, content: str, 
                          message_type: MessageType = MessageType.TEXT) -> bool:
        """发送消息"""
        pass
    
    @abstractmethod
    async def get_channel_info(self) -> Dict[str, Any]:
        """获取渠道信息"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass
    
    async def start(self):
        """启动渠道"""
        if not self.enabled:
            return False
        
        if await self.initialize():
            self._is_running = True
            return True
        return False
    
    async def stop(self):
        """停止渠道"""
        self._is_running = False
    
    @property
    def is_running(self) -> bool:
        return self._is_running
    
    def format_message(self, content: str, **kwargs) -> str:
        """格式化消息（可被子类重写）"""
        return content
    
    def truncate_message(self, content: str, max_length: int = 4096) -> str:
        """截断消息以符合渠道限制"""
        if len(content) <= max_length:
            return content
        return content[:max_length-3] + "..."