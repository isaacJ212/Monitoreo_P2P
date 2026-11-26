import json
import numpy as np
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config.Config import FIAT_RULES, settings
from app.Database.database import SessionLocal
from app.Models.models import MarketSnapshot
from app.Servicies.arbitrage import compute_arbitrage_match
from app.Servicies.binance import fetch_p2p_market_depth, filter_ads_by_config
from app.Servicies.notifier import dispatch_alert, dispatch_arbitrage_alert
from app.Servicies.predictor import build_predictions, get_historical_averages
from app.Servicies.report_service import dispatch_market_report


scheduler = AsyncIOScheduler()


async def run_monitoring_cycle() -> dict:
    db = SessionLocal()
    summary = {}
    try:
        for fiat, rule in FIAT_RULES.items():
            if not rule.get("enabled", False):
                continue

            asset = rule.get("asset", "USDT")
            budget = float(rule.get("budget", 5000.0))
            pay_types = rule.get("pay_types", [])
            only_merchants = bool(rule.get("only_verified_merchants", False))

            # Mercado general para guardar histórico real del comercio P2P
            general_buy_ads = await fetch_p2p_market_depth(fiat, "BUY", asset, budget=budget, only_merchants=False, pages=2)
            general_sell_ads = await fetch_p2p_market_depth(fiat, "SELL", asset, budget=budget, only_merchants=False, pages=2)

            # Guardar instantáneas del mercado general en base de datos
            for side, ads in (("BUY", general_buy_ads), ("SELL", general_sell_ads)):
                if not ads:
                    continue
                best = ads[0]
                top5_avg = float(np.mean([a.price for a in ads[:5]]))
                snapshot = MarketSnapshot(
                    fiat=fiat.upper(),
                    asset=asset.upper(),
                    trade_type=side,
                    best_price=best.price,
                    avg_top5_price=round(top5_avg, 4),
                    min_limit=best.min_limit,
                    max_limit=best.max_limit,
                    available_asset=best.available_asset,
                    payment_methods=json.dumps(best.payment_methods, ensure_ascii=False),
                    merchant_name=best.merchant_name,
                    merchant_finish_rate=best.finish_rate_pct,
                    adv_no=best.adv_no,
                )
                db.add(snapshot)

            db.commit()

            # Filtrar anuncios según las preferencias guardadas para evaluar alertas personalizadas
            buy_ads, _ = filter_ads_by_config(
                general_buy_ads, budget=budget, pay_types=pay_types, only_merchants=only_merchants
            )
            sell_ads, _ = filter_ads_by_config(
                general_sell_ads, budget=budget, pay_types=pay_types, only_merchants=only_merchants
            )
            if not buy_ads:
                buy_ads = general_buy_ads
            if not sell_ads:
                sell_ads = general_sell_ads

            # Obtener promedios históricos y predicciones
            avg_buy_hist, avg_sell_hist = get_historical_averages(db, fiat, asset)
            predictions = build_predictions(db, fiat, asset)
            arbitrage_match = compute_arbitrage_match(buy_ads, sell_ads, budget=budget, fiat=fiat, asset=asset)

            triggered = []

            # 1. Alerta Inteligente de Arbitraje (Mismo Banco y Ganancia Directa)
            if arbitrage_match and arbitrage_match.is_profitable and arbitrage_match.gain_per_usdt > 0.05:
                channels = await dispatch_arbitrage_alert(db, fiat, asset, arbitrage_match)
                if channels:
                    triggered.append({
                        "signal": "ARBITRAGE_MATCH",
                        "bank": arbitrage_match.matched_bank,
                        "gain_per_usdt": arbitrage_match.gain_per_usdt,
                        "roi_pct": arbitrage_match.spread_pct,
                        "channels": channels
                    })

            # 2. Alerta Inteligente de Compra Barata
            if buy_ads:
                best_buy = buy_ads[0]
                z_buy = predictions.buy_analysis.z_score
                cond_target = best_buy.price <= rule["buy_target"]
                cond_avg = (avg_buy_hist is not None and best_buy.price <= avg_buy_hist * 0.99)
                cond_z = (z_buy is not None and z_buy <= -1.2)

                if cond_target or cond_avg or cond_z:
                    channels = await dispatch_alert(
                        db, fiat, asset, "BUY_OPPORTUNITY", rule["buy_target"], best_buy, predictions.buy_analysis, avg_buy_hist
                    )
                    if channels:
                        triggered.append({"signal": "BUY_OPPORTUNITY", "price": best_buy.price, "channels": channels})

            # 3. Alerta Inteligente de Venta Cara
            if sell_ads:
                best_sell = sell_ads[0]
                z_sell = predictions.sell_analysis.z_score
                cond_target = best_sell.price >= rule["sell_target"]
                cond_avg = (avg_sell_hist is not None and best_sell.price >= avg_sell_hist * 1.01)
                cond_z = (z_sell is not None and z_sell >= 1.2)

                if cond_target or cond_avg or cond_z:
                    channels = await dispatch_alert(
                        db, fiat, asset, "SELL_OPPORTUNITY", rule["sell_target"], best_sell, predictions.sell_analysis, avg_sell_hist
                    )
                    if channels:
                        triggered.append({"signal": "SELL_OPPORTUNITY", "price": best_sell.price, "channels": channels})

            summary[fiat] = {
                "best_buy": buy_ads[0].price if buy_ads else None,
                "best_sell": sell_ads[0].price if sell_ads else None,
                "arbitrage_profitable": arbitrage_match.is_profitable if arbitrage_match else False,
                "net_profit_fiat": arbitrage_match.net_profit_fiat if arbitrage_match else 0.0,
                "alerts_triggered": triggered,
            }
    finally:
        db.close()

    return summary


async def run_periodic_report() -> dict | None:
    if not settings.ENABLE_PERIODIC_REPORTS:
        return None
    db = SessionLocal()
    try:
        rule = FIAT_RULES.get("NIO", {})
        budget = float(rule.get("budget", 5000.0))
        return await dispatch_market_report(db, fiat="NIO", asset="USDT", budget=budget)
    except Exception as exc:
        print(f"[Error Job Informe Periódico] {exc}")
        return None
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(
        run_monitoring_cycle,
        "interval",
        minutes=settings.POLL_INTERVAL_MINUTES,
        id="p2p_monitor_job",
        replace_existing=True,
    )
    if settings.ENABLE_PERIODIC_REPORTS:
        scheduler.add_job(
            run_periodic_report,
            "interval",
            minutes=settings.REPORT_INTERVAL_MINUTES,
            id="periodic_report_job",
            replace_existing=True,
        )
    scheduler.start()
