from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.Database.database import Base

class MarketSnapshot(Base):
    __tablename__ = "market_snapshot"


    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    timestamp : Mapped[datetime] = mapped_column(
        DateTime, default=lambda : datetime.now(timezone.utc), index=True
    )
    fiat : Mapped[str] = mapped_column(String(10), index= True)
    asset: Mapped[str] = mapped_column(String(10), default="USDT")
    trade_type : Mapped[str] = mapped_column(String(10), index=True)

    best_price : Mapped[float] = mapped_column(Float)
    avg_top5_price : Mapped[float] = mapped_column(Float)
    min_limit : Mapped[float] = mapped_column(Float)
    max_limit : Mapped[int] = mapped_column(Float)
    available_asset : Mapped[int] = mapped_column(Float)
    payment_methods : Mapped[str] = mapped_column(Text)
    merchant_name : Mapped[str] = mapped_column(String(120))
    merchant_finish_rate: Mapped[float] = mapped_column(Float)
    adv_no: Mapped[str] = mapped_column(String(64))


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    fiat: Mapped[str] = mapped_column(String(10), index=True)
    signal_type: Mapped[str] = mapped_column(String(20), index=True)  
    price: Mapped[float] = mapped_column(Float)
    channels_sent: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)


class UserConfig(Base):
    __tablename__ = "user_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fiat: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    asset: Mapped[str] = mapped_column(String(10), default="USDT")
    budget: Mapped[float] = mapped_column(Float, default=5000.0)
    pay_types: Mapped[str] = mapped_column(Text, default="[]")
    buy_target: Mapped[float] = mapped_column(Float, default=36.80)
    sell_target: Mapped[float] = mapped_column(Float, default=40.00)
    only_verified_merchants: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    report_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enable_periodic_reports: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )