from datetime import datetime, timezone
from sqlalchemy import BigInteger, String, Numeric, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FRScanCache(Base):
    __tablename__ = "fr_scan_cache"
    __table_args__ = (Index("idx_fr_cache_time", "scan_time"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scan_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    base: Mapped[str] = mapped_column(String(20), nullable=False)
    quote: Mapped[str] = mapped_column(String(10), default="USDT")
    fr_rate: Mapped[float | None] = mapped_column(Numeric(10, 6))
    abs_fr: Mapped[float | None] = mapped_column(Numeric(10, 6))
    vol_24h: Mapped[float | None] = mapped_column(Numeric(16, 2))
    mark_price: Mapped[float | None] = mapped_column(Numeric(20, 8))
    next_funding_time: Mapped[int | None] = mapped_column(BigInteger)
