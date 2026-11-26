import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import numpy as np
from sqlalchemy.orm import Session


from app.config.Config import FIAT_RULES, settings
from app.Database.database import Base, SessionLocal, auto_sync_sqlite_to_target, engine, get_db
from app.Models.models import AlertLog, MarketSnapshot, UserConfig
from app.scheduler import run_monitoring_cycle, run_periodic_report, scheduler, start_scheduler
from app.Schemas.schemas import (
    AppliedMarketConfig,
    FiatRuleUpdate,
    GeneralMarketStats,
    LiveMarketResponse,
    PredictionResponse,
    SmartTargetResponse,
)
from app.Servicies.arbitrage import compute_arbitrage_match
from app.Servicies.binance import (
    fetch_p2p_market_depth,
    filter_ads_by_config,
    normalize_bank_label,
)
from app.Servicies.notifier import (
    check_waha_status,
    get_whatsapp_recipients,
    send_email_detailed,
    send_waha_detailed,
)
from app.Servicies.predictor import build_predictions, calculate_smart_targets, get_historical_averages
from app.Servicies.report_service import dispatch_market_report, generate_market_report


def _load_or_seed_user_configs():
    """Carga la configuración persistida desde la BD hacia FIAT_RULES / settings."""
    db = SessionLocal()
    try:
        configs = db.query(UserConfig).all()
        if not configs:
            for fiat_code, rule in FIAT_RULES.items():
                db.add(
                    UserConfig(
                        fiat=fiat_code.upper(),
                        asset=rule.get("asset", "USDT"),
                        budget=float(rule.get("budget", 5000.0)),
                        pay_types=json.dumps(rule.get("pay_types", [])),
                        buy_target=float(rule.get("buy_target", 36.80)),
                        sell_target=float(rule.get("sell_target", 40.00)),
                        only_verified_merchants=bool(rule.get("only_verified_merchants", False)),
                        enabled=bool(rule.get("enabled", True)),
                        report_interval_minutes=int(settings.REPORT_INTERVAL_MINUTES),
                        enable_periodic_reports=bool(settings.ENABLE_PERIODIC_REPORTS),
                    )
                )
            db.commit()
            return

        for cfg in configs:
            try:
                pts = json.loads(cfg.pay_types) if cfg.pay_types else []
            except Exception:
                pts = []
            FIAT_RULES[cfg.fiat.upper()] = {
                "asset": cfg.asset,
                "buy_target": cfg.buy_target,
                "sell_target": cfg.sell_target,
                "budget": cfg.budget,
                "pay_types": pts,
                "only_verified_merchants": cfg.only_verified_merchants,
                "enabled": cfg.enabled,
            }
            if cfg.fiat.upper() == "NIO":
                settings.REPORT_INTERVAL_MINUTES = cfg.report_interval_minutes
                settings.ENABLE_PERIODIC_REPORTS = cfg.enable_periodic_reports
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    auto_sync_sqlite_to_target(engine)
    _load_or_seed_user_configs()
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
    budget: float | None = Query(None, gt=0),
    pay_type: str | None = None,
    only_merchants: bool | None = None,
    db: Session = Depends(get_db),
):
    fiat_code = fiat.upper()
    asset_code = asset.upper()

    # Si no se envían parámetros explícitos, usar configuración guardada
    saved_rule = FIAT_RULES.get(fiat_code, {})
    eff_budget = float(budget if budget is not None else saved_rule.get("budget", 5000.0))
    saved_pts = saved_rule.get("pay_types") or []
    eff_pay_type = pay_type if pay_type is not None else (saved_pts[0] if saved_pts else "")
    eff_only_merchants = bool(
        only_merchants if only_merchants is not None else saved_rule.get("only_verified_merchants", False)
    )
    pay_types = [eff_pay_type] if eff_pay_type and eff_pay_type.strip() else []

    # 1. Mercado general completo (sin filtros de banco, monto ni verificados)
    general_buy_ads = await fetch_p2p_market_depth(
        fiat_code, "BUY", asset_code, budget=eff_budget, only_merchants=False, pages=2
    )
    general_sell_ads = await fetch_p2p_market_depth(
        fiat_code, "SELL", asset_code, budget=eff_budget, only_merchants=False, pages=2
    )

    general_arbitrage = compute_arbitrage_match(
        general_buy_ads, general_sell_ads, budget=eff_budget, fiat=fiat_code, asset=asset_code
    )

    # Estadísticas globales del mercado P2P (Compra y Venta)
    bank_counts: dict[str, int] = {}
    for ad in general_buy_ads + general_sell_ads:
        for m in ad.payment_methods:
            lbl = normalize_bank_label(m)
            if lbl:
                bank_counts[lbl] = bank_counts.get(lbl, 0) + 1
    top_banks = [k for k, _ in sorted(bank_counts.items(), key=lambda x: x[1], reverse=True)[:6]]

    gen_best_buy = general_buy_ads[0] if general_buy_ads else None
    gen_best_sell = general_sell_ads[0] if general_sell_ads else None
    gen_spread = round(gen_best_sell.price - gen_best_buy.price, 4) if (gen_best_buy and gen_best_sell) else None
    gen_spread_pct = (
        round((gen_spread / gen_best_buy.price) * 100, 2)
        if (gen_spread is not None and gen_best_buy and gen_best_buy.price > 0)
        else None
    )

    general_stats = GeneralMarketStats(
        best_buy_price=gen_best_buy.price if gen_best_buy else None,
        best_sell_price=gen_best_sell.price if gen_best_sell else None,
        avg_top5_buy=round(float(np.mean([a.price for a in general_buy_ads[:5]])), 4) if general_buy_ads else None,
        avg_top5_sell=round(float(np.mean([a.price for a in general_sell_ads[:5]])), 4) if general_sell_ads else None,
        min_buy_price=min(a.price for a in general_buy_ads) if general_buy_ads else None,
        max_buy_price=max(a.price for a in general_buy_ads) if general_buy_ads else None,
        min_sell_price=min(a.price for a in general_sell_ads) if general_sell_ads else None,
        max_sell_price=max(a.price for a in general_sell_ads) if general_sell_ads else None,
        general_spread=gen_spread,
        general_spread_pct=gen_spread_pct,
        total_buy_ads=len(general_buy_ads),
        total_sell_ads=len(general_sell_ads),
        available_banks=top_banks,
    )

    # 2. Mercado filtrado según las configuraciones guardadas del usuario
    filtered_buys, budget_buy_applied = filter_ads_by_config(
        general_buy_ads, budget=eff_budget, pay_types=pay_types, only_merchants=eff_only_merchants
    )
    filtered_sells, budget_sell_applied = filter_ads_by_config(
        general_sell_ads, budget=eff_budget, pay_types=pay_types, only_merchants=eff_only_merchants
    )

    arbitrage_match = compute_arbitrage_match(
        filtered_buys, filtered_sells, budget=eff_budget, fiat=fiat_code, asset=asset_code
    )
    avg_buy, avg_sell = get_historical_averages(db, fiat_code, asset_code)

    return LiveMarketResponse(
        fiat=fiat_code,
        asset=asset_code,
        checked_at=datetime.now(timezone.utc),
        best_buy=filtered_buys[0] if filtered_buys else None,
        best_sell=filtered_sells[0] if filtered_sells else None,
        buy_ads=filtered_buys[:12],
        sell_ads=filtered_sells[:12],
        arbitrage_match=arbitrage_match,
        historical_avg_buy=avg_buy,
        historical_avg_sell=avg_sell,
        general_best_buy=gen_best_buy,
        general_best_sell=gen_best_sell,
        general_buy_ads=general_buy_ads[:12],
        general_sell_ads=general_sell_ads[:12],
        general_arbitrage_match=general_arbitrage,
        general_stats=general_stats,
        applied_config=AppliedMarketConfig(
            budget=eff_budget,
            pay_type=eff_pay_type or None,
            only_merchants=eff_only_merchants,
            filtered_buy_count=len(filtered_buys),
            filtered_sell_count=len(filtered_sells),
            budget_filtered=bool(budget_buy_applied or budget_sell_applied),
        ),
    )


