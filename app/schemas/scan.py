"""FR scan result schemas."""
from datetime import datetime
from pydantic import BaseModel


class FRScanResult(BaseModel):
    exchange: str
    base: str
    quote: str
    fr_rate: float
    abs_fr: float
    vol_24h: float
    mark_price: float
    next_funding_time: int
    scan_time: datetime


class Opportunity(BaseModel):
    type: str  # p1_intra_cross, p2_cross_exchange, p3_single_leg
    base: str
    direction: str  # LONG or SHORT
    exchanges: list[str]
    fr_diff: float
    net_income: float
    hold_settles: int
    risk_note: str | None = None


class ApiKeyCreate(BaseModel):
    api_key: str
    secret_key: str
    passphrase: str | None = None  # Bitget
    memo: str | None = None  # BitMart


class ApiKeyStatus(BaseModel):
    exchange: str
    is_configured: bool
    is_valid: bool
    last_verified: datetime | None

    model_config = {"from_attributes": True}
