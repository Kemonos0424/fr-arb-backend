"""Exchange Base Class - shared_config dependency removed."""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional


class ExchangeBase(ABC):
    name: str
    display_name: str
    can_trade_api: bool
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005

    @abstractmethod
    def format_symbol(self, base: str, quote: str = "USDT") -> str:
        pass

    @abstractmethod
    def get_funding_rate(self, base: str) -> Optional[Dict]:
        pass

    @abstractmethod
    def get_all_funding_rates(self) -> List[Dict]:
        pass

    @abstractmethod
    def get_ticker(self, base: str) -> Optional[Dict]:
        pass

    def get_order_book(self, base: str, quote: str = "USDT", limit: int = 20) -> Optional[Dict]:
        return None

    def _qty_to_usd(self, price: float, qty: float) -> float:
        return price * qty

    def analyze_depth(self, base: str, quote: str = "USDT", leverage: int = 20) -> Dict:
        """Board depth analysis. Leverage is now a parameter (no shared_config import)."""
        book = self.get_order_book(base, quote, limit=20)
        if not book or not book.get("asks") or not book.get("bids"):
            return {"min_usd": 5, "max_usd": 5, "depth_usd": 0, "spread_bps": 999,
                    "min_notional": 100, "max_notional": 100, "thin": True}

        best_ask = float(book["asks"][0][0])
        best_bid = float(book["bids"][0][0])
        mid = (best_ask + best_bid) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000

        ask_depth = sum(self._qty_to_usd(float(a[0]), float(a[1])) for a in book["asks"])
        bid_depth = sum(self._qty_to_usd(float(b[0]), float(b[1])) for b in book["bids"])
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

    def get_all_usdc_funding_rates(self) -> List[Dict]:
        return []

    def get_balance(self) -> Dict:
        raise NotImplementedError(f"{self.name}: API trading not supported")

    def get_positions(self) -> List[Dict]:
        raise NotImplementedError(f"{self.name}: API trading not supported")

    def place_market_order(self, base: str, side: str, amount_usdt: float, leverage: int = 20) -> Dict:
        raise NotImplementedError(f"{self.name}: API trading not supported")

    def close_position(self, base: str, position_side: str = "LONG") -> Dict:
        raise NotImplementedError(f"{self.name}: API trading not supported")

    def set_leverage(self, base: str, leverage: int) -> bool:
        raise NotImplementedError(f"{self.name}: API trading not supported")