@app.get("/api/v1/predictions/{fiat}", response_model=PredictionResponse)
def get_predictions(fiat: str, asset: str = "USDT", db: Session = Depends(get_db)):

    return build_predictions(db, fiat, asset)


def _parse_ni_dt(raw: str, tz_ni: timezone) -> datetime:
    cleaned = raw.strip().replace(" ", "T")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz_ni)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc_dt(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _downsample_list(items: list, max_points: int = 320) -> list:
    total = len(items)
    if total <= max_points:
        return items
    step = max(1, total // (max_points - 20))
    sampled = [items[i] for i in range(0, total - 1, step)]
    if items[-1] is not sampled[-1]:
        sampled.append(items[-1])
    return sampled


@app.get("/api/v1/history/{fiat}")
def get_price_history(
    fiat: str,
    trade_type: str = Query("BOTH", pattern="^(BUY|SELL|BOTH)$"),
    time_range: str | None = Query(None, pattern="^(1h|6h|12h|24h|7d|30d|1m)$"),
    hours: float | None = Query(None),
    start_time: str | None = Query(None),
    end_time: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    tz_ni = timezone(timedelta(hours=-6))  # Zona horaria de Nicaragua (UTC-6)
    now_utc = datetime.now(timezone.utc)
    fiat_code = fiat.upper()
    is_long_range = False

    base_filter = [MarketSnapshot.fiat == fiat_code]
    if trade_type in ("BUY", "SELL"):
        base_filter.append(MarketSnapshot.trade_type == trade_type)

    # 1. Filtro Manual por Fecha y Hora exacta (Desde / Hasta)
    if start_time:
        try:
            start_utc = _parse_ni_dt(start_time, tz_ni)
            end_utc = _parse_ni_dt(end_time, tz_ni) if end_time else now_utc.replace(tzinfo=None)

            diff = end_utc - start_utc
            if diff < timedelta(hours=1):
                start_utc = end_utc - timedelta(hours=1)
            elif diff > timedelta(days=31):
                start_utc = end_utc - timedelta(days=31)

            rows = (
                db.query(MarketSnapshot)
                .filter(*base_filter, MarketSnapshot.timestamp >= start_utc, MarketSnapshot.timestamp <= end_utc)
                .order_by(MarketSnapshot.timestamp.asc())
                .all()
            )
            is_long_range = (end_utc - start_utc) > timedelta(hours=24)
        except Exception:
            rows = []
    else:
        # 2. Filtro por Horas/Días (mínimo 1 hora, máximo 31 días = 744 horas)
        if hours is not None:
            clamped_hours = max(1.0, min(744.0, float(hours)))
            delta = timedelta(hours=clamped_hours)
        else:
            range_map = {
                "1h": timedelta(hours=1),
                "6h": timedelta(hours=6),
                "12h": timedelta(hours=12),
                "24h": timedelta(hours=24),
                "7d": timedelta(days=7),
                "30d": timedelta(days=30),
                "1m": timedelta(days=30),
            }
            preset = (time_range or "24h").lower()
            delta = range_map.get(preset, timedelta(hours=24))

        cutoff_utc = (now_utc - delta).replace(tzinfo=None)
        rows = (
            db.query(MarketSnapshot)
            .filter(*base_filter, MarketSnapshot.timestamp >= cutoff_utc)
            .order_by(MarketSnapshot.timestamp.asc())
            .all()
        )
        is_long_range = delta > timedelta(hours=24)

        # Si el monitor estuvo pausado recientemente y no hay registros respecto a now_utc,
        # anclar la ventana relativa al último snapshot guardado en la BD.
        if not rows:
            latest = (
                db.query(MarketSnapshot)
                .filter(*base_filter)
                .order_by(MarketSnapshot.timestamp.desc())
                .first()
            )
            if latest:
                latest_naive = _as_utc_dt(latest.timestamp).replace(tzinfo=None)
                anchored_cutoff = latest_naive - delta
                rows = (
                    db.query(MarketSnapshot)
                    .filter(*base_filter, MarketSnapshot.timestamp >= anchored_cutoff)
                    .order_by(MarketSnapshot.timestamp.asc())
                    .all()
                )

    if trade_type in ("BUY", "SELL"):
        rows = _downsample_list(rows, max_points=320)
        result = []
        for r in rows:
            dt = _as_utc_dt(r.timestamp)
            local_dt = dt.astimezone(tz_ni)
            label_time = local_dt.strftime("%d/%m %I:%M %p") if is_long_range else local_dt.strftime("%I:%M %p")
            result.append({
                "timestamp": dt.isoformat(),
                "timestamp_ms": int(dt.timestamp() * 1000),
                "timestamp_local": label_time,
                "hour_local": local_dt.hour,
                "best_price": r.best_price,
                "avg_top5_price": r.avg_top5_price,
                "min_limit": r.min_limit,
                "max_limit": r.max_limit,
                "payment_methods": json.loads(r.payment_methods) if isinstance(r.payment_methods, str) else r.payment_methods,
                "merchant_name": r.merchant_name,
            })
        return result

    # Modo BOTH: emparejar BUY y SELL cronológicamente por ventana de ciclo (<= 90s)
    paired_cycles: list[dict] = []
    for r in rows:
        dt = _as_utc_dt(r.timestamp)
        ts_ms = int(dt.timestamp() * 1000)
        methods = json.loads(r.payment_methods) if isinstance(r.payment_methods, str) else (r.payment_methods or [])

        # Reutilizar último ciclo si está dentro de 90 segundos y le falta este lado
        if paired_cycles and abs(ts_ms - paired_cycles[-1]["timestamp_ms"]) <= 90_000:
            cycle = paired_cycles[-1]
            if r.trade_type == "BUY" and cycle["buy_price"] is None:
                cycle["buy_price"] = r.best_price
                cycle["buy_avg_top5"] = r.avg_top5_price
                cycle["buy_merchant"] = r.merchant_name
                cycle["buy_payment_methods"] = methods
                continue
            if r.trade_type == "SELL" and cycle["sell_price"] is None:
                cycle["sell_price"] = r.best_price
                cycle["sell_avg_top5"] = r.avg_top5_price
                cycle["sell_merchant"] = r.merchant_name
                cycle["sell_payment_methods"] = methods
                continue

        local_dt = dt.astimezone(tz_ni)
        label_time = local_dt.strftime("%d/%m %I:%M %p") if is_long_range else local_dt.strftime("%I:%M %p")
        cycle = {
            "timestamp": dt.isoformat(),
            "timestamp_ms": ts_ms,
            "timestamp_local": label_time,
            "hour_local": local_dt.hour,
            "buy_price": r.best_price if r.trade_type == "BUY" else None,
            "buy_avg_top5": r.avg_top5_price if r.trade_type == "BUY" else None,
            "buy_merchant": r.merchant_name if r.trade_type == "BUY" else None,
            "buy_payment_methods": methods if r.trade_type == "BUY" else [],
            "sell_price": r.best_price if r.trade_type == "SELL" else None,
            "sell_avg_top5": r.avg_top5_price if r.trade_type == "SELL" else None,
            "sell_merchant": r.merchant_name if r.trade_type == "SELL" else None,
            "sell_payment_methods": methods if r.trade_type == "SELL" else [],
            "spread": None,
        }
        paired_cycles.append(cycle)

    for c in paired_cycles:
        if c["buy_price"] is not None and c["sell_price"] is not None:
            c["spread"] = round(c["sell_price"] - c["buy_price"], 4)

    return _downsample_list(paired_cycles, max_points=320)


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
def upsert_rule(fiat: str, rule: FiatRuleUpdate, db: Session = Depends(get_db)):
    if rule.buy_target >= rule.sell_target:
        raise HTTPException(status_code=400, detail="buy_target debe ser menor que sell_target.")
    fiat_code = fiat.upper()
    rule_dict = rule.model_dump()
    FIAT_RULES[fiat_code] = rule_dict

    cfg = db.query(UserConfig).filter(UserConfig.fiat == fiat_code).first()
    if cfg is None:
        cfg = UserConfig(fiat=fiat_code)
        db.add(cfg)

    cfg.asset = rule.asset.upper()
    cfg.budget = float(rule.budget)
    cfg.pay_types = json.dumps(rule.pay_types or [])
    cfg.buy_target = float(rule.buy_target)
    cfg.sell_target = float(rule.sell_target)
    cfg.only_verified_merchants = bool(rule.only_verified_merchants)
    cfg.enabled = bool(rule.enabled)
    cfg.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"fiat": fiat_code, "rule": FIAT_RULES[fiat_code], "persisted": True}


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
def update_report_settings(
    interval_minutes: int = Query(..., ge=5, le=1440),
    enabled: bool = Query(True),
    db: Session = Depends(get_db),
):
    settings.REPORT_INTERVAL_MINUTES = interval_minutes
    settings.ENABLE_PERIODIC_REPORTS = enabled

    cfg = db.query(UserConfig).filter(UserConfig.fiat == "NIO").first()
    if cfg:
        cfg.report_interval_minutes = interval_minutes
        cfg.enable_periodic_reports = enabled
        cfg.updated_at = datetime.now(timezone.utc)
        db.commit()

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


@app.get("/api/v1/notifications/status")
async def get_notifications_status():
    waha_status = await check_waha_status()
    email_ok = bool(settings.SMTP_USER and settings.SMTP_PASSWORD and settings.ALERT_EMAIL_TO)
    return {
        "waha": waha_status,
        "email": {
            "configured": email_ok,
            "smtp_host": settings.SMTP_HOST,
            "smtp_port": settings.SMTP_PORT,
            "from": settings.SMTP_USER,
            "to": settings.ALERT_EMAIL_TO,
            "detail": (
                f"Listo para enviar a {settings.ALERT_EMAIL_TO}"
                if email_ok
                else "Falta SMTP_USER, SMTP_PASSWORD o ALERT_EMAIL_TO en .env"
            ),
        },
    }


@app.post("/api/v1/notifications/test-whatsapp")
async def test_whatsapp_notification(
    recipient: str | None = Query(None),
    db: Session = Depends(get_db),
):
    tz_ni = timezone(timedelta(hours=-6))
    now_str = datetime.now(timezone.utc).astimezone(tz_ni).strftime("%d/%m/%Y %I:%M %p")
    msg = (
        f"✅ *Prueba de WhatsApp — Monitor P2P Nicaragua*\n"
        f"⏰ {now_str} (Hora NI)\n"
        f"Tu conexión con WAHA está funcionando correctamente para recibir alertas USDT/NIO."
    )
    res = await send_waha_detailed(msg, recipient_override=recipient)

    log = AlertLog(
        fiat="NIO",
        signal_type="TEST_WHATSAPP",
        price=0.0,
        channels_sent="whatsapp(waha)" if res["ok"] else "failed",
        message=(
            f"Prueba WhatsApp enviada a {', '.join(res['recipients_sent'])} (sesión: {res['session_used']})"
            if res["ok"]
            else f"Error WhatsApp: {'; '.join(res['errors'])}"
        ),
    )
    db.add(log)
    db.commit()

    return {
        "ok": res["ok"],
        "session_used": res["session_used"],
        "recipients": res["recipients_sent"] or get_whatsapp_recipients(),
        "error": "; ".join(res["errors"]) if res["errors"] else None,
    }


@app.post("/api/v1/notifications/test-email")
async def test_email_notification(db: Session = Depends(get_db)):
    tz_ni = timezone(timedelta(hours=-6))
    now_str = datetime.now(timezone.utc).astimezone(tz_ni).strftime("%d/%m/%Y %I:%M %p")
    subject = f"[Monitor P2P Nicaragua] ✅ Prueba de Correo - {now_str}"
    body_text = (
        f"Prueba exitosa del sistema Monitor P2P Nicaragua.\n"
        f"Fecha y hora (Nicaragua): {now_str}\n"
        f"Tu canal SMTP está configurado correctamente para recibir alertas y reportes."
    )
    body_html = f"""
    <div style="font-family:Arial,sans-serif;background:#0b0f19;color:#f1f5f9;padding:20px;border-radius:10px;">
      <h2 style="color:#10b981;margin-top:0;">✅ Prueba de Correo Exitosa</h2>
      <p>Tu sistema <b>Monitor P2P Nicaragua (USDT/NIO)</b> está enviando correos correctamente.</p>
      <p style="color:#94a3b8;font-size:12px;">Hora Nicaragua: {now_str}</p>
    </div>
    """
    res = await asyncio.to_thread(send_email_detailed, subject, body_text, body_html)

    log = AlertLog(
        fiat="NIO",
        signal_type="TEST_EMAIL",
        price=0.0,
        channels_sent="email" if res["ok"] else "failed",
        message=(
            f"Prueba correo enviada a {res['recipient']}"
            if res["ok"]
            else f"Error correo: {res['error']}"
        ),
    )
    db.add(log)
    db.commit()

    return res