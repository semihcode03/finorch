"""Telegram bildirimi (Bot API, httpx ile - ekstra bagimlilik gerektirmez)."""

from __future__ import annotations

import logging

import httpx

from finorch.config import settings

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


def _url(method: str) -> str:
    return _API.format(token=settings.telegram_bot_token, method=method)


def send_message(text: str, chat_id: str | None = None) -> bool:
    """Belirtilen chat'e mesaj gonderir. chat_id verilmezse ayarlardaki kullanilir."""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN tanimli degil.")
        return False
    chat_id = chat_id or settings.telegram_chat_id
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID tanimli degil (finorch get-chat-id ile ogrenin).")
        return False

    try:
        resp = httpx.post(
            _url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("Telegram mesaji gonderilemedi: %s", e)
        return False


def get_chat_ids() -> list[dict]:
    """getUpdates ile son mesajlari cekip chat id'leri dondurur.

    Kullanim: botunuza Telegram'dan bir mesaj gonderin, sonra bunu calistirin.
    """
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN tanimli degil.")
    resp = httpx.get(_url("getUpdates"), timeout=20)
    resp.raise_for_status()
    data = resp.json()

    seen: dict[str, dict] = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            cid = str(chat["id"])
            seen[cid] = {
                "chat_id": cid,
                "type": chat.get("type", ""),
                "title": chat.get("title") or chat.get("username") or chat.get("first_name", ""),
            }
    return list(seen.values())
