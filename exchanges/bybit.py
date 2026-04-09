"""Bybit Exchange Module - FR読み取り + API取引"""
import requests
import time
import hashlib
import hmac
from exchanges.base import ExchangeBase

BASE_URL = "https://api.bybit.com"


class BybitExchange(ExchangeBase):
    name = "bybit"
    display_name = "Bybit"
    can_trade_api = False  # APIキー未設定時はFalse
    maker_fee = 0.0002   # 0.02%
    taker_fee = 0.00055  # 0.055%

    def __init__(self, api_key="", api_secret=""):
        self.api_key = api_key
        self.api_secret = api_secret
        if api_key and api_secret:
            self.can_trade_api = True

    def _sign(self, params_str):
        return hmac.new(self.api_secret.encode(), params_str.encode(), hashlib.sha256).hexdigest()

    def _ts(self):
        return str(int(time.time() * 1000))

    def format_symbol(self, base, quote="USDT"):
        return f"{base}{quote}"

    def get_funding_rate(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/v5/market/tickers",
                params={"category": "linear", "symbol": symbol}, timeout=8).json()
            item = r.get("result", {}).get("list", [{}])[0]
            return {
                "base": base,
                "fr_rate": float(item.get("fundingRate", 0)) * 100,
                "next_funding_time": int(item.get("nextFundingTime", 0)),
                "mark_price": float(item.get("markPrice", 0)),
            }
        except Exception:
            return None

    def get_all_funding_rates(self):
        try:
            r = requests.get(f"{BASE_URL}/v5/market/tickers",
                params={"category": "linear"}, timeout=10).json()
            results = []
            for item in r.get("result", {}).get("list", []):
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                base = symbol.replace("USDT", "")
                fr = float(item.get("fundingRate", 0)) * 100
                results.append({
                    "base": base,
                    "symbol": symbol,
                    "fr_rate": fr,
                    "abs_fr": abs(fr),
                    "next_funding_time": int(item.get("nextFundingTime", 0)),
                    "mark_price": float(item.get("markPrice", 0)),
                    "vol_24h": float(item.get("turnover24h", 0)),
                })
            return results
        except Exception:
            return []

    def get_ticker(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/v5/market/tickers",
                params={"category": "linear", "symbol": symbol}, timeout=8).json()
            item = r.get("result", {}).get("list", [{}])[0]
            return {
                "base": base,
                "last_price": float(item.get("lastPrice", 0)),
                "volume_24h": float(item.get("turnover24h", 0)),
            }
        except Exception:
            return None

    # ── 取引API（APIキー設定時のみ） ──

    def get_order_book(self, base, quote="USDT", limit=20):
        try:
            r = requests.get(f"{BASE_URL}/v5/market/orderbook",
                params={"category": "linear", "symbol": f"{base}{quote}", "limit": limit}, timeout=8).json()
            if r.get("retCode") == 0:
                return {"asks": r["result"].get("a", []), "bids": r["result"].get("b", [])}
        except Exception:
            pass
        return None

    def _auth_get(self, path, params=""):
        ts = self._ts()
        recv_window = "5000"
        sign_str = f"{ts}{self.api_key}{recv_window}{params}"
        sig = self._sign(sign_str)
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sig,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": recv_window,
        }
        r = requests.get(f"{BASE_URL}{path}?{params}", headers=headers, timeout=10)
        return r.json()

    def _auth_post(self, path, body):
        import json
        ts = self._ts()
        recv_window = "5000"
        body_str = json.dumps(body)
        sign_str = f"{ts}{self.api_key}{recv_window}{body_str}"
        sig = self._sign(sign_str)
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sig,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": recv_window,
            "Content-Type": "application/json",
        }
        r = requests.post(f"{BASE_URL}{path}", data=body_str, headers=headers, timeout=10)
        return r.json()

    def get_balance(self):
        data = self._auth_get("/v5/account/wallet-balance", "accountType=UNIFIED")
        if data.get("retCode") == 0:
            coins = data.get("result", {}).get("list", [{}])[0].get("coin", [])
            for c in coins:
                if c.get("coin") == "USDT":
                    return {
                        "balance": float(c.get("walletBalance") or 0),
                        "available": float(c.get("availableToWithdraw") or 0),
                        "equity": float(c.get("equity") or 0),
                    }
        return {"error": data.get("retMsg", str(data))}

    def get_positions(self):
        data = self._auth_get("/v5/position/list", "category=linear&settleCoin=USDT")
        if data.get("retCode") == 0:
            return data.get("result", {}).get("list", [])
        return []

    def place_market_order(self, base, side, amount_usdt, leverage=20):
        symbol = self.format_symbol(base)
        self.set_leverage(base, leverage)
        # Bybitは数量をコイン単位で指定する必要がある
        ticker = self.get_ticker(base)
        price = ticker['last_price'] if ticker else 0
        if price <= 0:
            return {"ok": False, "error": "price unavailable"}
        qty = round(amount_usdt * leverage / price, 6)

        body = {
            "category": "linear",
            "symbol": symbol,
            "side": "Buy" if side == "BUY" else "Sell",
            "orderType": "Market",
            "qty": str(qty),
        }
        data = self._auth_post("/v5/order/create", body)
        if data.get("retCode") == 0:
            return {"ok": True, "order_id": data["result"].get("orderId")}
        return {"ok": False, "error": data.get("retMsg", str(data))}

    def close_position(self, base, position_side="LONG"):
        symbol = self.format_symbol(base)
        side = "Sell" if position_side == "LONG" else "Buy"
        # 全量決済
        positions = self.get_positions()
        qty = "0"
        for p in positions:
            if p.get("symbol") == symbol and p.get("side") == ("Buy" if position_side == "LONG" else "Sell"):
                qty = p.get("size", "0")
                break
        if float(qty) <= 0:
            return {"ok": False, "error": "no position found"}

        body = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty,
            "reduceOnly": True,
        }
        data = self._auth_post("/v5/order/create", body)
        if data.get("retCode") == 0:
            return {"ok": True, "order_id": data["result"].get("orderId")}
        return {"ok": False, "error": data.get("retMsg", str(data))}

    def set_leverage(self, base, leverage):
        symbol = self.format_symbol(base)
        body = {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage),
        }
        data = self._auth_post("/v5/position/set-leverage", body)
        return data.get("retCode") == 0
