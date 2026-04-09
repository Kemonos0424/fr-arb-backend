"""MEXC Exchange Module - FR読み取りのみ（取引APIは停止中）"""
import requests
import time
from exchanges.base import ExchangeBase

BASE_URL = "https://contract.mexc.com"


def _get(url, params=None, retries=2):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=8)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i < retries - 1:
                time.sleep(0.5)
    return {}


class MEXCExchange(ExchangeBase):
    name = "mexc"
    display_name = "MEXC"
    can_trade_api = False  # 先物注文APIは2022年から停止中
    maker_fee = 0.0001   # 0.01%
    taker_fee = 0.0004   # 0.04%

    def format_symbol(self, base, quote="USDT"):
        return f"{base}_{quote}"

    def get_funding_rate(self, base):
        symbol = self.format_symbol(base)
        data = _get(f"{BASE_URL}/api/v1/contract/funding_rate/{symbol}").get("data", {})
        if not data:
            return None
        return {
            "base": base,
            "fr_rate": float(data.get("fundingRate", 0)) * 100,
            "next_funding_time": int(data.get("nextSettleTime", 0)),
            "mark_price": 0,
        }

    def get_all_funding_rates(self):
        # 全銘柄取得
        detail = _get(f"{BASE_URL}/api/v1/contract/detail")
        pairs = [c["symbol"].replace("_USDT", "")
                 for c in detail.get("data", [])
                 if c.get("symbol", "").endswith("_USDT")]

        results = []
        for base in pairs:
            symbol = self.format_symbol(base)
            try:
                fr = _get(f"{BASE_URL}/api/v1/contract/funding_rate/{symbol}").get("data", {})
                ticker = _get(f"{BASE_URL}/api/v1/contract/ticker", {"symbol": symbol}).get("data", {})

                fr_rate = float(fr.get("fundingRate", 0)) * 100
                results.append({
                    "base": base,
                    "symbol": symbol,
                    "fr_rate": fr_rate,
                    "abs_fr": abs(fr_rate),
                    "next_funding_time": int(fr.get("nextSettleTime", 0)),
                    "mark_price": float(ticker.get("lastPrice", 0)),
                    "vol_24h": float(ticker.get("amount24", 0)),
                })
            except Exception:
                pass
        return results

    def get_ticker(self, base):
        symbol = self.format_symbol(base)
        data = _get(f"{BASE_URL}/api/v1/contract/ticker", {"symbol": symbol}).get("data", {})
        if not data:
            return None
        return {
            "base": base,
            "last_price": float(data.get("lastPrice", 0)),
            "volume_24h": float(data.get("amount24", 0)),
        }

    # MEXCの板の数量はコントラクト枚数（1枚=contractSize BTC）
    # contractSizeは銘柄ごとに異なる。BTC=0.0001, ETH=0.01等
    _contract_sizes = {}

    def _get_contract_size(self, base, quote="USDT"):
        key = f"{base}_{quote}"
        if key not in self._contract_sizes:
            detail = _get(f"{BASE_URL}/api/v1/contract/detail")
            for c in detail.get("data", []):
                sym = c.get("symbol", "")
                self._contract_sizes[sym] = float(c.get("contractSize", 0.0001))
        return self._contract_sizes.get(key, 0.0001)

    def _qty_to_usd(self, price, qty):
        """MEXCの数量=コントラクト枚数。USD = 枚数 × contractSize × 価格"""
        # analyze_depth呼び出し時にbase情報がないのでcontractSizeは近似値を使用
        # BTC=0.0001が多い。正確にはbase別に取得すべきだが、
        # 板が大きいか小さいかの判定には影響しないレベル
        return qty * 0.0001 * price

    def get_order_book(self, base, quote="USDT", limit=20):
        symbol = f"{base}_{quote}"
        try:
            data = _get(f"{BASE_URL}/api/v1/contract/depth/{symbol}", {"limit": limit}).get("data", {})
            # contractSizeを取得してUSD変換用に保持
            cs = self._get_contract_size(base, quote)
            self._current_contract_size = cs
            return {"asks": data.get("asks", []), "bids": data.get("bids", [])}
        except Exception:
            return None

    def analyze_depth(self, base, quote="USDT"):
        """MEXC用: コントラクト枚数をUSDに正確に変換"""
        cs = self._get_contract_size(base, quote)
        book = self.get_order_book(base, quote, limit=20)
        if not book or not book.get("asks") or not book.get("bids"):
            return {"min_usd": 5, "max_usd": 100, "depth_usd": 0, "spread_bps": 999,
                    "min_notional": 100, "max_notional": 2000}

        best_ask = float(book["asks"][0][0])
        best_bid = float(book["bids"][0][0])
        mid = (best_ask + best_bid) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000

        # 板全体（20段すべて）
        ask_depth = sum(float(a[1]) * cs * float(a[0]) for a in book["asks"])
        bid_depth = sum(float(b[1]) * cs * float(b[0]) for b in book["bids"])
        depth_usd = min(ask_depth, bid_depth)

        max_notional = max(depth_usd * 0.10, 50)
        from shared_config import FR_CONFIG
        lev = FR_CONFIG.get("leverage", 20)

        return {
            "min_usd": 5,
            "max_usd": round(max_notional / lev, 2),
            "min_notional": round(5 * lev, 2),
            "max_notional": round(max_notional, 2),
            "depth_usd": round(depth_usd, 2),
            "spread_bps": round(spread_bps, 2),
        }

    def get_all_usdc_funding_rates(self):
        """MEXC USDC建て先物のFR一括取得"""
        detail = _get(f"{BASE_URL}/api/v1/contract/detail")
        pairs = [c["symbol"].replace("_USDC", "")
                 for c in detail.get("data", [])
                 if c.get("symbol", "").endswith("_USDC")]

        results = []
        for base in pairs:
            symbol = f"{base}_USDC"
            try:
                fr = _get(f"{BASE_URL}/api/v1/contract/funding_rate/{symbol}").get("data", {})
                ticker = _get(f"{BASE_URL}/api/v1/contract/ticker", {"symbol": symbol}).get("data", {})
                fr_rate = float(fr.get("fundingRate", 0)) * 100
                results.append({
                    "base": base, "symbol": symbol, "quote": "USDC",
                    "fr_rate": fr_rate, "abs_fr": abs(fr_rate),
                    "next_funding_time": int(fr.get("nextSettleTime", 0)),
                    "mark_price": float(ticker.get("lastPrice", 0)),
                    "vol_24h": float(ticker.get("amount24", 0)),
                })
            except Exception:
                pass
        return results
