"""Dashboard endpoints: positions, balances, P&L."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.position import Position
from app.models.trade_log import TradeLog
from app.core.deps import get_current_user
from app.schemas.position import PositionResponse

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(
    status: str = Query("open", regex="^(open|closed|all)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Position).where(Position.user_id == user.id)
    if status != "all":
        q = q.where(Position.status == status)
    q = q.order_by(Position.opened_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/balances")
async def get_balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch real-time balances from configured exchanges."""
    from app.services.exchange_factory import create_user_exchanges

    exchanges = await create_user_exchanges(user.id, db)
    balances = {}
    for name, ex in exchanges.items():
        if not ex.can_trade_api:
            continue
        try:
            balances[name] = ex.get_balance()
        except NotImplementedError:
            pass
        except Exception as e:
            balances[name] = {"error": str(e)}
    return balances


@router.get("/pnl")
async def get_pnl(
    period: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if period == "daily":
        since = now - timedelta(days=1)
    elif period == "weekly":
        since = now - timedelta(weeks=1)
    else:
        since = now - timedelta(days=30)

    result = await db.execute(
        select(
            func.count(Position.id).label("trades"),
            func.sum(Position.actual_pnl).label("total_pnl"),
        ).where(
            Position.user_id == user.id,
            Position.status == "closed",
            Position.closed_at >= since,
        )
    )
    row = result.one()
    return {
        "period": period,
        "trades": row.trades or 0,
        "total_pnl": float(row.total_pnl or 0),
    }
