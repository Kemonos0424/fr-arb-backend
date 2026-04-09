"""API key management endpoints."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.api_key import ExchangeApiKey
from app.core.deps import get_current_user
from app.services.crypto import encrypt
from app.schemas.scan import ApiKeyCreate, ApiKeyStatus

router = APIRouter(prefix="/api/keys", tags=["keys"])

SUPPORTED_EXCHANGES = {"bingx", "bitget", "bitmart"}


@router.get("/", response_model=list[ApiKeyStatus])
async def list_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeApiKey).where(ExchangeApiKey.user_id == user.id)
    )
    keys = result.scalars().all()
    configured = {k.exchange: k for k in keys}

    statuses = []
    for ex in SUPPORTED_EXCHANGES:
        if ex in configured:
            k = configured[ex]
            statuses.append(ApiKeyStatus(
                exchange=ex, is_configured=True,
                is_valid=k.is_valid, last_verified=k.last_verified,
            ))
        else:
            statuses.append(ApiKeyStatus(
                exchange=ex, is_configured=False,
                is_valid=False, last_verified=None,
            ))
    return statuses


@router.post("/{exchange}")
async def save_key(
    exchange: str,
    req: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if exchange not in SUPPORTED_EXCHANGES:
        raise HTTPException(status_code=400, detail=f"Unsupported exchange: {exchange}")

    # Upsert
    result = await db.execute(
        select(ExchangeApiKey).where(
            ExchangeApiKey.user_id == user.id,
            ExchangeApiKey.exchange == exchange,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.api_key_enc = encrypt(req.api_key)
        existing.secret_enc = encrypt(req.secret_key)
        existing.passphrase_enc = encrypt(req.passphrase) if req.passphrase else None
        existing.memo_enc = encrypt(req.memo) if req.memo else None
        existing.is_valid = True
        existing.last_verified = None
    else:
        db.add(ExchangeApiKey(
            user_id=user.id,
            exchange=exchange,
            api_key_enc=encrypt(req.api_key),
            secret_enc=encrypt(req.secret_key),
            passphrase_enc=encrypt(req.passphrase) if req.passphrase else None,
            memo_enc=encrypt(req.memo) if req.memo else None,
        ))

    await db.commit()
    return {"status": "saved"}


@router.delete("/{exchange}")
async def delete_key(
    exchange: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeApiKey).where(
            ExchangeApiKey.user_id == user.id,
            ExchangeApiKey.exchange == exchange,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    await db.delete(key)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{exchange}/verify")
async def verify_key(
    exchange: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test connectivity with stored API key by calling get_balance()."""
    from app.services.exchange_factory import create_user_exchanges

    exchanges = await create_user_exchanges(user.id, db)
    if exchange not in exchanges:
        raise HTTPException(status_code=404, detail="Key not configured for this exchange")

    ex = exchanges[exchange]
    if not ex.can_trade_api:
        raise HTTPException(status_code=400, detail="Read-only exchange")

    try:
        balance = ex.get_balance()
        if "error" in balance:
            # Mark as invalid
            result = await db.execute(
                select(ExchangeApiKey).where(
                    ExchangeApiKey.user_id == user.id,
                    ExchangeApiKey.exchange == exchange,
                )
            )
            key = result.scalar_one_or_none()
            if key:
                key.is_valid = False
                await db.commit()
            return {"status": "invalid", "error": balance["error"]}

        # Mark as valid
        result = await db.execute(
            select(ExchangeApiKey).where(
                ExchangeApiKey.user_id == user.id,
                ExchangeApiKey.exchange == exchange,
            )
        )
        key = result.scalar_one_or_none()
        if key:
            key.is_valid = True
            key.last_verified = datetime.now(timezone.utc)
            await db.commit()

        return {"status": "valid", "balance": balance}
    except Exception as e:
        return {"status": "error", "error": str(e)}
