"""BingX Exchange Module - constructor-based credentials."""
import time
import hashlib
import hmac
import requests
from urllib.parse import urlencode
from exchanges.base import ExchangeBase

BINGX_BASE = "https://open-api.bingx.com"


class BingXExchange(ExchangeBase):
    name = "bingx"
    display_name = "BingX"
    can_trade_api = True
    maker_fee = 0.0002
    taker_fee = 0.0005

    def __init__(self, api_key: str | None = None, secret_key: str | None = None):
        self.api_key = api_key
        self.secret_key = secret_key

    def _sign(self, params: dict) -> str:
        if not self.secret_key:
            raise ValueError("BingX secret_key not configured")
        query = urlencode(sorted(params.items()))
        return hmac.new(self.secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _auth_get(self, path: str, params: dict = None) -> dict:
        params = params or {}
        params["timestamp"] = str(int(time.time() * 1000))
        params["signature"] = self._sign(params)
        headers = {"X-BX-APIKEY": self.api_key}
        r = requests.get(f"{BINGX_BASE}{path}", params=params, headers=headers, timeout=10)
        return r.json()

    def _auth_post(self, path: str, params: dict = None) -> dict:
        params = params or {}
        params["timestamp"] = str(int(time.time() * 1000))
        params["signature"] = self._sign(params)
        headers = {"X-BX-APIKEY": self.api_key}
        r = requests.post(f"{BINGX_BASE}{path}", params=params, headers=headers, timeout=10)
        return r.json()

    def format_symbol(self, base, quote="USDT"):
        return f"{base}-{quote}"

    def get_funding_rate(self, base):
        try:
            r = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/premiumIndex",
                params={"symbol": self.format_symbol(base)}, timeout=8).json()
            if r.get("code") == 0:
                d = r.get("data", {})
                return {
                    "base": base,
                    "fr_rate": float(d.get("lastFundingRate", 0)) * 100,
                    "next_funding_time": int(d.get("nextFundingTime", 0)),
                    "mark_price": float(d.get("markPrice", 0)),
                }
        except Exception:
            pass
        return None

    def get_all_funding_rates(self):
        try:
            r = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/premiumIndex", timeout=10).json()
            results = []
            for d in r.get("data", []):
                symbol = d.get("symbol", "")
                if not symbol.endswith("-USDT"):
                    continue
                base = symbol.replace("-USDT", "")
                fr = float(d.get("lastFundingRate", 0)) * 100
                results.append({
                    "base": base, "symbol": symbol,
                    "fr_rate": fr, "abs_fr": abs(fr),
                    "next_funding_time": int(d.get("nextFundingTime", 0)),
                    "mark_price": float(d.get("markPrice", 0)),
                    "vol_24h": 0,  # Omit per-symbol ticker call for speed
                })
            return results
        except Exception:
            return []

    def get_ticker(self, base):
        try:
            r = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/ticker",
                params={"symbol": self.format_symbol(base)}, timeout=8).json()
            if r.get("code") == 0:
                d = r.get("data", {})
                return {
                    "base": base,
                    "last_price": float(d.get("lastPrice", 0)),
                    "volume_24h": float(d.get("quoteVolume", 0)),
                }
        except Exception:
            pass
        return None

    def get_order_book(self, base, quote="USDT", limit=20):
        try:
            r = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/depth",
                params={"symbol": f"{base}-{quote}", "limit": limit}, timeout=8).json()
            if r.get("code") == 0:
                return {"asks": r["data"].get("asks", []), "bids": r["data"].get("bids", [])}
        except Exception:
            pass
        return None

    def get_all_usdc_funding_rates(self):
        try:
            r = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/premiumIndex", timeout=10).json()
            results = []
            for d in r.get("data", []):
                symbol = d.get("symbol", "")
                if not symbol.endswith("-USDC"):
                    continue
                base = symbol.replace("-USDC", "")
                fr = float(d.get("lastFundingRate", 0)) * 100
                results.append({
                    "base": base, "symbol": symbol, "quote": "USDC",
                    "fr_rate": fr, "abs_fr": abs(fr),
                    "next_funding_time": int(d.get("nextFundingTime", 0)),
                    "mark_price": float(d.get("markPrice", 0)),
                    "vol_24h": 0,
                })
            return results
        except Exception:
            return []

    # Trading API
    def get_balance(self):
        try:
            r = self._auth_get("/openApi/swap/v2/user/balance")
            if r.get("code") == 0:
                bal = r.get("data", {}).get("balance", {})
                return {
                    "balance": float(bal.get("balance", 0)),
                    "available": float(bal.get("availableMargin", 0)),
                    "equity": float(bal.get("equity", 0)),
                }
            return {"error": r.get("msg", str(r))}
        except Exception as e:
            return {"error": str(e)}

    def get_positions(self):
        try:
            r = self._auth_get("/openApi/swap/v2/user/positions")
            if r.get("code") == 0:
                return r.get("data", [])
            return []
        except Exception:
            return []

    def place_market_order(self, base, side, amount_usdt, leverage=20):
        symbol = self.format_symbol(base)
        self.set_leverage(base, leverage)
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quoteOrderQty": str(amount_usdt * leverage),
        }
        try:
            r = self._auth_post("/openApi/swap/v2/trade/order", params)
            if r.get("code") == 0:
                return {"ok": True, "order_id": r.get("data", {}).get("order", {}).get("orderId")}
            return {"ok": False, "error": r.get("msg", str(r))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close_position(self, base, position_side="LONG"):
        symbol = self.format_symbol(base)
        side = "SELL" if position_side == "LONG" else "BUY"
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quoteOrderQty": "0",
            "reduceOnly": "true",
        }
        try:
            r = self._auth_post("/openApi/swap/v2/trade/order", params)
            if r.get("code") == 0:
                return {"ok": True, "order_id": r.get("data", {}).get("order", {}).get("orderId")}
            return {"ok": False, "error": r.get("msg", str(r))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_leverage(self, base, leverage):
        symbol = self.format_symbol(base)
        try:
            r = self._auth_post("/openApi/swap/v2/trade/leverage", {
                "symbol": symbol, "side": "BOTH", "leverage": str(leverage),
            })
            return r.get("code") == 0
        except Exception:
            return False
