import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ExchangeApiKey(Base):
    __tablename__ = "exchange_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "exchange", name="uq_user_exchange"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)  # bingx, bitget, bitmart
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    passphrase_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Bitget only
    memo_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # BitMart only
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="api_keys")
