"""Notification service for Telegram and Discord."""
import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 10


async def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Send a message via Telegram Bot API."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TELEGRAM_API.format(token=bot_token),
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=TIMEOUT,
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


async def send_discord(webhook_url: str, message: str) -> bool:
    """Send a message via Discord Webhook."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{webhook_url}?wait=true",
                json={
                    "content": "",
                    "thread_name": "FR Arb Auto Trading",
                    "embeds": [{"description": message, "color": 0x00AAFF}],
                },
                timeout=TIMEOUT,
            )
            return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning(f"Discord send failed: {e}")
        return False


async def notify_user(settings, event_type: str, details: str):
    """Send notification to user's configured channels.

    Args:
        settings: UserSettings ORM object
        event_type: entry_opened, position_closed, error, daily_summary
        details: Pre-formatted message string
    """
    prefix = {
        "entry_opened": "Entry",
        "position_closed": "Close",
        "error": "Error",
        "daily_summary": "Summary",
    }.get(event_type, event_type)

    message = f"[{prefix}] {details}"

    if settings.telegram_bot_token and settings.telegram_chat_id:
        await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, message)

    if settings.discord_webhook:
        await send_discord(settings.discord_webhook, message)
