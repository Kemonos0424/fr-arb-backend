"""Create per-user exchange instances with decrypted API keys."""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ExchangeApiKey
from app.services.crypto import decrypt


async def create_user_exchanges(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Build exchange instances for a user using their encrypted API keys.

    Returns dict of {exchange_name: ExchangeInstance}.
    Read-only exchanges (MEXC, Bybit, Phemex) are always included.
    """
    # Import here to avoid circular deps and allow exchanges/ to be a standalone package
    from exchanges.bingx import BingXExchange
    from exchanges.bitget import BitgetExchange
    from exchanges.bitmart import BitMartExchange
    from exchanges.bybit import BybitExchange
    from exchanges.mexc import MEXCExchange
    from exchanges.phemex import PhemexExchange

    result = await db.execute(
        select(ExchangeApiKey).where(
            ExchangeApiKey.user_id == user_id,
            ExchangeApiKey.is_valid.is_(True),
        )
    )
    key_rows = result.scalars().all()

    exchanges = {}
    for row in key_rows:
        api_key = decrypt(row.api_key_enc)
        secret = decrypt(row.secret_enc)

        if row.exchange == "bingx":
            exchanges["bingx"] = BingXExchange(api_key=api_key, secret_key=secret)
        elif row.exchange == "bitget":
            passphrase = decrypt(row.passphrase_enc) if row.passphrase_enc else ""
            exchanges["bitget"] = BitgetExchange(api_key=api_key, secret_key=secret, passphrase=passphrase)
        elif row.exchange == "bitmart":
            memo = decrypt(row.memo_enc) if row.memo_enc else ""
            exchanges["bitmart"] = BitMartExchange(api_key=api_key, secret_key=secret, memo=memo)

    # Always add read-only exchanges
    for ExClass in [BybitExchange, MEXCExchange, PhemexExchange]:
        ex = ExClass()
        exchanges[ex.name] = ex

    return exchanges
