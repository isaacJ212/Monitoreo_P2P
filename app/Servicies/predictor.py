import json
from collections import defaultdict
from datetime import timedelta, timezone
import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.Models.models import MarketSnapshot
from app.Schemas.schemas import (
    HourlyPattern,
    PaymentMethodStat,
    PredictionResponse,
    PredictionSide,
    TimePatternAnalysis,
)


def _analyze_series(db: Session, fiat: str, trade_type: str, limit: int = 120) -> PredictionSide:
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.fiat == fiat.upper(), MarketSnapshot.trade_type == trade_type)
        .order_by(MarketSnapshot.timestamp.desc())
        .limit(limit)
        .all()
    )
    if len(rows) < 6:
        return PredictionSide(
            status="INSUFICIENT_DATA",
            samples_used=len(rows),
            recommendation=f"Recolectando histórico ({len(rows)}/6 muestras mínimas necesarias).",
        )

    rows.reverse()  # Orden cronológico

    prices = np.array([r.best_price for r in rows], dtype=float)
    timestamps = np.array([r.timestamp.timestamp() for r in rows], dtype=float)
    t_minutes = (timestamps - timestamps[0]) / 60.0

    current_price = float(prices[-1])
    sma_short = float(np.mean(prices[-5:]))
    sma_long = float(np.mean(prices[-min(len(prices), 20):]))

    std_dev = float(np.std(prices))
    mean_price = float(np.mean(prices))
    z_score = float((current_price - mean_price) / std_dev) if std_dev > 1e-6 else 0.0

    # Regresión lineal sobre los últimos puntos
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

    # Recomendación contextual
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


def _format_hour_label(hour: int) -> str:
    am_pm = "AM" if hour < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    return f"{h12:02d}:00 {am_pm}"


def _analyze_time_and_payments(db: Session, fiat: str, asset: str = "USDT") -> TimePatternAnalysis:
    # Traer últimas 500 muestras históricas
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.fiat == fiat.upper(), MarketSnapshot.asset == asset.upper())
        .order_by(MarketSnapshot.timestamp.desc())
        .limit(500)
        .all()
    )

    if not rows:
        return TimePatternAnalysis(
            summary_insight="Sin suficiente histórico aún para calcular patrones por hora."
        )

    tz_ni = timezone(timedelta(hours=-6))  # Zona horaria de Nicaragua (UTC-6)

    hourly_buys = defaultdict(list)
    hourly_sells = defaultdict(list)
    pay_methods_map = defaultdict(lambda: {"count": 0, "min_limits": [], "max_limits": []})
    all_min_limits = []
    all_max_limits = []

    for r in rows:
        # Convertir a hora local Nicaragua
        dt = r.timestamp
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_hour = dt.astimezone(tz_ni).hour

        if r.trade_type == "BUY":
            hourly_buys[local_hour].append(r.best_price)
        elif r.trade_type == "SELL":
            hourly_sells[local_hour].append(r.best_price)

        all_min_limits.append(r.min_limit)
        all_max_limits.append(r.max_limit)

        # Parsear métodos de pago
        try:
            methods = json.loads(r.payment_methods)
            if isinstance(methods, list):
                for m in methods:
                    clean_m = str(m).strip()
                    if clean_m:
                        pay_methods_map[clean_m]["count"] += 1
                        pay_methods_map[clean_m]["min_limits"].append(r.min_limit)
                        pay_methods_map[clean_m]["max_limits"].append(r.max_limit)
        except Exception:
            pass

    # Calcular estadísticas por hora (0 a 23)
    patterns: list[HourlyPattern] = []
    avg_buy_by_hour = {}
    avg_sell_by_hour = {}

    for h in range(24):
        b_list = hourly_buys.get(h, [])
        s_list = hourly_sells.get(h, [])
        total_samples = len(b_list) + len(s_list)

        if total_samples > 0:
            avg_b = round(float(np.mean(b_list)), 4) if b_list else None
            avg_s = round(float(np.mean(s_list)), 4) if s_list else None
            if avg_b is not None:
                avg_buy_by_hour[h] = avg_b
            if avg_s is not None:
                avg_sell_by_hour[h] = avg_s

            patterns.append(
                HourlyPattern(
                    hour_local=h,
                    hour_label=_format_hour_label(h),
                    avg_buy_price=avg_b,
                    avg_sell_price=avg_s,
                    sample_count=total_samples,
                )
            )

    # Identificar mejores horas: menor precio para comprar, mayor precio para vender
    best_buy_hours = sorted(avg_buy_by_hour.keys(), key=lambda h: avg_buy_by_hour[h])[:3]
    best_sell_hours = sorted(avg_sell_by_hour.keys(), key=lambda h: avg_sell_by_hour[h], reverse=True)[:3]

    best_buy_labels = [_format_hour_label(h) for h in best_buy_hours]
    best_sell_labels = [_format_hour_label(h) for h in best_sell_hours]

    # Estadísticas de métodos de pago
    popular_methods: list[PaymentMethodStat] = []
    for m_name, data in sorted(pay_methods_map.items(), key=lambda x: x[1]["count"], reverse=True)[:6]:
        mins = data["min_limits"]
        maxs = data["max_limits"]
        popular_methods.append(
            PaymentMethodStat(
                method=m_name,
                frequency=data["count"],
                avg_min_limit=round(float(np.mean(mins)), 2) if mins else 0.0,
                avg_max_limit=round(float(np.mean(maxs)), 2) if maxs else 0.0,
            )
        )

    overall_min = round(float(np.mean(all_min_limits)), 2) if all_min_limits else 0.0
    overall_max = round(float(np.mean(all_max_limits)), 2) if all_max_limits else 0.0

    insight_parts = []
    if best_buy_labels:
        insight_parts.append(f"Mejores horas para COMPRAR barato: {', '.join(best_buy_labels)}.")
    if best_sell_labels:
        insight_parts.append(f"Mejores horas para VENDER caro: {', '.join(best_sell_labels)}.")
    if popular_methods:
        top_m = popular_methods[0]
        insight_parts.append(
            f"Método de pago más activo: {top_m.method} ({top_m.frequency} apariciones, límites típicos {top_m.avg_min_limit:,.0f} a {top_m.avg_max_limit:,.0f} {fiat})."
        )

    summary_insight = " ".join(insight_parts) if insight_parts else "Recopilando datos de patrones horarios."

    return TimePatternAnalysis(
        best_hours_to_buy=best_buy_labels,
        best_hours_to_sell=best_sell_labels,
        hourly_patterns=patterns,
        popular_payment_methods=popular_methods,
        overall_avg_min_limit=overall_min,
        overall_avg_max_limit=overall_max,
        summary_insight=summary_insight,
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
        time_patterns=_analyze_time_and_payments(db, fiat, asset),
    )
