import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session


from app.config.Config import FIAT_RULES, settings
from app.Database.database import Base, auto_sync_sqlite_to_target, engine, get_db
from app.Models.models import AlertLog, MarketSnapshot
from app.scheduler import run_monitoring_cycle, run_periodic_report, scheduler, start_scheduler
from app.Schemas.schemas import FiatRuleUpdate, LiveMarketResponse, PredictionResponse, SmartTargetResponse
from app.Servicies.arbitrage import compute_arbitrage_match
from app.Servicies.binance import fetch_p2p_ads
from app.Servicies.predictor import build_predictions, calculate_smart_targets, get_historical_averages
from app.Servicies.report_service import dispatch_market_report, generate_market_report


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    auto_sync_sqlite_to_target(engine)
    start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Binance P2P Monitor & Predictor API",
    version="1.0.1",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "P2P Monitor API en línea. Visita /docs para la documentación interactiva."}



@app.get("/api/v1/live/{fiat}", response_model=LiveMarketResponse)
async def get_live_market(
    fiat: str,
    asset: str = "USDT",
    budget: float = Query(5000.0, gt=0),
    pay_type: str | None = None,
    only_merchants: bool = False,
    db: Session = Depends(get_db),
):
    fiat_code = fiat.upper()
    asset_code = asset.upper()
    pay_types = [pay_type] if pay_type else []
    buy_ads = await fetch_p2p_ads(fiat_code, "BUY", asset_code, budget, pay_types, only_merchants=only_merchants)
    sell_ads = await fetch_p2p_ads(fiat_code, "SELL", asset_code, budget, pay_types, only_merchants=only_merchants)

    arbitrage_match = compute_arbitrage_match(buy_ads, sell_ads, budget=budget, fiat=fiat_code, asset=asset_code)
    avg_buy, avg_sell = get_historical_averages(db, fiat_code, asset_code)

    return LiveMarketResponse(
        fiat=fiat_code,
        asset=asset_code,
        checked_at=datetime.now(timezone.utc),
        best_buy=buy_ads[0] if buy_ads else None,   
        best_sell=sell_ads[0] if sell_ads else None,
        buy_ads=buy_ads[:10],
        sell_ads=sell_ads[:10],
        arbitrage_match=arbitrage_match,
        historical_avg_buy=avg_buy,
        historical_avg_sell=avg_sell,
    )


@app.get("/api/v1/predictions/{fiat}", response_model=PredictionResponse)
def get_predictions(fiat: str, asset: str = "USDT", db: Session = Depends(get_db)):

    return build_predictions(db, fiat, asset)


