"""FR scan endpoints."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.fr_scan_cache import FRScanCache
from app.models.settings import UserSettings
from app.core.deps import get_current_user
from app.schemas.scan import FRScanResult

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.get("/latest", response_model=list[FRScanResult])
async def get_latest_scan(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest cached FR scan results."""
    # Find the most recent scan_time
    result = await db.execute(
        select(FRScanCache.scan_time)
        .order_by(FRScanCache.scan_time.desc())
        .limit(1)
    )
    latest_time = result.scalar_one_or_none()
    if not latest_time:
        return []

    result = await db.execute(
        select(FRScanCache)
        .where(FRScanCache.scan_time == latest_time)
        .order_by(FRScanCache.abs_fr.desc())
    )
    return result.scalars().all()


@router.post("/trigger")
async def trigger_scan(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an on-demand FR scan. Results cached in DB and returned."""
    from exchanges import get_all_exchanges
    from concurrent.futures import ThreadPoolExecutor, as_completed

    scan_time = datetime.now(timezone.utc)
    all_exchanges = get_all_exchanges()
    all_results = []

    def fetch_fr(ex):
        try:
            return ex.name, ex.get_all_funding_rates()
        except Exception:
            return ex.name, []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_fr, ex): ex for ex in all_exchanges}
        for future in as_completed(futures, timeout=60):
            name, rates = future.result()
            for r in rates:
                entry = FRScanCache(
                    scan_time=scan_time,
                    exchange=name,
                    base=r.get("base", ""),
                    quote="USDT",
                    fr_rate=r.get("fr_rate", 0),
                    abs_fr=r.get("abs_fr", 0),
                    vol_24h=r.get("vol_24h", 0),
                    mark_price=r.get("mark_price", 0),
                    next_funding_time=r.get("next_funding_time", 0),
                )
                db.add(entry)
                all_results.append(entry)

    await db.commit()
    return {"scan_time": scan_time.isoformat(), "count": len(all_results)}


@router.get("/opportunities")
async def get_opportunities(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate opportunities based on user's strategy settings."""
    # Get user settings
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    settings = result.scalar_one_or_none()
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    # Get latest scan
    result = await db.execute(
        select(FRScanCache.scan_time)
        .order_by(FRScanCache.scan_time.desc())
        .limit(1)
    )
    latest_time = result.scalar_one_or_none()
    if not latest_time:
        return []

    result = await db.execute(
        select(FRScanCache).where(FRScanCache.scan_time == latest_time)
    )
    scan_data = result.scalars().all()

    # Build matrix: base -> exchange -> fr_rate
    config = settings.to_fr_config()
    min_vol = config["min_volume_24h"]
    opportunities = []

    # Group by base
    base_map: dict[str, list] = {}
    for r in scan_data:
        if float(r.vol_24h or 0) < min_vol:
            continue
        base_map.setdefault(r.base, []).append(r)

    # P2: cross-exchange - find max FR difference per base
    if config["p2_cross_exchange"]["enabled"]:
        p2_cfg = config["p2_cross_exchange"]
        for base, rates in base_map.items():
            if len(rates) < 2:
                continue
            sorted_rates = sorted(rates, key=lambda x: float(x.fr_rate or 0))
            lowest = sorted_rates[0]
            highest = sorted_rates[-1]
            diff = float(highest.fr_rate or 0) - float(lowest.fr_rate or 0)
            if diff >= p2_cfg["min_fr_diff"]:
                opportunities.append({
                    "type": "p2_cross_exchange",
                    "base": base,
                    "direction": f"LONG@{lowest.exchange} / SHORT@{highest.exchange}",
                    "exchanges": [lowest.exchange, highest.exchange],
                    "fr_diff": round(diff, 4),
                    "net_income": round(diff * p2_cfg["amount_per_slot"] * config["leverage"] / 100, 2),
                    "hold_settles": 1 if diff >= p2_cfg.get("breakeven_1x", 0.08) else 2,
                })

    # P3: single-leg - find highest |FR| per base
    if config["p3_single_leg"]["enabled"]:
        p3_cfg = config["p3_single_leg"]
        for base, rates in base_map.items():
            for r in rates:
                fr = float(r.fr_rate or 0)
                if abs(fr) >= p3_cfg["min_fr_rate"]:
                    side = "SHORT" if fr > 0 else "LONG"
                    opportunities.append({
                        "type": "p3_single_leg",
                        "base": base,
                        "direction": f"{side}@{r.exchange}",
                        "exchanges": [r.exchange],
                        "fr_diff": round(abs(fr), 4),
                        "net_income": round((abs(fr) - 0.04) * p3_cfg["amount_per_slot"] * config["leverage"] / 100, 2),
                        "hold_settles": 1,
                    })

    opportunities.sort(key=lambda x: x["fr_diff"], reverse=True)
    return opportunities
