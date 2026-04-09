"""Exchange Registry - multi-user version (credentials via constructor)."""
from exchanges.bingx import BingXExchange
from exchanges.mexc import MEXCExchange
from exchanges.bybit import BybitExchange
from exchanges.bitget import BitgetExchange
from exchanges.bitmart import BitMartExchange
from exchanges.phemex import PhemexExchange


def get_all_exchanges():
    """Return read-only exchange instances (no credentials needed for FR scanning)."""
    return [
        BingXExchange(),
        BitgetExchange(),
        BitMartExchange(),
        PhemexExchange(),
        BybitExchange(),
        MEXCExchange(),
    ]


def get_scan_exchanges():
    return get_all_exchanges()


def get_trade_exchanges():
    return [ex for ex in get_all_exchanges() if ex.can_trade_api]
