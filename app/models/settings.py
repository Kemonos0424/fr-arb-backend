import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class UserSettings(Base):
    """Per-user strategy settings (replaces shared_config.py)."""
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Capital
    total_capital: Mapped[float] = mapped_column(Numeric(10, 2), default=3000)
    position_ratio: Mapped[float] = mapped_column(Numeric(3, 2), default=0.40)

    # P1: intra-exchange USDT/USDC cross
    p1_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    p1_min_fr_diff: Mapped[float] = mapped_column(Numeric(6, 4), default=0.04)
    p1_max_slots: Mapped[int] = mapped_column(Integer, default=4)
    p1_amount_per_slot: Mapped[float] = mapped_column(Numeric(10, 2), default=250)

    # P2: cross-exchange hedge
    p2_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    p2_min_fr_diff: Mapped[float] = mapped_column(Numeric(6, 4), default=0.04)
    p2_max_slots: Mapped[int] = mapped_column(Integer, default=2)
    p2_amount_per_slot: Mapped[float] = mapped_column(Numeric(10, 2), default=250)

    # P3: single-leg FR
    p3_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    p3_min_fr_rate: Mapped[float] = mapped_column(Numeric(6, 4), default=0.04)
    p3_max_slots: Mapped[int] = mapped_column(Integer, default=2)
    p3_amount_per_slot: Mapped[float] = mapped_column(Numeric(10, 2), default=250)

    # Common
    leverage: Mapped[int] = mapped_column(Integer, default=20)
    min_volume_24h: Mapped[float] = mapped_column(Numeric(12, 2), default=500000)
    order_type: Mapped[str] = mapped_column(String(10), default="limit")

    # Auto-trading
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    max_per_trade: Mapped[float] = mapped_column(Numeric(10, 2), default=250)
    max_daily_loss: Mapped[float] = mapped_column(Numeric(10, 2), default=50)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=4)

    # Daily loss tracking
    daily_loss_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    daily_loss_date: Mapped[str | None] = mapped_column(String(10))  # "YYYY-MM-DD"

    # Notifications
    telegram_bot_token: Mapped[str | None] = mapped_column(String(100))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(50))
    discord_webhook: Mapped[str | None] = mapped_column(String(300))

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="settings")

    def to_fr_config(self) -> dict:
        """Convert to the dict format expected by fr_cross_scanner.find_opportunities()."""
        return {
            "min_volume_24h": float(self.min_volume_24h),
            "entry_before_mins": 30,
            "exit_after_mins": 10,
            "leverage": self.leverage,
            "order_type": self.order_type,
            "p1_intra_cross": {
                "enabled": self.p1_enabled,
                "min_fr_diff": float(self.p1_min_fr_diff),
                "breakeven_1x": 0.08,
                "max_slots": self.p1_max_slots,
                "amount_per_slot": float(self.p1_amount_per_slot),
                "fee_hold_threshold": 0.8,
            },
            "p2_cross_exchange": {
                "enabled": self.p2_enabled,
                "min_fr_diff": float(self.p2_min_fr_diff),
                "breakeven_1x": 0.08,
                "max_slots": self.p2_max_slots,
                "amount_per_slot": float(self.p2_amount_per_slot),
                "fee_hold_threshold": 0.8,
            },
            "p3_single_leg": {
                "enabled": self.p3_enabled,
                "min_fr_rate": float(self.p3_min_fr_rate),
                "max_slots": self.p3_max_slots,
                "amount_per_slot": float(self.p3_amount_per_slot),
                "fee_hold_threshold": 0.8,
                "sl_fr_multiplier": 50,
            },
            "depth": {
                "max_impact_pct": 0.05,
                "max_book_usage": 0.10,
                "min_position_usd": 5,
            },
        }
