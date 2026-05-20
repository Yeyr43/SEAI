# ════════════════════════════════════════════════
# channels/message_protocol.py - 统一消息协议
# ══════════════════════════════════════════════════
from typing import Dict, Any, Optional
from datetime import datetime
import re
from .base_channel import ChannelMessage, MessageType

class MessageConverter:
    """消息转换器"""
    
    @staticmethod
    def to_agent_format(message: ChannelMessage) -> Dict[str, Any]:
        """转换为智能体内部格式"""
        return {
            "role": "user",
            "content": message.content,
            "metadata": {
                "channel_type": message.channel_type,
                "user_id": message.user_id,
                "message_type": message.message_type.value,
                "message_id": message.message_id,
                "timestamp": message.timestamp.isoformat(),
                "priority": message.priority.value
            },
            "original_message": message.to_dict()
        }
    
    @staticmethod
    def from_agent_format(response: str, original_message: ChannelMessage) -> Dict[str, Any]:
        """从智能体响应转换为渠道格式"""
        return {
            "content": response,
            "channel_type": original_message.channel_type,
            "user_id": original_message.user_id,
            "reply_to": original_message.message_id,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def parse_telegram_message(update: Dict) -> Optional[ChannelMessage]:
        """解析Telegram消息"""
        try:
            msg = update.get("message", {})
            text = msg.get("text", "")
            if not text:
                return None
            
            chat = msg.get("chat", {})
            user = msg.get("from", {})
            
            return ChannelMessage(
                message_id=str(msg.get("message_id", "")),
                channel_type="telegram",
                user_id=str(chat.get("id", user.get("id", ""))),
                message_type=MessageType.TEXT,
                content=text,
                metadata={
                    "chat_id": chat.get("id"),
                    "username": user.get("username", ""),
                    "first_name": user.get("first_name", ""),
                    "chat_type": chat.get("type", "")
                },
                timestamp=datetime.now(),
                reply_to=str(msg.get("reply_to_message", {}).get("message_id", "")) if msg.get("reply_to_message") else None
            )
        except Exception as e:
            print(f"解析Telegram消息失败: {e}")
            return None

class MessageQueue:
    """消息队列"""
    
    def __init__(self, max_size: int = 1000):
        self.queue = []
        self.max_size = max_size
    
    def enqueue(self, message: ChannelMessage) -> bool:
        """入队"""
        if len(self.queue) >= self.max_size:
            return False
        
        # 按优先级插入
        message.priority = message.priority or MessagePriority.NORMAL
        self.queue.append(message)
        self.queue.sort(key=lambda x: self._priority_value(x.priority), reverse=True)
        return True
    
    def dequeue(self) -> Optional[ChannelMessage]:
        """出队"""
        if not self.queue:
            return None
        return self.queue.pop(0)
    
    def peek(self) -> Optional[ChannelMessage]:
        """查看队首消息"""
        if not self.queue:
            return None
        return self.queue[0]
    
    def size(self) -> int:
        return len(self.queue)
    
    def clear(self):
        self.queue.clear()
    
    @staticmethod
    def _priority_value(priority: MessagePriority) -> int:
        values = {
            MessagePriority.LOW: 1,
            MessagePriority.NORMAL: 2,
            MessagePriority.HIGH: 3,
            MessagePriority.URGENT: 4
        }
        return values.get(priority, 2)