"""Per-user auto-entry and auto-close tasks.

Ported from fr_auto_runner.py to work with DB-backed state and per-user exchanges.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

from app.tasks import celery_app
from app.database import async_session
from app.models.settings import UserSettings
from app.models.position import Position
from app.models.trade_log import TradeLog
from app.models.fr_scan_cache import FRScanCache
from app.services.exchange_factory import create_user_exchanges
from app.services.notifier import notify_user

from sqlalchemy import select, func

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))
MAX_ENTRIES_PER_SCAN = 2


@celery_app.task(name="app.tasks.auto_trade_task.check_all_users_entry")
def check_all_users_entry():
    """Check auto-entry for all users with auto_enabled=True."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_check_entries())
    finally:
        loop.close()


@celery_app.task(name="app.tasks.auto_trade_task.check_all_users_close")
def check_all_users_close():
    """Check auto-close for all users with open positions."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_check_closes())
    finally:
        loop.close()


# ── Entry Logic ──

async def _check_entries():
    async with async_session() as db:
        result = await db.execute(
            select(UserSettings).where(UserSettings.auto_enabled.is_(True))
        )
        active_users = result.scalars().all()

    results = []
    for settings in active_users:
        try:
            r = await _auto_entry_for_user(settings.user_id, settings)
            results.append({"user_id": str(settings.user_id), "result": r})
        except Exception as e:
            logger.exception(f"Entry check failed for user {settings.user_id}")
            results.append({"user_id": str(settings.user_id), "error": str(e)})
    return results


async def _auto_entry_for_user(user_id, settings):
    """Evaluate opportunities and place orders for a single user."""
    async with async_session() as db:
        # Plan check: only Pro users can auto-trade
        from app.models.user import User
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or user.plan != "pro":
            return "plan_not_pro"

        # Safety: daily loss reset
        today = datetime.now(JST).strftime("%Y-%m-%d")
        if settings.daily_loss_date != today:
            settings.daily_loss_usd = 0
            settings.daily_loss_date = today
            db.add(settings)
            await db.commit()
            await db.refresh(settings)

        # Safety: daily loss limit
        if float(settings.daily_loss_usd) >= float(settings.max_daily_loss):
            settings.auto_enabled = False
            db.add(settings)
            await db.commit()
            return "daily_loss_limit_reached"

        # Count open positions
        result = await db.execute(
            select(func.count(Position.id)).where(
                Position.user_id == user_id,
                Position.status == "open",
            )
        )
        open_count = result.scalar() or 0
        if open_count >= settings.max_open_positions:
            return "max_positions_reached"

        # Get existing open bases (to avoid duplicates)
        result = await db.execute(
            select(Position.base).where(
                Position.user_id == user_id,
                Position.status == "open",
            )
        )
        open_bases = {row[0] for row in result.all()}

        # Get latest scan data
        result = await db.execute(
            select(FRScanCache.scan_time)
            .order_by(FRScanCache.scan_time.desc())
            .limit(1)
        )
        latest_time = result.scalar_one_or_none()
        if not latest_time:
            return "no_scan_data"

        # Check scan freshness (must be within 10 minutes)
        scan_age = (datetime.now(timezone.utc) - latest_time).total_seconds()
        if scan_age > 600:
            return "scan_data_stale"

        result = await db.execute(
            select(FRScanCache).where(FRScanCache.scan_time == latest_time)
        )
        scan_data = result.scalars().all()

        # Build opportunities (same logic as /api/scan/opportunities)
        config = settings.to_fr_config()
        min_vol = config["min_volume_24h"]
        opportunities = _evaluate_opportunities(scan_data, config, min_vol)

        if not opportunities:
            return "no_opportunities"

        # Get user's exchanges
        exchanges = await create_user_exchanges(user_id, db)
        entered = 0
        entry_results = []

        for opp in opportunities:
            if entered >= MAX_ENTRIES_PER_SCAN:
                break
            if open_count + entered >= settings.max_open_positions:
                break

            # Skip duplicate base
            if opp["base"] in open_bases:
                continue

            # Min net income check
            if opp["net_income"] < 0.10:
                continue

            try:
                if opp["type"] == "cross_exchange":
                    r = await _enter_cross_exchange(user_id, opp, exchanges, config, db)
                elif opp["type"] == "single_leg":
                    r = await _enter_single_leg(user_id, opp, exchanges, config, db)
                else:
                    continue

                if r:
                    entered += 1
                    open_bases.add(opp["base"])
                    entry_results.append(r)
            except Exception as e:
                logger.exception(f"Entry failed for {opp['base']}: {e}")
                db.add(TradeLog(
                    user_id=user_id,
                    action="error",
                    type=opp["type"],
                    base=opp["base"],
                    details={"error": str(e)},
                ))
                await db.commit()

        return {"entered": entered, "details": entry_results}


def _evaluate_opportunities(scan_data, config, min_vol):
    """Build opportunities from scan data (mirrors /api/scan/opportunities logic)."""
    base_map: dict[str, list] = {}
    for r in scan_data:
        if float(r.vol_24h or 0) < min_vol:
            continue
        base_map.setdefault(r.base, []).append(r)

    opportunities = []

    # P2: cross-exchange
    if config["p2_cross_exchange"]["enabled"]:
        p2 = config["p2_cross_exchange"]
        for base, rates in base_map.items():
            if len(rates) < 2:
                continue
            sorted_rates = sorted(rates, key=lambda x: float(x.fr_rate or 0))
            lowest = sorted_rates[0]
            highest = sorted_rates[-1]
            diff = float(highest.fr_rate or 0) - float(lowest.fr_rate or 0)
            if diff >= p2["min_fr_diff"]:
                net_income = round(diff * p2["amount_per_slot"] * config["leverage"] / 100, 2)
                hold_settles = 1 if diff >= p2.get("breakeven_1x", 0.08) else 2
                opportunities.append({
                    "type": "cross_exchange",
                    "base": base,
                    "long_exchange": lowest.exchange,
                    "short_exchange": highest.exchange,
                    "net_fr": diff,
                    "net_income": net_income,
                    "hold_settles": hold_settles,
                    "amount": p2["amount_per_slot"],
                })

    # P3: single-leg
    if config["p3_single_leg"]["enabled"]:
        p3 = config["p3_single_leg"]
        for base, rates in base_map.items():
            for r in rates:
                fr = float(r.fr_rate or 0)
                if abs(fr) >= p3["min_fr_rate"]:
                    side = "short" if fr > 0 else "long"
                    net_income = round((abs(fr) - 0.04) * p3["amount_per_slot"] * config["leverage"] / 100, 2)
                    opportunities.append({
                        "type": "single_leg",
                        "base": base,
                        "exchange": r.exchange,
                        "side": side,
                        "fr_rate": fr,
                        "net_income": net_income,
                        "hold_settles": 1,
                        "amount": p3["amount_per_slot"],
                    })

    # Sort by net_income descending
    opportunities.sort(key=lambda x: x["net_income"], reverse=True)
    return opportunities


async def _enter_cross_exchange(user_id, opp, exchanges, config, db):
    """Execute P2 cross-exchange entry with rollback on failure."""
    long_ex = exchanges.get(opp["long_exchange"])
    short_ex = exchanges.get(opp["short_exchange"])

    if not long_ex or not short_ex:
        return None
    if not long_ex.can_trade_api or not short_ex.can_trade_api:
        return None

    base = opp["base"]
    amount = min(opp["amount"], float(config.get("max_per_trade_usd", 1500)))
    leg = amount / 2
    lev = config["leverage"]

    # Long side
    r1 = long_ex.place_market_order(base, "BUY", leg, lev)
    if not r1.get("ok"):
        logger.warning(f"Long entry failed for {base} on {opp['long_exchange']}: {r1.get('error')}")
        return None

    time.sleep(1)

    # Short side
    r2 = short_ex.place_market_order(base, "SELL", leg, lev)
    if not r2.get("ok"):
        # Rollback long side
        long_ex.close_position(base, "LONG")
        logger.warning(f"Short entry failed for {base}, rolled back long")
        return None

    # Record position
    position = Position(
        user_id=user_id,
        type="cross_exchange",
        base=base,
        legs={
            "long_exchange": opp["long_exchange"],
            "short_exchange": opp["short_exchange"],
            "long_order_id": r1.get("order_id"),
            "short_order_id": r2.get("order_id"),
        },
        amount_usd=amount,
        leverage=lev,
        net_fr=opp["net_fr"],
        expected_income=opp["net_income"],
        hold_settles=opp["hold_settles"],
        settles_received=0,
        status="open",
    )
    db.add(position)

    db.add(TradeLog(
        user_id=user_id,
        action="entry",
        type="cross_exchange",
        base=base,
        exchange=f"{opp['long_exchange']}/{opp['short_exchange']}",
        details={
            "amount": amount,
            "leverage": lev,
            "net_fr": opp["net_fr"],
            "net_income": opp["net_income"],
            "long_order_id": r1.get("order_id"),
            "short_order_id": r2.get("order_id"),
        },
    ))
    await db.commit()

    # Load settings for notification
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if user_settings:
        await notify_user(user_settings, "entry_opened",
            f"{base} Cross Entry\n"
            f"Long: {opp['long_exchange']} / Short: {opp['short_exchange']}\n"
            f"FR diff: {opp['net_fr']:+.4f}% Est: ${opp['net_income']:.2f}\n"
            f"Amount: ${amount:.0f}")

    return {
        "base": base,
        "type": "cross_exchange",
        "long": opp["long_exchange"],
        "short": opp["short_exchange"],
        "amount": amount,
        "net_income": opp["net_income"],
    }


async def _enter_single_leg(user_id, opp, exchanges, config, db):
    """Execute P3 single-leg entry."""
    ex = exchanges.get(opp["exchange"])
    if not ex or not ex.can_trade_api:
        return None

    base = opp["base"]
    amount = min(opp["amount"], float(config.get("max_per_trade_usd", 1500)))
    lev = config["leverage"]
    side_api = "SELL" if opp["side"] == "short" else "BUY"

    r = ex.place_market_order(base, side_api, amount, lev)
    if not r.get("ok"):
        logger.warning(f"Single-leg entry failed for {base} on {opp['exchange']}: {r.get('error')}")
        return None

    position = Position(
        user_id=user_id,
        type="single_leg",
        base=base,
        legs={
            "exchange": opp["exchange"],
            "side": opp["side"],
            "order_id": r.get("order_id"),
        },
        amount_usd=amount,
        leverage=lev,
        fr_rate=opp["fr_rate"],
        expected_income=opp["net_income"],
        hold_settles=opp["hold_settles"],
        settles_received=0,
        status="open",
    )
    db.add(position)

    db.add(TradeLog(
        user_id=user_id,
        action="entry",
        type="single_leg",
        base=base,
        exchange=opp["exchange"],
        details={
            "side": opp["side"],
            "amount": amount,
            "leverage": lev,
            "fr_rate": opp["fr_rate"],
            "net_income": opp["net_income"],
            "order_id": r.get("order_id"),
        },
    ))
    await db.commit()

    # Notify
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if user_settings:
        await notify_user(user_settings, "entry_opened",
            f"{base} Single-leg {opp['side'].upper()} on {opp['exchange']}\n"
            f"FR: {opp['fr_rate']:+.4f}% Est: ${opp['net_income']:.2f}\n"
            f"Amount: ${amount:.0f}")

    return {
        "base": base,
        "type": "single_leg",
        "exchange": opp["exchange"],
        "side": opp["side"],
        "amount": amount,
        "net_income": opp["net_income"],
    }


# ── Close Logic ──

async def _check_closes():
    """Check all open positions for close conditions."""
    async with async_session() as db:
        result = await db.execute(
            select(Position).where(Position.status == "open")
        )
        open_positions = result.scalars().all()

    if not open_positions:
        return "no_open_positions"

    # Group by user_id for exchange caching
    user_positions: dict[str, list[Position]] = {}
    for pos in open_positions:
        uid = str(pos.user_id)
        user_positions.setdefault(uid, []).append(pos)

    results = []
    for uid_str, positions in user_positions.items():
        try:
            r = await _close_positions_for_user(positions)
            results.extend(r)
        except Exception as e:
            logger.exception(f"Close check failed for user {uid_str}")
            results.append({"user_id": uid_str, "error": str(e)})

    return results


async def _close_positions_for_user(positions: list[Position]):
    """Check and execute close for a user's open positions."""
    if not positions:
        return []

    user_id = positions[0].user_id
    results = []

    async with async_session() as db:
        # Load user settings for close timing config
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            return [{"user_id": str(user_id), "error": "no_settings"}]

        exit_after_mins = 10  # Default from shared_config
        max_hold_settles = 3

        exchanges = await create_user_exchanges(user_id, db)

        for pos in positions:
            try:
                r = await _check_and_close_position(pos, settings, exchanges, exit_after_mins, max_hold_settles, db)
                results.append(r)
            except Exception as e:
                logger.exception(f"Close failed for position {pos.id}")
                results.append({"position_id": str(pos.id), "error": str(e)})

    return results


