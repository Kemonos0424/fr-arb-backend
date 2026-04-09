"""Position and trade schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel


class PositionResponse(BaseModel):
    id: uuid.UUID
    type: str
    base: str
    legs: dict
    amount_usd: float | None
    leverage: int | None
    fr_rate: float | None
    net_fr: float | None
    expected_income: float | None
    status: str
    opened_at: datetime
    closed_at: datetime | None
    actual_pnl: float | None

    model_config = {"from_attributes": True}


class TradeLogResponse(BaseModel):
    id: int
    action: str
    type: str | None
    base: str | None
    exchange: str | None
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ManualEntryRequest(BaseModel):
    base: str
    type: str  # intra_cross, cross_exchange, single_leg
    exchange: str  # target exchange for single_leg
    side: str  # BUY or SELL
    amount_usdt: float
    leverage: int = 20


class CloseRequest(BaseModel):
    reason: str = "manual"
