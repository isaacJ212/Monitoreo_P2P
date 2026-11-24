import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.Models.models import MarketSnapshot
from app.Schemas.schemas import PredictionResponse, PredictionSide
from app.Servicies.binance import _analyze_series


def analize_series(db: Session, fiat: str, trade_type: str, limit: int = 120) -> PredictionSide:
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.fiat == fiat.upper(), MarketSnapshot.trade_type == trade_type)
        .order_by(MarketSnapshot.timestamp.desc())
        .limit(limit)
        .all
    )
    if len(rows) < 6 :
        return PredictionSide(
            status="INSUFICIENT_DATA",
            samples_used=len(rows),
            recommendation=f"Recolectando histórico ({len(rows)}/6 muestras mínimas necesarias).",
        )

    rows.reverse() # esto es para el orden cronologico

    prices = np.array([r.best_price for r in rows], dtype=float)
    timestamps = np.array([r.timestamp.timestamp() for r in rows], dtype=float)
    t_minutes = (timestamps - timestamps[0]) / 60.0

    current_price = float(prices[-1])
    sma_short = float(np.mean(prices[-5:]))
    sma_long = float(np.mean(prices[-min(len(prices), 20):]))

    std_dev = float(np.std(prices))
    mean_price = float(np.mean(prices))
    z_score = float((current_price - mean_price) / std_dev) if std_dev > 1e-6 else 0.0

    # Regresión lineal sobre los últimos 24 puntos para capturar la pendiente reciente
    recent_t = t_minutes[-min(len(t_minutes), 24):]
    recent_p = prices[-min(len(prices), 24):]
    if np.ptp(recent_t) > 0:
        slope, intercept = np.polyfit(recent_t, recent_p, 1)
        last_t = recent_t[-1]
        proj_30m = float(slope * (last_t + 30.0) + intercept)
        proj_60m = float(slope * (last_t + 60.0) + intercept)
    else:
        slope = 0.0
        proj_30m = current_price
        proj_60m = current_price

    # Clasificación de tendencia
    if slope > 0.0005 and sma_short > sma_long:
        trend = "ALCISTA"
    elif slope < -0.0005 and sma_short < sma_long:
        trend = "BAJISTA"
    else:
        trend = "LATERAL"

    # Recomendación contextual según lado de la operación
    if trade_type == "BUY":
        if z_score <= -1.2:
            rec = "OPORTUNIDAD DE COMPRA: Precio estadísticamente bajo frente al histórico reciente."
        elif trend == "BAJISTA":
            rec = "ESPERAR: Tendencia bajista; el precio podría bajar un poco más."
        else:
            rec = "NEUTRAL: Precio dentro del rango normal."
    else:  # SELL
        if z_score >= 1.2:
            rec = "OPORTUNIDAD DE VENTA: Precio estadísticamente alto frente al histórico reciente."
        elif trend == "ALCISTA":
            rec = "ESPERAR: Tendencia alcista; podría pagarse mejor en breve."
        else:
            rec = "NEUTRAL: Precio dentro del rango normal."

    return PredictionSide(
        status="OK",
        samples_used=len(rows),
        current_price=round(current_price, 4),
        sma_short=round(sma_short, 4),
        sma_long=round(sma_long, 4),
        projected_next_30m=round(proj_30m, 4),
        projected_next_60m=round(proj_60m, 4),
        z_score=round(z_score, 2),
        trend=trend,
        recommendation=rec,
    )


def build_predictions(db: Session, fiat: str, asset: str = "USDT") -> PredictionResponse:
    fiat = fiat.upper()
    min_buy = (
        db.query(func.min(MarketSnapshot.best_price))
        .filter(MarketSnapshot.fiat == fiat, MarketSnapshot.trade_type == "BUY")
        .scalar()
    )
    max_sell = (
        db.query(func.max(MarketSnapshot.best_price))
        .filter(MarketSnapshot.fiat == fiat, MarketSnapshot.trade_type == "SELL")
        .scalar()
    )

    return PredictionResponse(
        fiat=fiat,
        asset=asset.upper(),
        buy_analysis=_analyze_series(db, fiat, "BUY"),
        sell_analysis=_analyze_series(db, fiat, "SELL"),
        historical_min_buy=round(min_buy, 4) if min_buy else None,
        historical_max_sell=round(max_sell, 4) if max_sell else None,
    )