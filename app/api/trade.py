"""Manual trade endpoints."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.position import Position
from app.models.trade_log import TradeLog
from app.core.deps import get_current_user
from app.schemas.position import ManualEntryRequest, PositionResponse, TradeLogResponse

router = APIRouter(prefix="/api/trade", tags=["trade"])


@router.post("/entry", response_model=PositionResponse)
async def manual_entry(
    req: ManualEntryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Place a manual trade via exchange API."""
    from app.services.exchange_factory import create_user_exchanges

    exchanges = await create_user_exchanges(user.id, db)
    if req.exchange not in exchanges:
        raise HTTPException(status_code=400, detail=f"Exchange {req.exchange} not configured")

    ex = exchanges[req.exchange]
    if not ex.can_trade_api:
        raise HTTPException(status_code=400, detail=f"{req.exchange} does not support API trading")

    # Place order
    result = ex.place_market_order(req.base, req.side, req.amount_usdt, req.leverage)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=f"Order failed: {result.get('error')}")

    # Record position
    position = Position(
        user_id=user.id,
        type=req.type,
        base=req.base,
        legs={"side": req.side, "exchange": req.exchange, "order_id": result.get("order_id")},
        amount_usd=req.amount_usdt,
        leverage=req.leverage,
        status="open",
    )
    db.add(position)

    # Log trade
    db.add(TradeLog(
        user_id=user.id,
        action="entry",
        type=req.type,
        base=req.base,
        exchange=req.exchange,
        details={"side": req.side, "amount": req.amount_usdt, "leverage": req.leverage, "order_id": result.get("order_id")},
    ))

    await db.commit()
    await db.refresh(position)
    return position


@router.post("/close/{position_id}", response_model=PositionResponse)
async def close_position(
    position_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close a specific position."""
    import uuid as uuid_mod
    from app.services.exchange_factory import create_user_exchanges

    pos = await db.get(Position, uuid_mod.UUID(position_id))
    if not pos or pos.user_id != user.id:
        raise HTTPException(status_code=404, detail="Position not found")
    if pos.status != "open":
        raise HTTPException(status_code=400, detail="Position already closed")

    exchanges = await create_user_exchanges(user.id, db)
    exchange_name = pos.legs.get("exchange")
    if exchange_name not in exchanges:
        raise HTTPException(status_code=400, detail=f"Exchange {exchange_name} not available")

    ex = exchanges[exchange_name]
    side = pos.legs.get("side", "BUY")
    position_side = "LONG" if side == "BUY" else "SHORT"

    result = ex.close_position(pos.base, position_side)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=f"Close failed: {result.get('error')}")

    pos.status = "closed"
    pos.closed_at = datetime.now(timezone.utc)
    pos.close_reason = "manual"

    db.add(TradeLog(
        user_id=user.id,
        action="close",
        type=pos.type,
        base=pos.base,
        exchange=exchange_name,
        details={"reason": "manual", "order_id": result.get("order_id")},
    ))

    await db.commit()
    await db.refresh(pos)
    return pos


@router.get("/history", response_model=list[TradeLogResponse])
async def trade_history(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TradeLog)
        .where(TradeLog.user_id == user.id)
        .order_by(TradeLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()
