"""Global FR scan task - runs once, results shared by all users."""
import asyncio
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.tasks import celery_app
from app.database import async_session
from app.models.fr_scan_cache import FRScanCache


@celery_app.task(name="app.tasks.scan_task.global_fr_scan")
def global_fr_scan():
    """Fetch FR rates from all exchanges, cache in DB."""
    return asyncio.get_event_loop().run_until_complete(_do_scan())


async def _do_scan():
    from exchanges import get_all_exchanges

    scan_time = datetime.now(timezone.utc)
    all_exchanges = get_all_exchanges()
    count = 0

    def fetch_fr(ex):
        try:
            return ex.name, ex.get_all_funding_rates()
        except Exception:
            return ex.name, []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_fr, ex): ex for ex in all_exchanges}
        results = []
        for future in as_completed(futures, timeout=120):
            name, rates = future.result()
            for r in rates:
                results.append(FRScanCache(
                    scan_time=scan_time,
                    exchange=name,
                    base=r.get("base", ""),
                    quote="USDT",
                    fr_rate=r.get("fr_rate", 0),
                    abs_fr=r.get("abs_fr", 0),
                    vol_24h=r.get("vol_24h", 0),
                    mark_price=r.get("mark_price", 0),
                    next_funding_time=r.get("next_funding_time", 0),
                ))

    async with async_session() as db:
        db.add_all(results)
        await db.commit()
        count = len(results)

    return {"scan_time": scan_time.isoformat(), "count": count}
