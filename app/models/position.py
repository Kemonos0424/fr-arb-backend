import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (Index("idx_positions_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # intra_cross, cross_exchange, single_leg
    base: Mapped[str] = mapped_column(String(20), nullable=False)

    # Leg details (flexible structure for different strategy types)
    legs: Mapped[dict] = mapped_column(JSONB, nullable=False)

    amount_usd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    leverage: Mapped[int | None] = mapped_column(Integer)
    fr_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))
    net_fr: Mapped[float | None] = mapped_column(Numeric(8, 4))
    expected_income: Mapped[float | None] = mapped_column(Numeric(10, 4))
    hold_settles: Mapped[int] = mapped_column(Integer, default=1)
    settles_received: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default="open")  # open, closed, error
    close_reason: Mapped[str | None] = mapped_column(String(100))

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_pnl: Mapped[float | None] = mapped_column(Numeric(10, 4))
