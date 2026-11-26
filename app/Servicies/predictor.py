import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.Models.models import MarketSnapshot
from app.Schemas.schemas import (
    ArbitrageWindow,
    ForecastPoint,
    HourlyPattern,
    PaymentMethodStat,
    PredictionResponse,
    PredictionSide,
    TimePatternAnalysis,
)

TZ_NI = timezone(timedelta(hours=-6))


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    timestamps = np.array([_as_utc(r.timestamp).timestamp() for r in rows], dtype=float)
    t_minutes = (timestamps - timestamps[0]) / 60.0

    current_price = float(prices[-1])
    sma_short = float(np.mean(prices[-5:]))
    sma_long = float(np.mean(prices[-min(len(prices), 20):]))

    std_dev = float(np.std(prices))
    mean_price = float(np.mean(prices))
    z_score = float((current_price - mean_price) / std_dev) if std_dev > 1e-6 else 0.0

    # Regresión lineal sobre los últimos puntos, anclada suavemente al precio actual
    recent_t = t_minutes[-min(len(t_minutes), 24):]
    recent_p = prices[-min(len(prices), 24):]
    if np.ptp(recent_t) > 0:
        slope, _ = np.polyfit(recent_t, recent_p, 1)
        # Amortiguación para evitar extrapolaciones irreales si la serie tiene saltos bruscos
        max_delta = max(0.03, std_dev * 1.5, current_price * 0.005)
        delta_30 = float(np.clip(slope * 30.0 * 0.85, -max_delta, max_delta))
        delta_60 = float(np.clip(slope * 60.0 * 0.70, -max_delta * 1.35, max_delta * 1.35))
        proj_30m = current_price + delta_30
        proj_60m = current_price + delta_60
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
            rec = "OPORTUNIDAD DE COMPRA: Precio estadísticamente bajo frente al promedio reciente."
        elif trend == "BAJISTA":
            rec = "ESPERAR: Tendencia bajista; el precio podría bajar un poco más."
        else:
            rec = "NEUTRAL: Precio dentro del rango normal."
    else:  # SELL
        if z_score >= 1.2:
            rec = "OPORTUNIDAD DE VENTA: Precio estadísticamente alto frente al promedio reciente."
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


def get_historical_averages(db: Session, fiat: str, asset: str = "USDT") -> tuple[float | None, float | None]:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    avg_buy = (
        db.query(func.avg(MarketSnapshot.best_price))
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.asset == clean_asset, MarketSnapshot.trade_type == "BUY")
        .scalar()
    )
    avg_sell = (
        db.query(func.avg(MarketSnapshot.best_price))
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.asset == clean_asset, MarketSnapshot.trade_type == "SELL")
        .scalar()
    )

    return (
        round(float(avg_buy), 4) if avg_buy is not None else None,
        round(float(avg_sell), 4) if avg_sell is not None else None,
    )


def _analyze_time_and_payments(db: Session, fiat: str, asset: str = "USDT") -> TimePatternAnalysis:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.asset == clean_asset)
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

    # Calcular la mejor Ventana de Arbitraje Diario (Comprar más barato vs Vender más caro)
    best_arbitrage_window = None
    max_window_spread = -999999.0
    best_b_h = None
    best_s_h = None

    for bh, b_price in avg_buy_by_hour.items():
        for sh, s_price in avg_sell_by_hour.items():
            spread = s_price - b_price
            if spread > max_window_spread:
                max_window_spread = spread
                best_b_h = bh
                best_s_h = sh

    if best_b_h is not None and best_s_h is not None and max_window_spread > -99999:
        b_avg = avg_buy_by_hour[best_b_h]
        s_avg = avg_sell_by_hour[best_s_h]
        roi_pct = round((max_window_spread / b_avg) * 100, 2)
        b_lbl = _format_hour_label(best_b_h)
        s_lbl = _format_hour_label(best_s_h)
        best_arbitrage_window = ArbitrageWindow(
            best_buy_hour=b_lbl,
            avg_buy_price=b_avg,
            best_sell_hour=s_lbl,
            avg_sell_price=s_avg,
            expected_spread=round(max_window_spread, 4),
            expected_roi_pct=roi_pct,
            insight=(
                f"Ventana óptima de arbitraje: Comprar a las {b_lbl} (promedio {b_avg:.2f} {clean_fiat}) "
                f"y vender a las {s_lbl} (promedio {s_avg:.2f} {clean_fiat}) "
                f"con margen potencial de +{max_window_spread:.2f} {clean_fiat} (+{roi_pct}%)."
            ),
        )

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
    if best_arbitrage_window:
        insight_parts.append(best_arbitrage_window.insight)
    elif best_buy_labels:
        insight_parts.append(f"Mejores horas para COMPRAR barato: {', '.join(best_buy_labels)}.")
    if popular_methods:
        top_m = popular_methods[0]
        insight_parts.append(
            f"Método de pago dominante: {top_m.method} ({top_m.frequency} registros, límites habituales {top_m.avg_min_limit:,.0f} a {top_m.avg_max_limit:,.0f} {clean_fiat})."
        )

    summary_insight = " ".join(insight_parts) if insight_parts else "Recopilando datos de patrones horarios."

    return TimePatternAnalysis(
        best_hours_to_buy=best_buy_labels,
        best_hours_to_sell=best_sell_labels,
        best_arbitrage_window=best_arbitrage_window,
        hourly_patterns=patterns,
        popular_payment_methods=popular_methods,
        overall_avg_min_limit=overall_min,
        overall_avg_max_limit=overall_max,
        summary_insight=summary_insight,
    )