@app.get("/api/v1/history/{fiat}")
def get_price_history(
    fiat: str,
    trade_type: str = Query("BUY", pattern="^(BUY|SELL)$"),
    time_range: str = Query("24h", pattern="^(1h|6h|12h|24h|7d|30d|1m)$"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    range_map = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "12h": timedelta(hours=12),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "1m": timedelta(days=30),
    }
    delta = range_map.get(time_range.lower(), timedelta(hours=24))

    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - delta
    cutoff_naive = cutoff_time.replace(tzinfo=None)

    rows = (
        db.query(MarketSnapshot)
        .filter(
            MarketSnapshot.fiat == fiat.upper(),
            MarketSnapshot.trade_type == trade_type,
            MarketSnapshot.timestamp >= cutoff_naive
        )
        .order_by(MarketSnapshot.timestamp.asc())
        .all()
    )

    # Si hay pocos o ningún registro en ese rango específico, asegurar devolver los más recientes disponibles
    if not rows:
        rows = (
            db.query(MarketSnapshot)
            .filter(MarketSnapshot.fiat == fiat.upper(), MarketSnapshot.trade_type == trade_type)
            .order_by(MarketSnapshot.timestamp.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()

    # Muestreo inteligente (downsampling) para rangos largos (ej: 7D o 1M con miles de puntos)
    # asegurando que el gráfico en el frontend sea ultra fluido sin perder tendencias
    total_rows = len(rows)
    if total_rows > 350:
        step = max(1, total_rows // 300)
        sampled = [rows[i] for i in range(0, total_rows - 1, step)]
        if rows[-1] not in sampled:
            sampled.append(rows[-1])
        rows = sampled

    tz_ni = timezone(timedelta(hours=-6))  # Zona horaria de Nicaragua (UTC-6)
    is_long_range = time_range.lower() in ("7d", "30d", "1m")

    result = []
    for r in rows:
        dt = r.timestamp
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(tz_ni)
        label_time = local_dt.strftime("%d/%m %I:%M %p") if is_long_range else local_dt.strftime("%I:%M %p")

        result.append({
            "timestamp": dt.isoformat(),
            "timestamp_local": label_time,
            "best_price": r.best_price,
            "avg_top5_price": r.avg_top5_price,
            "min_limit": r.min_limit,
            "max_limit": r.max_limit,
            "payment_methods": json.loads(r.payment_methods) if isinstance(r.payment_methods, str) else r.payment_methods,
            "merchant_name": r.merchant_name,
        })
    return result


@app.get("/api/v1/alerts")
def get_alerts(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)):
    logs = db.query(AlertLog).order_by(AlertLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "timestamp": a.timestamp.isoformat(),
            "fiat": a.fiat,
            "signal_type": a.signal_type,
            "price": a.price,
            "channels_sent": a.channels_sent,
            "message": a.message,
        }
        for a in logs
    ]


@app.get("/api/v1/config/rules")
def get_rules():
    return FIAT_RULES


@app.get("/api/v1/config/smart-targets/{fiat}", response_model=SmartTargetResponse)
def get_smart_targets(fiat: str, asset: str = "USDT", db: Session = Depends(get_db)):
    return calculate_smart_targets(db, fiat=fiat, asset=asset)


@app.put("/api/v1/config/rules/{fiat}")
def upsert_rule(fiat: str, rule: FiatRuleUpdate):
    if rule.buy_target >= rule.sell_target:
        raise HTTPException(status_code=400, detail="buy_target debe ser menor que sell_target.")
    FIAT_RULES[fiat.upper()] = rule.model_dump()
    return {"fiat": fiat.upper(), "rule": FIAT_RULES[fiat.upper()]}


@app.post("/api/v1/monitor/run")
async def trigger_manual_cycle():
    result = await run_monitoring_cycle()
    return {"status": "completed", "summary": result}


@app.post("/api/v1/reports/send-now")
async def send_report_now(budget: float = Query(5000.0), db: Session = Depends(get_db)):
    result = await dispatch_market_report(db, fiat="NIO", asset="USDT", budget=budget)
    return result


@app.get("/api/v1/reports/latest")
async def get_latest_report(budget: float = Query(5000.0), db: Session = Depends(get_db)):
    data = await generate_market_report(db, fiat="NIO", asset="USDT", budget=budget)
    return data


@app.get("/api/v1/config/report-settings")
def get_report_settings():
    return {
        "interval_minutes": settings.REPORT_INTERVAL_MINUTES,
        "enabled": settings.ENABLE_PERIODIC_REPORTS,
        "email_to": settings.ALERT_EMAIL_TO,
    }


@app.put("/api/v1/config/report-settings")
def update_report_settings(interval_minutes: int = Query(..., ge=5, le=1440), enabled: bool = Query(True)):
    settings.REPORT_INTERVAL_MINUTES = interval_minutes
    settings.ENABLE_PERIODIC_REPORTS = enabled

    if scheduler.get_job("periodic_report_job"):
        scheduler.remove_job("periodic_report_job")
    if enabled:
        scheduler.add_job(
            run_periodic_report,
            "interval",
            minutes=interval_minutes,
            id="periodic_report_job",
            replace_existing=True,
        )
    return {
        "interval_minutes": settings.REPORT_INTERVAL_MINUTES,
        "enabled": settings.ENABLE_PERIODIC_REPORTS,
        "status": "updated",
    }