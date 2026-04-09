"""User settings schemas."""
from pydantic import BaseModel


class SettingsResponse(BaseModel):
    total_capital: float
    position_ratio: float
    p1_enabled: bool
    p1_min_fr_diff: float
    p1_max_slots: int
    p1_amount_per_slot: float
    p2_enabled: bool
    p2_min_fr_diff: float
    p2_max_slots: int
    p2_amount_per_slot: float
    p3_enabled: bool
    p3_min_fr_rate: float
    p3_max_slots: int
    p3_amount_per_slot: float
    leverage: int
    min_volume_24h: float
    order_type: str
    auto_enabled: bool
    max_per_trade: float
    max_daily_loss: float
    max_open_positions: int
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook: str | None = None

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    total_capital: float | None = None
    position_ratio: float | None = None
    p1_enabled: bool | None = None
    p1_min_fr_diff: float | None = None
    p1_max_slots: int | None = None
    p1_amount_per_slot: float | None = None
    p2_enabled: bool | None = None
    p2_min_fr_diff: float | None = None
    p2_max_slots: int | None = None
    p2_amount_per_slot: float | None = None
    p3_enabled: bool | None = None
    p3_min_fr_rate: float | None = None
    p3_max_slots: int | None = None
    p3_amount_per_slot: float | None = None
    leverage: int | None = None
    min_volume_24h: float | None = None
    order_type: str | None = None
    max_per_trade: float | None = None
    max_daily_loss: float | None = None
    max_open_positions: int | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook: str | None = None
