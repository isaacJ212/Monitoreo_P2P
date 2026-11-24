import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session


from app.config.Config import FIAT_RULES
from app.Database.database import Base, engine, get_db
from app.Models.models import AlertLog, MarketSnapshot
from app.scheduler import run_monitoring_cycle, scheduler, start_scheduler
from app.Schemas.schemas import FiatRuleUpdate, LiveMarketResponse, PredictionResponse
from app.Servicies.arbitrage import compute_arbitrage_match
from app.Servicies.binance import fetch_p2p_ads
from app.Servicies.predictor import build_predictions, get_historical_averages


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Binance P2P Monitor & Predictor API",
    version="1.0.0",
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

    arbitrage_match = compute_arbitrage_match(buy_ads, sell_ads, fiat=fiat_code, asset=asset_code)
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
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):

    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.fiat == fiat.upper(), MarketSnapshot.trade_type == trade_type)
        .order_by(MarketSnapshot.timestamp.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "best_price": r.best_price,
            "avg_top5_price": r.avg_top5_price,
            "min_limit": r.min_limit,
            "max_limit": r.max_limit,
            "payment_methods": json.loads(r.payment_methods),
            "merchant_name": r.merchant_name,
        }
        for r in rows
    ]


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