"""Bitget Exchange Module - constructor-based credentials."""
import requests
import time
import hashlib
import hmac
import base64
import json
from exchanges.base import ExchangeBase

BASE_URL = "https://api.bitget.com"


class BitgetExchange(ExchangeBase):
    name = "bitget"
    display_name = "Bitget"
    can_trade_api = True
    maker_fee = 0.0002
    taker_fee = 0.0006

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, passphrase: str | None = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    def _sign(self, timestamp, method, path, body=""):
        message = f"{timestamp}{method}{path}{body}"
        mac = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _ts(self):
        return str(int(time.time() * 1000))

    def _auth_headers(self, method, path, body=""):
        ts = self._ts()
        sig = self._sign(ts, method, path, body)
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sig,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase or "",
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    def format_symbol(self, base, quote="USDT"):
        return f"{base}{quote}"

    def get_funding_rate(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/current-fund-rate",
                params={"symbol": symbol, "productType": "USDT-FUTURES"}, timeout=8).json()
            if r.get("code") == "00000":
                d = r.get("data", [{}])[0]
                return {
                    "base": base,
                    "fr_rate": float(d.get("fundingRate", 0)) * 100,
                    "next_funding_time": int(d.get("nextUpdate", 0) or 0),
                    "mark_price": float(d.get("markPrice", 0) or 0),
                }
        except Exception:
            pass
        return None

    def get_all_funding_rates(self):
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/tickers",
                params={"productType": "USDT-FUTURES"}, timeout=10).json()
            if r.get("code") != "00000":
                return []

            fr_r = requests.get(f"{BASE_URL}/api/v2/mix/market/current-fund-rate",
                params={"productType": "USDT-FUTURES"}, timeout=10).json()
            fr_map = {}
            if fr_r.get("code") == "00000":
                for d in fr_r.get("data", []):
                    sym = d.get("symbol", "")
                    fr_map[sym] = {
                        "fr_rate": float(d.get("fundingRate", 0)) * 100,
                        "next_funding_time": int(d.get("nextUpdate", 0) or 0),
                    }

            results = []
            for item in r.get("data", []):
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                base = symbol.replace("USDT", "")
                fr_info = fr_map.get(symbol, {})
                results.append({
                    "base": base, "symbol": symbol,
                    "fr_rate": fr_info.get("fr_rate", 0),
                    "abs_fr": abs(fr_info.get("fr_rate", 0)),
                    "next_funding_time": fr_info.get("next_funding_time", 0),
                    "mark_price": float(item.get("markPrice", 0) or 0),
                    "vol_24h": float(item.get("quoteVolume", 0) or 0),
                })
            return results
        except Exception:
            return []

    def get_ticker(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/ticker",
                params={"symbol": symbol, "productType": "USDT-FUTURES"}, timeout=8).json()
            if r.get("code") == "00000":
                d = r.get("data", [{}])[0]
                return {
                    "base": base,
                    "last_price": float(d.get("lastPr", 0) or 0),
                    "volume_24h": float(d.get("quoteVolume", 0) or 0),
                }
        except Exception:
            pass
        return None

    def get_order_book(self, base, quote="USDT", limit=20):
        symbol = self.format_symbol(base, quote)
        try:
            r = requests.get(f"{BASE_URL}/api/v2/mix/market/merge-depth",
                params={"symbol": symbol, "productType": "USDT-FUTURES", "limit": str(limit)},
                timeout=8).json()
            if r.get("code") == "00000":
                d = r.get("data", {})
                return {"asks": d.get("asks", []), "bids": d.get("bids", [])}
        except Exception:
            pass
        return None

    # Trading API
    def get_balance(self):
        if not self.api_key:
            return {"error": "API key not configured"}
        path = "/api/v2/mix/account/accounts?productType=USDT-FUTURES"
        headers = self._auth_headers("GET", path)
        try:
            r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=10).json()
            if r.get("code") == "00000":
                for acc in r.get("data", []):
                    if acc.get("marginCoin") == "USDT":
                        return {
                            "balance": float(acc.get("usdtEquity", 0) or 0),
                            "available": float(acc.get("crossMaxAvailable", 0) or 0),
                            "equity": float(acc.get("accountEquity", 0) or 0),
                        }
            return {"error": r.get("msg", str(r))}
        except Exception as e:
            return {"error": str(e)}

    def get_positions(self):
        if not self.api_key:
            return []
        path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES"
        headers = self._auth_headers("GET", path)
        try:
            r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=10).json()
            if r.get("code") == "00000":
                return r.get("data", [])
        except Exception:
            pass
        return []

    def place_market_order(self, base, side, amount_usdt, leverage=20):
        if not self.api_key:
            return {"ok": False, "error": "API key not configured"}
        symbol = self.format_symbol(base)
        self.set_leverage(base, leverage)

        ticker = self.get_ticker(base)
        price = ticker['last_price'] if ticker else 0
        if price <= 0:
            return {"ok": False, "error": "price unavailable"}
        size = str(round(amount_usdt * leverage / price, 6))

        path = "/api/v2/mix/order/place-order"
        body = json.dumps({
            "symbol": symbol, "productType": "USDT-FUTURES",
            "marginMode": "crossed", "marginCoin": "USDT",
            "side": "buy" if side == "BUY" else "sell",
            "orderType": "market", "size": size,
        })
        headers = self._auth_headers("POST", path, body)
        try:
            r = requests.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=10).json()
            if r.get("code") == "00000":
                return {"ok": True, "order_id": r.get("data", {}).get("orderId")}
            return {"ok": False, "error": r.get("msg", str(r))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close_position(self, base, position_side="LONG"):
        if not self.api_key:
            return {"ok": False, "error": "API key not configured"}
        symbol = self.format_symbol(base)
        side = "sell" if position_side == "LONG" else "buy"
        path = "/api/v2/mix/order/place-order"
        body = json.dumps({
            "symbol": symbol, "productType": "USDT-FUTURES",
            "marginMode": "crossed", "marginCoin": "USDT",
            "side": side, "orderType": "market", "size": "0", "reduceOnly": "YES",
        })
        headers = self._auth_headers("POST", path, body)
        try:
            r = requests.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=10).json()
            if r.get("code") == "00000":
                return {"ok": True, "order_id": r.get("data", {}).get("orderId")}
            return {"ok": False, "error": r.get("msg", str(r))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_leverage(self, base, leverage):
        if not self.api_key:
            return False
        symbol = self.format_symbol(base)
        path = "/api/v2/mix/account/set-leverage"
        body = json.dumps({
            "symbol": symbol, "productType": "USDT-FUTURES",
            "marginCoin": "USDT", "leverage": str(leverage),
        })
        headers = self._auth_headers("POST", path, body)
        try:
            r = requests.post(f"{BASE_URL}{path}", data=body, headers=headers, timeout=10).json()
            return r.get("code") == "00000"
        except Exception:
            return False
