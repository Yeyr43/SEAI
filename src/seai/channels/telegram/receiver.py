# ══════════════════════════════════════════════════
# channels/telegram/receiver.py - Telegram 接收器
# ══════════════════════════════════════════════════
from loguru import logger

async def handle_telegram_update(update: dict, agent):
    try:
        msg = update.get("message", {})
        text = msg.get("text", ""); chat_id = msg.get("chat", {}).get("id")
        if text and chat_id:
            result = await agent.chat(text)
            from .sender import send_message
            await send_message(chat_id, result)
    except Exception as e:
        logger.error(f"Telegram 处理失败：{e}")