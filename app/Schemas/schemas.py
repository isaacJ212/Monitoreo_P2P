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
    merchant_user_no: str = ""
    merchant_link: str = ""
    month_orders: int
    finish_rate_pct: float
    is_verified_merchant: bool
    link: str = ""


class ArbitragePair(BaseModel):
    matched_bank: str
    buy_merchant: str
    buy_price: float
    buy_min_limit: float
    buy_max_limit: float
    buy_link: str
    buy_user_no: str = ""
    buy_merchant_link: str = ""

    sell_merchant: str
    sell_price: float
    sell_min_limit: float
    sell_max_limit: float
    sell_link: str
    sell_user_no: str = ""
    sell_merchant_link: str = ""

    spread: float
    roi_pct: float
    gain_per_usdt: float
    gain_per_1000_fiat: float
    simulated_budget: float = 5000.0
    usdt_obtained: float = 0.0
    fiat_returned: float = 0.0
    net_profit_fiat: float = 0.0
    net_profit_pct: float = 0.0
    is_profitable: bool
    is_budget_within_limits: bool = True


class ArbitrageMatch(BaseModel):
    matched_bank: str
    buy_merchant: str
    buy_price: float
    buy_min_limit: float
    buy_max_limit: float
    buy_payment_methods: list[str]
    buy_link: str
    buy_user_no: str = ""
    buy_merchant_link: str = ""

    sell_merchant: str
    sell_price: float
    sell_min_limit: float
    sell_max_limit: float
    sell_payment_methods: list[str]
    sell_link: str
    sell_user_no: str = ""
    sell_merchant_link: str = ""

    gross_spread: float
    spread_pct: float
    simulated_budget: float = 5000.0
    usdt_obtained: float = 0.0
    fiat_returned: float = 0.0
    net_profit_fiat: float = 0.0
    net_profit_pct: float = 0.0
    gain_per_usdt: float = 0.0
    gain_per_1000_fiat: float = 0.0
    is_profitable: bool = False
    is_budget_within_limits: bool = True
    common_payment_methods: list[str] = []
    recommendation: str = ""
    top_matches: list[ArbitragePair] = []


class GeneralMarketStats(BaseModel):
    best_buy_price: float | None = None
    best_sell_price: float | None = None
    avg_top5_buy: float | None = None
    avg_top5_sell: float | None = None
    min_buy_price: float | None = None
    max_buy_price: float | None = None
    min_sell_price: float | None = None
    max_sell_price: float | None = None
    general_spread: float | None = None
    general_spread_pct: float | None = None
    total_buy_ads: int = 0
    total_sell_ads: int = 0
    available_banks: list[str] = []


class AppliedMarketConfig(BaseModel):
    budget: float = 5000.0
    pay_type: str | None = None
    only_merchants: bool = False
    filtered_buy_count: int = 0
    filtered_sell_count: int = 0
    budget_filtered: bool = False


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
    general_best_buy: AdDetail | None = None
    general_best_sell: AdDetail | None = None
    general_buy_ads: list[AdDetail] = []
    general_sell_ads: list[AdDetail] = []
    general_arbitrage_match: ArbitrageMatch | None = None
    general_stats: GeneralMarketStats | None = None
    applied_config: AppliedMarketConfig | None = None


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
    best_hours_to_buy: list[str] = []
    best_hours_to_sell: list[str] = []
    best_arbitrage_window: ArbitrageWindow | None = None
    hourly_patterns: list[HourlyPattern] = []
    popular_payment_methods: list[PaymentMethodStat] = []
    overall_avg_min_limit: float = 0.0
    overall_avg_max_limit: float = 0.0
    summary_insight: str = ""


class ForecastPoint(BaseModel):
    timestamp: datetime
    timestamp_ms: int
    timestamp_local: str
    minutes_ahead: int
    predicted_buy: float | None = None
    predicted_sell: float | None = None
    signal: str = "NEUTRAL"


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
    last_snapshot_at: datetime | None = None
    last_snapshot_ms: int | None = None
    timeline_forecast: list[ForecastPoint] = []


class FiatRuleUpdate(BaseModel):
    asset: str = "USDT"
    buy_target: float = Field(..., gt=0)
    sell_target: float = Field(..., gt=0)
    budget: float = Field(..., gt=0)
    pay_types: list[str] = []
    only_verified_merchants: bool = False
    enabled: bool = True
    auto_smart_mode: bool = False


class SmartTargetResponse(BaseModel):
    fiat: str
    asset: str
    suggested_buy_target: float
    suggested_sell_target: float
    historical_avg_buy: float
    historical_avg_sell: float
    spread: float
    spread_pct: float
    samples_used: int
    insight: str