async def _check_and_close_position(pos, settings, exchanges, exit_after_mins, max_hold_settles, db):
    """Check close conditions for a single position and execute if met."""
    opened_at = pos.opened_at
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)

    elapsed_h = (datetime.now(timezone.utc) - opened_at).total_seconds() / 3600

    # Count FR settlements (every 8 hours)
    settles = int(elapsed_h / 8)
    target_settles = pos.hold_settles or 1
    exit_after_h = exit_after_mins / 60

    # Determine if we should close
    should_close = False
    reason = ""

    if settles >= target_settles and elapsed_h >= target_settles * 8 + exit_after_h:
        should_close = True
        reason = f"FR {settles}x received ({elapsed_h:.1f}h held)"
    elif settles >= max_hold_settles:
        should_close = True
        reason = f"max hold {max_hold_settles}x reached ({elapsed_h:.1f}h)"
    elif elapsed_h >= max_hold_settles * 8 + 1:
        should_close = True
        reason = f"max hold time exceeded ({elapsed_h:.1f}h)"

    if not should_close:
        # Update settles_received
        if pos.settles_received != settles:
            pos.settles_received = settles
            db.add(pos)
            await db.commit()
        return {
            "position_id": str(pos.id),
            "status": "holding",
            "settles": f"{settles}/{target_settles}",
            "elapsed_h": round(elapsed_h, 1),
        }

    # Execute close
    close_results = {}

    if pos.type == "cross_exchange":
        long_ex_name = pos.legs.get("long_exchange")
        short_ex_name = pos.legs.get("short_exchange")
        long_ex = exchanges.get(long_ex_name)
        short_ex = exchanges.get(short_ex_name)

        if long_ex and long_ex.can_trade_api:
            r1 = long_ex.close_position(pos.base, "LONG")
            close_results["long"] = "ok" if r1.get("ok") else r1.get("error", "failed")
        else:
            close_results["long"] = "exchange_unavailable"

        time.sleep(1)

        if short_ex and short_ex.can_trade_api:
            r2 = short_ex.close_position(pos.base, "SHORT")
            close_results["short"] = "ok" if r2.get("ok") else r2.get("error", "failed")
        else:
            close_results["short"] = "exchange_unavailable"

    elif pos.type == "single_leg":
        ex_name = pos.legs.get("exchange")
        ex = exchanges.get(ex_name)
        pos_side = "SHORT" if pos.legs.get("side") == "short" else "LONG"

        if ex and ex.can_trade_api:
            r = ex.close_position(pos.base, pos_side)
            close_results["close"] = "ok" if r.get("ok") else r.get("error", "failed")
        else:
            close_results["close"] = "exchange_unavailable"

    # Update position
    pos.status = "closed"
    pos.closed_at = datetime.now(timezone.utc)
    pos.close_reason = reason
    pos.settles_received = settles
    db.add(pos)

    # Track daily loss if expected_income was negative
    expected = float(pos.expected_income or 0)
    if expected < 0:
        today = datetime.now(JST).strftime("%Y-%m-%d")
        if settings.daily_loss_date != today:
            settings.daily_loss_usd = 0
            settings.daily_loss_date = today
        settings.daily_loss_usd = float(settings.daily_loss_usd or 0) + abs(expected)
        db.add(settings)

    # Log trade
    db.add(TradeLog(
        user_id=pos.user_id,
        action="close",
        type=pos.type,
        base=pos.base,
        exchange=pos.legs.get("exchange") or f"{pos.legs.get('long_exchange')}/{pos.legs.get('short_exchange')}",
        details={
            "reason": reason,
            "settles": settles,
            "elapsed_h": round(elapsed_h, 1),
            "close_results": close_results,
        },
    ))

    await db.commit()

    # Notify user
    exchange_str = pos.legs.get("exchange") or f"{pos.legs.get('long_exchange')}/{pos.legs.get('short_exchange')}"
    await notify_user(settings, "position_closed",
        f"{pos.base} {pos.type} closed ({reason})\n"
        f"Exchange: {exchange_str}\n"
        f"FR settles: {settles}x / Held: {elapsed_h:.1f}h")

    return {
        "position_id": str(pos.id),
        "status": "closed",
        "reason": reason,
        "settles": settles,
        "close_results": close_results,
    }
