"""Phemex Exchange Module - FR読み取り + 通知（手動取引）
板データがREST APIで取得不可のため、板分析は他取引所で代替。
Maker手数料0.01%は最安。手動でエントリーする価値あり。
"""
import requests
import time
from exchanges.base import ExchangeBase

BASE_URL = "https://api.phemex.com"


class PhemexExchange(ExchangeBase):
    name = "phemex"
    display_name = "Phemex"
    can_trade_api = False  # 手動取引（通知のみ）
    maker_fee = 0.0001    # 0.01%（最安）
    taker_fee = 0.0006    # 0.06%

    def format_symbol(self, base, quote="USDT"):
        return f"{base}{quote}"

    def get_funding_rate(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/md/v2/ticker/24hr",
                params={"symbol": symbol}, timeout=8).json()
            d = r.get("result", {})
            return {
                "base": base,
                "fr_rate": float(d.get("fundingRateRr", 0)) * 100,
                "next_funding_time": 0,  # tickerに含まれない
                "mark_price": float(d.get("markPriceRp", 0)),
            }
        except Exception:
            return None

    def get_all_funding_rates(self):
        try:
            r = requests.get(f"{BASE_URL}/md/v2/ticker/24hr/all", timeout=10).json()
            results = []
            for t in r.get("result", []):
                symbol = t.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                base = symbol.replace("USDT", "")
                fr = float(t.get("fundingRateRr", 0)) * 100
                vol = float(t.get("turnoverRv", 0) or 0)

                results.append({
                    "base": base,
                    "symbol": symbol,
                    "fr_rate": fr,
                    "abs_fr": abs(fr),
                    "next_funding_time": 0,
                    "mark_price": float(t.get("markPriceRp", 0) or 0),
                    "vol_24h": vol,
                })
            return results
        except Exception:
            return []

    def get_ticker(self, base):
        symbol = self.format_symbol(base)
        try:
            r = requests.get(f"{BASE_URL}/md/v2/ticker/24hr",
                params={"symbol": symbol}, timeout=8).json()
            d = r.get("result", {})
            return {
                "base": base,
                "last_price": float(d.get("closeRp", 0) or 0),
                "volume_24h": float(d.get("turnoverRv", 0) or 0),
            }
        except Exception:
            return None
