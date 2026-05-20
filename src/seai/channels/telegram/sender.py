# ══════════════════════════════════════════════════
# channels/telegram/sender.py - Telegram 发送器
# ══════════════════════════════════════════════════
import os, httpx

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
async def send_message(chat_id: int, text: str):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 4096):
        chunk = text[i:i+4096]
        try:
            async with httpx.AsyncClient() as client: await client.post(url, json={"chat_id": chat_id, "text": chunk})
        except Exception: pass