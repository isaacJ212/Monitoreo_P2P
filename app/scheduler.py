import json
#from sched import scheduler
import numpy as np 
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config.Config import FIAT_RULES, settings
from app.Database.database import SessionLocal
from app.Models.models import MarketSnapshot
from app.Servicies.binance import fetch_p2p_ads
from app.Servicies.notifier import dispatch_alert
from app.Servicies.predictor import build_predictions



scheduler = AsyncIOScheduler()

async def run_monitoring_cycle()-> dict:
    db = SessionLocal()
    summary = {}
    try:
        for fiat, rule in FIAT_RULES.items():
            if not rule.get("enabled", False):
                continue

            asset = rule.get("asset", "USDT")
            budget = rule.get("budget", 5000.0)
            pay_types = rule.get("pay_types", [])

            buy_ads = await fetch_p2p_ads(fiat, "BUY", asset, budget, pay_types)
            sell_ads = await fetch_p2p_ads(fiat, "SELL", asset, budget, pay_types)

            for side, ads in (("BUY", buy_ads), ("SELL", sell_ads)):
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

            predictions = build_predictions(db, fiat, asset)
            triggered = []

            if buy_ads:
                best_buy = buy_ads[0]
                z_buy = predictions.buy_analysis.z_score
                if best_buy.price <= rule["buy_target"] or (z_buy is not None and z_buy <= -1.8):
                    channels = await dispatch_alert(
                        db, fiat, asset, "BUY_LOW", rule["buy_target"], best_buy, predictions.buy_analysis
                    )
                    triggered.append({"signal": "BUY_LOW", "price": best_buy.price, "channels": channels})

            if sell_ads:
                best_sell = sell_ads[0]
                z_sell = predictions.sell_analysis.z_score
                if best_sell.price >= rule["sell_target"] or (z_sell is not None and z_sell >= 1.8):
                    channels = await dispatch_alert(
                        db, fiat, asset, "SELL_HIGH", rule["sell_target"], best_sell, predictions.sell_analysis
                    )
                    triggered.append({"signal": "SELL_HIGH", "price": best_sell.price, "channels": channels})

            summary[fiat] = {
                "best_buy": buy_ads[0].price if buy_ads else None,
                "best_sell": sell_ads[0].price if sell_ads else None,
                "alerts_triggered": triggered,
            }
    finally:
        db.close()

    return summary


def start_scheduler():
    scheduler.add_job(
        run_monitoring_cycle,
        "interval",
        minutes=settings.POLL_INTERVAL_MINUTES,
        id="p2p_monitor_job",
        replace_existing=True,
    )
    scheduler.start()