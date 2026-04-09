"""User settings endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.settings import UserSettings
from app.core.deps import get_current_user
from app.schemas.settings import SettingsResponse, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")
    return s


@router.put("", response_model=SettingsResponse)
async def update_settings(
    req: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(s, field, value)

    await db.commit()
    await db.refresh(s)
    return s


@router.post("/auto/on")
async def auto_on(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")
    s.auto_enabled = True
    await db.commit()
    return {"auto_enabled": True}


@router.post("/auto/off")
async def auto_off(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")
    s.auto_enabled = False
    await db.commit()
    return {"auto_enabled": False}


@router.post("/test-notification")
async def test_notification(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test notification to verify Telegram/Discord config."""
    from app.services.notifier import send_telegram, send_discord

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")

    results = {}
    if s.telegram_bot_token and s.telegram_chat_id:
        ok = await send_telegram(s.telegram_bot_token, s.telegram_chat_id, "FR Arb SaaS: Test notification")
        results["telegram"] = "sent" if ok else "failed"
    else:
        results["telegram"] = "not_configured"

    if s.discord_webhook:
        ok = await send_discord(s.discord_webhook, "FR Arb SaaS: Test notification")
        results["discord"] = "sent" if ok else "failed"
    else:
        results["discord"] = "not_configured"

    return results
