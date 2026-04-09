"""Signal API — FR arbitrage signals for desktop client.

Authenticated via API token (not JWT).
Plan-gated: Free = P3 only, 10 max. Pro = all, 500 max.
"""
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.api_token import APIToken
from app.models.settings import UserSettings
from app.models.fr_scan_cache import FRScanCache
from app.core.deps import get_signal_user

router = APIRouter(prefix="/api/signals", tags=["signals"])

PLAN_LIMITS = {
    "free": {"strategies": ["p3"], "max_signals": 10},
    "pro": {"strategies": ["p1", "p2", "p3"], "max_signals": 500},
}


@router.get("/fr")
async def get_fr_signals(
    auth: tuple[User, APIToken] = Depends(get_signal_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
):
    """Get FR arbitrage signals. Requires API token auth."""
    user, api_token = auth
    plan = user.plan or "free"
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    # Cap limit by plan
    effective_limit = min(limit, limits["max_signals"])

    # Get user settings
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    settings = result.scalar_one_or_none()
    if not settings:
        return {"timestamp": datetime.now(timezone.utc).isoformat(), "signals": [], "summary": _empty_summary(), "plan": plan}

    # Get latest scan
    result = await db.execute(
        select(FRScanCache.scan_time).order_by(FRScanCache.scan_time.desc()).limit(1)
    )
    latest_time = result.scalar_one_or_none()
    if not latest_time:
        return {"timestamp": datetime.now(timezone.utc).isoformat(), "signals": [], "summary": _empty_summary(), "plan": plan}

    result = await db.execute(
        select(FRScanCache).where(FRScanCache.scan_time == latest_time)
    )
    scan_data = result.scalars().all()

    # Build signals
    config = settings.to_fr_config()
    min_vol = config["min_volume_24h"]
    allowed_strategies = limits["strategies"]

    signals = _build_signals(scan_data, config, min_vol, allowed_strategies, latest_time)
    signals = signals[:effective_limit]

    summary = {
        "total_signals": len(signals),
        "p1_count": sum(1 for s in signals if s["type"] == "p1_intra_cross"),
        "p2_count": sum(1 for s in signals if s["type"] == "p2_cross_exchange"),
        "p3_count": sum(1 for s in signals if s["type"] == "p3_single_leg"),
        "scan_time": latest_time.isoformat(),
    }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals": signals,
        "summary": summary,
        "plan": plan,
    }


def _build_signals(scan_data, config, min_vol, allowed_strategies, scan_time):
    """Build signal list from scan data (mirrors /scan/opportunities logic)."""
    base_map: dict[str, list] = {}
    for r in scan_data:
        if float(r.vol_24h or 0) < min_vol:
            continue
        base_map.setdefault(r.base, []).append(r)

    signals = []

    # P2: cross-exchange
    if "p2" in allowed_strategies and config["p2_cross_exchange"]["enabled"]:
        p2 = config["p2_cross_exchange"]
        for base, rates in base_map.items():
            if len(rates) < 2:
                continue
            sorted_rates = sorted(rates, key=lambda x: float(x.fr_rate or 0))
            lowest, highest = sorted_rates[0], sorted_rates[-1]
            diff = float(highest.fr_rate or 0) - float(lowest.fr_rate or 0)
            if diff >= p2["min_fr_diff"]:
                sig_id = _signal_id(base, "p2", lowest.exchange, highest.exchange, scan_time)
                net_income = round(diff * p2["amount_per_slot"] * config["leverage"] / 100, 2)
                signals.append({
                    "id": sig_id,
                    "type": "p2_cross_exchange",
                    "base": base,
                    "direction": f"LONG@{lowest.exchange} / SHORT@{highest.exchange}",
                    "exchanges": [lowest.exchange, highest.exchange],
                    "fr_diff": round(diff, 4),
                    "net_income": net_income,
                    "hold_settles": 1 if diff >= p2.get("breakeven_1x", 0.08) else 2,
                    "estimated_apy": round(diff * config["leverage"] * 365 * 3 / 100, 1),
                    "next_funding_secs": _next_funding_secs(rates),
                })

    # P3: single-leg
    if "p3" in allowed_strategies and config["p3_single_leg"]["enabled"]:
        p3 = config["p3_single_leg"]
        for base, rates in base_map.items():
            for r in rates:
                fr = float(r.fr_rate or 0)
                if abs(fr) >= p3["min_fr_rate"]:
                    side = "SHORT" if fr > 0 else "LONG"
                    sig_id = _signal_id(base, "p3", r.exchange, side, scan_time)
                    net_income = round((abs(fr) - 0.04) * p3["amount_per_slot"] * config["leverage"] / 100, 2)
                    signals.append({
                        "id": sig_id,
                        "type": "p3_single_leg",
                        "base": base,
                        "direction": f"{side}@{r.exchange}",
                        "exchanges": [r.exchange],
                        "fr_diff": round(abs(fr), 4),
                        "net_income": net_income,
                        "hold_settles": 1,
                        "estimated_apy": round(abs(fr) * config["leverage"] * 365 * 3 / 100, 1),
                        "next_funding_secs": _next_funding_secs([r]),
                    })

    signals.sort(key=lambda x: x["fr_diff"], reverse=True)
    return signals


def _signal_id(base, strategy, *args, scan_time=None):
    """Generate deterministic signal ID from content."""
    raw = f"{base}:{strategy}:{':'.join(str(a) for a in args)}:{scan_time}"
    return f"sig_{hashlib.md5(raw.encode()).hexdigest()[:12]}"


def _next_funding_secs(rates):
    """Estimate seconds until next funding from scan data."""
    for r in rates:
        nft = r.next_funding_time
        if nft and nft > 0:
            now_ts = datetime.now(timezone.utc).timestamp()
            # next_funding_time could be ms or s
            if nft > 1e12:
                nft = nft / 1000
            remaining = int(nft - now_ts)
            return max(0, remaining)
    return None


def _empty_summary():
    return {"total_signals": 0, "p1_count": 0, "p2_count": 0, "p3_count": 0, "scan_time": None}
