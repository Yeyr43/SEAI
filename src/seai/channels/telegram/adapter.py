# ════════════════════════════════════════════════
# channels/telegram/adapter.py - Telegram 渠道适配器
# ══════════════════════════════════════════════════
import os
import logging
import httpx
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional
from ..base_channel import BaseChannel, ChannelMessage, MessageType
from ..message_protocol import MessageConverter

class TelegramAdapter(BaseChannel):
    """Telegram 渠道适配器 - 替换现有receiver.py/sender.py"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.bot_token = config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        self.webhook_url = config.get("webhook_url", "")
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self._offset = 0
        self._client: Optional[httpx.AsyncClient] = None
        self.logger = logging.getLogger("TelegramAdapter")
    
    async def initialize(self) -> bool:
        """初始化Telegram适配器"""
        if not self.bot_token:
            self.logger.error("未设置Telegram bot token")
            return False
        
        try:
            self._client = httpx.AsyncClient(timeout=30.0)
            
            # 验证token有效性
            me = await self._get_me()
            if me:
                self.logger.info(f"Telegram bot初始化成功: {me.get('username')}")
                return True
            else:
                self.logger.error("Telegram bot token无效")
                return False
        
        except Exception as e:
            self.logger.error(f"初始化Telegram适配器失败: {e}")
            return False
    
    async def receive_messages(self) -> AsyncGenerator[ChannelMessage, None]:
        """接收Telegram消息"""
        while self._is_running:
            try:
                # 使用长轮询获取更新
                updates = await self._get_updates(timeout=30)
                
                for update in updates:
                    # 解析消息
                    message = MessageConverter.parse_telegram_message(update)
                    if message:
                        yield message
                    
                    # 更新offset
                    self._offset = update.get("update_id", self._offset) + 1
            
            except Exception as e:
                self.logger.error(f"接收Telegram消息时出错: {e}")
                await asyncio.sleep(5)  # 等待后重试
    
    async def send_message(self, user_id: str, content: str, 
                          message_type: MessageType = MessageType.TEXT) -> bool:
        """发送消息到Telegram"""
        try:
            # 截断消息以符合Telegram限制
            content = self.truncate_message(content, max_length=4096)
            
            # 发送消息
            url = f"{self.api_base}/sendMessage"
            response = await self._client.post(url, json={
                "chat_id": user_id,
                "text": content,
                "parse_mode": "Markdown"
            })
            
            if response.status_code == 200:
                self.logger.debug(f"消息已发送到Telegram用户 {user_id}")
                return True
            else:
                self.logger.error(f"发送Telegram消息失败: {response.text}")
                return False
        
        except Exception as e:
            self.logger.error(f"发送Telegram消息时出错: {e}")
            return False
    
    async def get_channel_info(self) -> Dict[str, Any]:
        """获取Telegram渠道信息"""
        try:
            me = await self._get_me()
            return {
                "channel_type": "telegram",
                "bot_username": me.get("username"),
                "bot_name": me.get("first_name"),
                "can_join_groups": me.get("can_join_groups", False),
                "can_read_all_group_messages": me.get("can_read_all_group_messages", False),
                "supports_inline_queries": me.get("supports_inline_queries", False)
            }
        except Exception as e:
            self.logger.error(f"获取Telegram渠道信息失败: {e}")
            return {}
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            me = await self._get_me()
            return me is not None
        except Exception as e:
            self.logger.error(f"Telegram健康检查失败: {e}")
            return False
    
    async def _get_me(self) -> Optional[Dict[str, Any]]:
        """获取bot信息"""
        try:
            url = f"{self.api_base}/getMe"
            response = await self._client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("result")
            return None
        except Exception as e:
            self.logger.error(f"获取bot信息失败: {e}")
            return None
    
    async def _get_updates(self, timeout: int = 30) -> list:
        """获取更新"""
        try:
            url = f"{self.api_base}/getUpdates"
            params = {
                "offset": self._offset,
                "timeout": timeout,
                "allowed_updates": ["message"]
            }
            
            response = await self._client.get(url, params=params, timeout=timeout + 10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("result", [])
            return []
        except Exception as e:
            self.logger.error(f"获取更新失败: {e}")
            return []
    
    async def set_webhook(self, webhook_url: str) -> bool:
        """设置webhook"""
        try:
            url = f"{self.api_base}/setWebhook"
            response = await self._client.post(url, json={
                "url": webhook_url
            })
            
            if response.status_code == 200:
                data = response.json()
                return data.get("result", False)
            return False
        except Exception as e:
            self.logger.error(f"设置webhook失败: {e}")
            return False
    
    async def delete_webhook(self) -> bool:
        """删除webhook"""
        try:
            url = f"{self.api_base}/deleteWebhook"
            response = await self._client.post(url)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("result", False)
            return False
        except Exception as e:
            self.logger.error(f"删除webhook失败: {e}")
            return False
    
    async def stop(self):
        """停止适配器"""
        await super().stop()
        if self._client:
            await self._client.aclose()
            self._client = None