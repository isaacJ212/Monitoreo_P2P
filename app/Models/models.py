from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.Database.database import Base
from sqlalchemy.orm import Mapped, mapped_column

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