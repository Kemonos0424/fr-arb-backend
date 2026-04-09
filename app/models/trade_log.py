import uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TradeLog(Base):
    __tablename__ = "trade_log"
    __table_args__ = (Index("idx_trade_log_user", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # entry, close, error
    type: Mapped[str | None] = mapped_column(String(20))
    base: Mapped[str | None] = mapped_column(String(20))
    exchange: Mapped[str | None] = mapped_column(String(20))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
