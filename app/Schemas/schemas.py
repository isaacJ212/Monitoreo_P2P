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
    link: str = ""


class ArbitrageMatch(BaseModel):
    buy_merchant: str
    buy_price: float
    buy_min_limit: float
    buy_max_limit: float
    buy_payment_methods: list[str]
    buy_link: str

    sell_merchant: str
    sell_price: float
    sell_min_limit: float
    sell_max_limit: float
    sell_payment_methods: list[str]
    sell_link: str

    gross_spread: float
    spread_pct: float
    simulated_budget: float
    usdt_obtained: float
    fiat_returned: float
    net_profit_fiat: float
    net_profit_pct: float
    is_profitable: bool
    common_payment_methods: list[str]
    recommendation: str


class LiveMarketResponse(BaseModel):
    fiat: str
    asset: str
    checked_at: datetime
    best_buy: AdDetail | None
    best_sell: AdDetail | None
    buy_ads: list[AdDetail]
    sell_ads: list[AdDetail]
    arbitrage_match: ArbitrageMatch | None = None
    historical_avg_buy: float | None = None
    historical_avg_sell: float | None = None


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


class HourlyPattern(BaseModel):
    hour_local: int  # Hora local de Nicaragua (0 - 23)
    hour_label: str  # Ej: "09:00 AM"
    avg_buy_price: float | None = None
    avg_sell_price: float | None = None
    sample_count: int = 0


class ArbitrageWindow(BaseModel):
    best_buy_hour: str
    avg_buy_price: float
    best_sell_hour: str
    avg_sell_price: float
    expected_spread: float
    expected_roi_pct: float
    insight: str


class PaymentMethodStat(BaseModel):
    method: str
    frequency: int
    avg_min_limit: float
    avg_max_limit: float


class TimePatternAnalysis(BaseModel):
    best_hours_to_buy: list[str] = []   # Ej: ["08:00 AM", "09:00 AM"]
    best_hours_to_sell: list[str] = []  # Ej: ["06:00 PM", "07:00 PM"]
    best_arbitrage_window: ArbitrageWindow | None = None
    hourly_patterns: list[HourlyPattern] = []
    popular_payment_methods: list[PaymentMethodStat] = []
    overall_avg_min_limit: float = 0.0
    overall_avg_max_limit: float = 0.0
    summary_insight: str = ""


class PredictionResponse(BaseModel):
    fiat: str
    asset: str
    buy_analysis: PredictionSide
    sell_analysis: PredictionSide
    historical_min_buy: float | None = None
    historical_max_sell: float | None = None
    historical_avg_buy: float | None = None
    historical_avg_sell: float | None = None
    time_patterns: TimePatternAnalysis | None = None


class FiatRuleUpdate(BaseModel):
    asset: str = "USDT"
    buy_target: float = Field(..., gt=0)
    sell_target: float = Field(..., gt=0)
    budget: float = Field(..., gt=0)
    pay_types: list[str] = []
    enabled: bool = True
