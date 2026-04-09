"""API Token management endpoints (JWT-protected)."""
import hashlib
import secrets
import uuid as uuid_mod
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.api_token import APIToken
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class CreateTokenRequest(BaseModel):
    name: str
    expires_days: int | None = None  # None = no expiry


class TokenResponse(BaseModel):
    id: str
    name: str
    is_revoked: bool
    last_used: str | None
    expires_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class TokenCreatedResponse(BaseModel):
    """Returned only once on creation. Contains the raw token."""
    id: str
    name: str
    token: str  # Raw token — shown only once
    expires_at: str | None
    created_at: str


@router.post("", response_model=TokenCreatedResponse)
async def create_token(
    req: CreateTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new API token for the desktop client."""
    # Limit: max 5 active tokens per user
    result = await db.execute(
        select(APIToken).where(APIToken.user_id == user.id, APIToken.is_revoked.is_(False))
    )
    active = result.scalars().all()
    if len(active) >= 5:
        raise HTTPException(status_code=400, detail="Maximum 5 active tokens allowed")

    # Generate token
    raw_token = f"fra_{secrets.token_hex(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expires_at = None
    if req.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_days)

    api_token = APIToken(
        user_id=user.id,
        token_hash=token_hash,
        name=req.name,
        expires_at=expires_at,
    )
    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)

    return TokenCreatedResponse(
        id=str(api_token.id),
        name=api_token.name,
        token=raw_token,
        expires_at=api_token.expires_at.isoformat() if api_token.expires_at else None,
        created_at=api_token.created_at.isoformat(),
    )


@router.get("", response_model=list[TokenResponse])
async def list_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all API tokens for the current user."""
    result = await db.execute(
        select(APIToken)
        .where(APIToken.user_id == user.id)
        .order_by(APIToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [
        TokenResponse(
            id=str(t.id),
            name=t.name,
            is_revoked=t.is_revoked,
            last_used=t.last_used.isoformat() if t.last_used else None,
            expires_at=t.expires_at.isoformat() if t.expires_at else None,
            created_at=t.created_at.isoformat(),
        )
        for t in tokens
    ]


@router.delete("/{token_id}")
async def revoke_token(
    token_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API token."""
    token = await db.get(APIToken, uuid_mod.UUID(token_id))
    if not token or token.user_id != user.id:
        raise HTTPException(status_code=404, detail="Token not found")
    token.is_revoked = True
    db.add(token)
    await db.commit()
    return {"status": "revoked"}