def _build_timeline_forecast(
    last_ts_utc: datetime | None,
    buy_analysis: PredictionSide,
    sell_analysis: PredictionSide,
    time_patterns: TimePatternAnalysis,
    avg_buy: float | None,
    avg_sell: float | None,
) -> list[ForecastPoint]:
    """Genera puntos de predicción cronológicos anclados exactamente al último snapshot."""
    if last_ts_utc is None:
        return []

    cur_buy = buy_analysis.current_price
    cur_sell = sell_analysis.current_price
    if cur_buy is None and cur_sell is None:
        return []

    hourly_buy_map = {
        h.hour_local: h.avg_buy_price
        for h in time_patterns.hourly_patterns
        if h.avg_buy_price is not None
    }
    hourly_sell_map = {
        h.hour_local: h.avg_sell_price
        for h in time_patterns.hourly_patterns
        if h.avg_sell_price is not None
    }

    p30_b = buy_analysis.projected_next_30m if buy_analysis.projected_next_30m is not None else cur_buy
    p60_b = buy_analysis.projected_next_60m if buy_analysis.projected_next_60m is not None else cur_buy
    p30_s = sell_analysis.projected_next_30m if sell_analysis.projected_next_30m is not None else cur_sell
    p60_s = sell_analysis.projected_next_60m if sell_analysis.projected_next_60m is not None else cur_sell

    ref_buy = buy_analysis.sma_long or avg_buy or cur_buy
    ref_sell = sell_analysis.sma_long or avg_sell or cur_sell
    base_ni_date = last_ts_utc.astimezone(TZ_NI).date()

    def _project_at(mins: int, cur: float | None, p30: float | None, p60: float | None, ref: float | None, hourly_map: dict[int, float], future_hour: int) -> float | None:
        if cur is None:
            return None
        if mins == 0:
            return round(cur, 4)
        if mins == 15:
            return round((cur + (p30 if p30 is not None else cur)) / 2.0, 4)
        if mins == 30:
            return round(p30 if p30 is not None else cur, 4)
        if mins == 45:
            return round(((p30 if p30 is not None else cur) + (p60 if p60 is not None else cur)) / 2.0, 4)
        if mins == 60:
            return round(p60 if p60 is not None else cur, 4)
        # +90m, +120m, +180m: mezcla progresiva entre proyección 60m y patrón horario real de Nicaragua
        base = p60 if p60 is not None else cur
        target = hourly_map.get(future_hour, ref if ref is not None else base)
        blend_w = {90: 0.40, 120: 0.65, 180: 0.85}.get(mins, 0.50)
        return round(base * (1.0 - blend_w) + target * blend_w, 4)

    offsets = [0, 15, 30, 45, 60, 90, 120, 180]
    forecast: list[ForecastPoint] = []

    for mins in offsets:
        dt_utc = last_ts_utc + timedelta(minutes=mins)
        dt_ni = dt_utc.astimezone(TZ_NI)
        future_hour = dt_ni.hour
        pred_b = _project_at(mins, cur_buy, p30_b, p60_b, ref_buy, hourly_buy_map, future_hour)
        pred_s = _project_at(mins, cur_sell, p30_s, p60_s, ref_sell, hourly_sell_map, future_hour)

        # Etiqueta clara en hora Nicaragua
        if dt_ni.date() != base_ni_date:
            lbl = dt_ni.strftime("%d/%m %I:%M %p")
        else:
            lbl = dt_ni.strftime("%I:%M %p")

        # Señal táctica de compra/venta
        signal = "NEUTRAL"
        if pred_b is not None and ref_buy and pred_b <= ref_buy * 0.9985:
            signal = "COMPRAR"
        elif pred_s is not None and ref_sell and pred_s >= ref_sell * 1.0015:
            signal = "VENDER"

        forecast.append(
            ForecastPoint(
                timestamp=dt_utc,
                timestamp_ms=int(dt_utc.timestamp() * 1000),
                timestamp_local=lbl,
                minutes_ahead=mins,
                predicted_buy=pred_b,
                predicted_sell=pred_s,
                signal=signal,
            )
        )

    return forecast


