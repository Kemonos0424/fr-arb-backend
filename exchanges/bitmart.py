"""BitMart Exchange Module - constructor-based credentials."""
import requests
import time
import hashlib
import hmac
import json
from exchanges.base import ExchangeBase

BASE_URL = "https://api-cloud-v2.bitmart.com"


class BitMartExchange(ExchangeBase):
    name = "bitmart"
    display_name = "BitMart"
    can_trade_api = True
    maker_fee = 0.0002
    taker_fee = 0.0006

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, memo: str | None = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.memo = memo or ""

    def _sign(self, ts, body=""):
        sign_str = f"{ts}#{self.memo}#{body}"
        return hmac.new(self.secret_key.encode(), sign_str.encode(), hashlib.sha256).hexdigest()

    def _ts(self):
        return str(int(time.time() * 1000))

    def _auth_headers(self, body=""):
        ts = self._ts()
        return {
            "X-BM-KEY": self.api_key,
            "X-BM-SIGN": self._sign(ts, body),
            "X-BM-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }

    def _get_auth(self, path):
        ts = self._ts()
        sig = hmac.new(self.secret_key.encode(), f"{ts}#{self.memo}#".encode(), hashlib.sha256).hexdigest()
        headers = {"X-BM-KEY": self.api_key, "X-BM-SIGN": sig, "X-BM-TIMESTAMP": ts, "Content-Type": "application/json"}
        try:
            return requests.get(f"{BASE_URL}{path}", headers=headers, timeout=10).json()
        except Exception:
            return {}

    def format_symbol(self, base, quote="USDT"):
        return f"{base}{quote}"

    def get_funding_rate(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/contract/public/funding-rate",
                params={"symbol": symbol}, timeout=8).json()
            if r.get("code") == 1000:
                d = r.get("data", {})
                return {
                    "base": base,
                    "fr_rate": float(d.get("rate_value", 0)) * 100,
                    "next_funding_time": int(d.get("funding_time", 0)),
                    "mark_price": 0,
                }
        except Exception:
            pass
        return None

    def get_all_funding_rates(self):
        try:
            r = requests.get(f"{BASE_URL}/contract/public/details", timeout=10).json()
            results = []
            for item in r.get("data", {}).get("symbols", []):
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                base = symbol.replace("USDT", "")
                fr = float(item.get("funding_rate", 0)) * 100
                turnover = float(item.get("turnover_24h", 0) or 0)
                results.append({
                    "base": base, "symbol": symbol,
                    "fr_rate": fr, "abs_fr": abs(fr),
                    "next_funding_time": int(item.get("funding_time", 0)),
                    "mark_price": float(item.get("last_price", 0) or 0),
                    "vol_24h": turnover,
                })
            return results
        except Exception:
            return []

    def get_ticker(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/contract/public/details", timeout=10).json()
            for item in r.get("data", {}).get("symbols", []):
                if item.get("symbol") == symbol:
                    return {
                        "base": base,
                        "last_price": float(item.get("last_price", 0) or 0),
                        "volume_24h": float(item.get("turnover_24h", 0) or 0),
                    }
        except Exception:
            pass
        return None

    def get_order_book(self, base, quote="USDT", limit=20):
        symbol = self.format_symbol(base, quote)
        try:
            r = requests.get(f"{BASE_URL}/contract/public/depth",
                params={"symbol": symbol}, timeout=8).json()
            if r.get("code") == 1000:
                d = r.get("data", {})
                asks = [[a[0], a[1]] for a in d.get("asks", [])]
                bids = [[b[0], b[1]] for b in d.get("bids", [])]
                return {"asks": asks[:limit], "bids": bids[:limit]}
        except Exception:
            pass
        return None

    def _qty_to_usd(self, price, qty):
        return float(price) * float(qty) * 0.001

    def analyze_depth(self, base, quote="USDT", leverage=20):
        cs = 0.001
        try:
            r = requests.get(f"{BASE_URL}/contract/public/details", timeout=8).json()
            for item in r.get("data", {}).get("symbols", []):
                if item.get("symbol") == self.format_symbol(base, quote):
                    cs = float(item.get("contract_size", 0.001) or 0.001)
                    break
        except Exception:
            pass

        book = self.get_order_book(base, quote, limit=20)
        if not book or not book.get("asks") or not book.get("bids"):
            return {"min_usd": 5, "max_usd": 5, "depth_usd": 0, "spread_bps": 999,
                    "min_notional": 100, "max_notional": 100, "thin": True}

        best_ask = float(book["asks"][0][0])
        best_bid = float(book["bids"][0][0])
        mid = (best_ask + best_bid) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000

        ask_depth = sum(float(a[0]) * float(a[1]) * cs for a in book["asks"])
        bid_depth = sum(float(b[0]) * float(b[1]) * cs for b in book["bids"])
        depth_usd = min(ask_depth, bid_depth)

        if depth_usd <= 0:
            return {"min_usd": 5, "max_usd": 5, "min_notional": 5 * leverage,
                    "max_notional": 5 * leverage, "depth_usd": 0, "spread_bps": spread_bps,
                    "thin": True}

        max_notional = depth_usd * 0.10
        max_margin = max(max_notional / leverage, 5)

        return {
            "min_usd": 5,
            "max_usd": round(max_margin, 2),
            "min_notional": round(5 * leverage, 2),
            "max_notional": round(max_notional, 2),
            "depth_usd": round(depth_usd, 2),
            "spread_bps": round(spread_bps, 2),
        }

    # Trading API
    def get_balance(self):
        if not self.api_key:
            return {"error": "API key not configured"}
        data = self._get_auth("/contract/private/assets-detail")
        if data.get("code") == 1000:
            for acc in data.get("data", []):
                if acc.get("currency") == "USDT":
                    return {
                        "balance": float(acc.get("equity", 0) or 0),
                        "available": float(acc.get("available_balance", 0) or 0),
                        "equity": float(acc.get("equity", 0) or 0),
                    }
        return {"error": data.get("message", str(data))}

    def get_positions(self):
        if not self.api_key:
            return []
        data = self._get_auth("/contract/private/position?symbol=BTCUSDT")
        if data.get("code") == 1000:
            return data.get("data", [])
        return []

    def place_market_order(self, base, side, amount_usdt, leverage=20):
        if not self.api_key:
            return {"ok": False, "error": "API key not configured"}
        symbol = self.format_symbol(base)
        self.set_leverage(base, leverage)

        ticker = self.get_ticker(base)
        price = ticker["last_price"] if ticker else 0
        if price <= 0:
            return {"ok": False, "error": "price unavailable"}

        cs = 0.001
        try:
            r = requests.get(f"{BASE_URL}/contract/public/details", timeout=8).json()
            for item in r.get("data", {}).get("symbols", []):
                if item.get("symbol") == symbol:
                    cs = float(item.get("contract_size", 0.001) or 0.001)
                    break
        except Exception:
            pass

        size = int(amount_usdt * leverage / (price * cs))
        if size < 1:
            size = 1

        order_side = 1 if side == "BUY" else 4
        body = json.dumps({
            "symbol": symbol, "side": order_side, "type": "market",
            "size": size, "leverage": str(leverage), "open_type": "cross",
        })
        headers = self._auth_headers(body)
        try:
            r = requests.post(f"{BASE_URL}/contract/private/submit-order",
                data=body, headers=headers, timeout=10).json()
            if r.get("code") == 1000:
                return {"ok": True, "order_id": r.get("data", {}).get("order_id")}
            return {"ok": False, "error": r.get("message", str(r))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close_position(self, base, position_side="LONG"):
        if not self.api_key:
            return {"ok": False, "error": "API key not configured"}
        symbol = self.format_symbol(base)
        order_side = 3 if position_side == "LONG" else 2

        pos_data = self._get_auth(f"/contract/private/position?symbol={symbol}")
        size = 0
        for p in pos_data.get("data", []):
            if p.get("symbol") == symbol:
                cur = int(p.get("current_amount", 0) or 0)
                if position_side == "LONG" and cur > 0:
                    size = cur
                elif position_side == "SHORT" and cur < 0:
                    size = abs(cur)
        if size <= 0:
            return {"ok": False, "error": "no position found"}

        body = json.dumps({
            "symbol": symbol, "side": order_side, "type": "market",
            "size": size, "leverage": "20", "open_type": "cross",
        })
        headers = self._auth_headers(body)
        try:
            r = requests.post(f"{BASE_URL}/contract/private/submit-order",
                data=body, headers=headers, timeout=10).json()
            if r.get("code") == 1000:
                return {"ok": True, "order_id": r.get("data", {}).get("order_id")}
            return {"ok": False, "error": r.get("message", str(r))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_leverage(self, base, leverage):
        if not self.api_key:
            return False
        symbol = self.format_symbol(base)
        body = json.dumps({"symbol": symbol, "leverage": str(leverage), "open_type": "cross"})
        headers = self._auth_headers(body)
        try:
            r = requests.post(f"{BASE_URL}/contract/private/submit-leverage",
                data=body, headers=headers, timeout=10).json()
            return r.get("code") == 1000
        except Exception:
            return False
