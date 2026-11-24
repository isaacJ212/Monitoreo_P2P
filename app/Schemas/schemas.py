from datetime import datetime
from pydantic import BaseModel, Field


class AdDetail(BaseModel):
    adv_no: str
    price: float
    min_limit: float
    max_limit: float
    suggested_amount_fiat: float
    suggested_amount_asset: float
    available_asset: float
    payment_methods: list[str]
    merchant_name: str
    month_orders: int
    finish_rate_pct: float
    is_verified_merchant: bool


class LiveMarketResponse(BaseModel):
    fiat: str
    asset: str
    checked_at: datetime
    best_buy: AdDetail | None
    best_sell: AdDetail | None
    buy_ads: list[AdDetail]
    sell_ads: list[AdDetail]


class PredictionSide(BaseModel):
    status: str
    samples_used: int
    current_price: float | None = None
    sma_short: float | None = None
    sma_long: float | None = None
    projected_next_30m: float | None = None
    projected_next_60m: float | None = None
    z_score: float | None = None
    trend: str | None = None
    recommendation: str


class PredictionResponse(BaseModel):
    fiat: str
    asset: str
    buy_analysis: PredictionSide
    sell_analysis: PredictionSide
    historical_min_buy: float | None = None
    historical_max_sell: float | None = None


class FiatRuleUpdate(BaseModel):
    asset: str = "USDT"
    buy_target: float = Field(..., gt=0)
    sell_target: float = Field(..., gt=0)
    budget: float = Field(..., gt=0)
    pay_types: list[str] = []
    enabled: bool = True