def build_predictions(db: Session, fiat: str, asset: str = "USDT") -> PredictionResponse:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    min_buy = (
        db.query(func.min(MarketSnapshot.best_price))
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.trade_type == "BUY")
        .scalar()
    )
    max_sell = (
        db.query(func.max(MarketSnapshot.best_price))
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.trade_type == "SELL")
        .scalar()
    )
    latest_ts = (
        db.query(func.max(MarketSnapshot.timestamp))
        .filter(MarketSnapshot.fiat == clean_fiat)
        .scalar()
    )
    latest_ts_utc = _as_utc(latest_ts) if latest_ts else None

    avg_buy, avg_sell = get_historical_averages(db, clean_fiat, clean_asset)
    buy_analysis = _analyze_series(db, clean_fiat, "BUY")
    sell_analysis = _analyze_series(db, clean_fiat, "SELL")
    time_patterns = _analyze_time_and_payments(db, clean_fiat, clean_asset)
    timeline_forecast = _build_timeline_forecast(
        latest_ts_utc, buy_analysis, sell_analysis, time_patterns, avg_buy, avg_sell
    )

    return PredictionResponse(
        fiat=clean_fiat,
        asset=clean_asset,
        buy_analysis=buy_analysis,
        sell_analysis=sell_analysis,
        historical_min_buy=round(min_buy, 4) if min_buy else None,
        historical_max_sell=round(max_sell, 4) if max_sell else None,
        historical_avg_buy=avg_buy,
        historical_avg_sell=avg_sell,
        time_patterns=time_patterns,
        last_snapshot_at=latest_ts_utc,
        last_snapshot_ms=int(latest_ts_utc.timestamp() * 1000) if latest_ts_utc else None,
        timeline_forecast=timeline_forecast,
    )


def calculate_smart_targets(db: Session, fiat: str = "NIO", asset: str = "USDT") -> dict:
    clean_fiat = fiat.upper()
    buy_rows = (
        db.query(MarketSnapshot.best_price)
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.trade_type == "BUY")
        .order_by(MarketSnapshot.timestamp.desc())
        .limit(150)
        .all()
    )
    sell_rows = (
        db.query(MarketSnapshot.best_price)
        .filter(MarketSnapshot.fiat == clean_fiat, MarketSnapshot.trade_type == "SELL")
        .order_by(MarketSnapshot.timestamp.desc())
        .limit(150)
        .all()
    )

    buy_prices = [r[0] for r in buy_rows if r[0] > 0]
    sell_prices = [r[0] for r in sell_rows if r[0] > 0]

    if len(buy_prices) >= 5 and len(sell_prices) >= 5:
        avg_b = float(np.mean(buy_prices))
        std_b = float(np.std(buy_prices))
        p25_b = float(np.percentile(buy_prices, 25))
        suggested_buy = round(min(p25_b, avg_b - 0.25 * std_b), 2)

        avg_s = float(np.mean(sell_prices))
        std_s = float(np.std(sell_prices))
        p75_s = float(np.percentile(sell_prices, 75))
        suggested_sell = round(max(p75_s, avg_s + 0.25 * std_s), 2)

        if suggested_buy >= suggested_sell:
            suggested_buy = round(avg_b * 0.995, 2)
            suggested_sell = round(avg_s * 1.005, 2)
            if suggested_buy >= suggested_sell:
                suggested_sell = round(suggested_buy + 0.40, 2)

        spread = round(suggested_sell - suggested_buy, 2)
        spread_pct = round((spread / suggested_buy) * 100, 2)
        samples = len(buy_prices) + len(sell_prices)

        insight = (
            f"Metas estadísticas calibradas con {samples} registros: "
            f"Alerta de compra al bajar a C${suggested_buy:.2f} (percentil 25 más bajo) "
            f"y alerta de venta al subir a C${suggested_sell:.2f} (percentil 75 más alto), "
            f"apuntando a un margen de +C${spread:.2f} NIO (+{spread_pct}%)."
        )
    else:
        suggested_buy = 36.80
        suggested_sell = 37.50
        avg_b = 37.04
        avg_s = 36.60
        spread = round(suggested_sell - suggested_buy, 2)
        spread_pct = round((spread / suggested_buy) * 100, 2)
        samples = len(buy_prices) + len(sell_prices)
        insight = "Datos históricos iniciales. Se usan metas de referencia para Nicaragua: Compra C$36.80, Venta C$37.50."

    return {
        "fiat": clean_fiat,
        "asset": asset.upper(),
        "suggested_buy_target": suggested_buy,
        "suggested_sell_target": suggested_sell,
        "historical_avg_buy": round(avg_b, 2),
        "historical_avg_sell": round(avg_s, 2),
        "spread": spread,
        "spread_pct": spread_pct,
        "samples_used": samples,
        "insight": insight,
    }

