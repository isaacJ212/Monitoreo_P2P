import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.config.Config import settings
from app.Models.models import AlertLog, MarketSnapshot
from app.Servicies.arbitrage import compute_arbitrage_match
from app.Servicies.binance import fetch_p2p_ads
from app.Servicies.notifier import _send_email_sync, send_waha_detailed
from app.Servicies.predictor import build_predictions, get_historical_averages


async def generate_market_report(
    db: Session,
    fiat: str = "NIO",
    asset: str = "USDT",
    budget: float = 5000.0,
) -> dict:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    tz_ni = timezone(timedelta(hours=-6))
    now_ni = datetime.now(timezone.utc).astimezone(tz_ni)
    now_str = now_ni.strftime("%I:%M %p")
    date_str = now_ni.strftime("%d/%m/%Y")

    # Obtener anuncios en vivo
    buy_ads = await fetch_p2p_ads(clean_fiat, "BUY", clean_asset, budget=budget)
    sell_ads = await fetch_p2p_ads(clean_fiat, "SELL", clean_asset, budget=budget)

    best_buy = buy_ads[0] if buy_ads else None
    best_sell = sell_ads[0] if sell_ads else None

    # Cruce de arbitraje
    arbitrage = compute_arbitrage_match(buy_ads, sell_ads, budget=budget, fiat=clean_fiat, asset=asset)
    top_plays = (arbitrage.top_matches if arbitrage else [])[:3]

    # Predicciones e histórico
    predictions = build_predictions(db, clean_fiat, clean_asset)
    avg_buy_hist, avg_sell_hist = get_historical_averages(db, clean_fiat, clean_asset)

    current_spread = round((best_sell.price - best_buy.price), 2) if (best_buy and best_sell) else 0.0

    return {
        "fiat": clean_fiat,
        "asset": clean_asset,
        "timestamp_local": now_str,
        "date_local": date_str,
        "budget": budget,
        "best_buy_price": best_buy.price if best_buy else 0.0,
        "best_buy_merchant": best_buy.merchant_name if best_buy else "N/D",
        "best_buy_link": best_buy.merchant_link if best_buy else "https://p2p.binance.com",
        "best_buy_banks": best_buy.payment_methods if best_buy else [],
        "best_sell_price": best_sell.price if best_sell else 0.0,
        "best_sell_merchant": best_sell.merchant_name if best_sell else "N/D",
        "best_sell_link": best_sell.merchant_link if best_sell else "https://p2p.binance.com",
        "best_sell_banks": best_sell.payment_methods if best_sell else [],
        "current_spread": current_spread,
        "historical_avg_buy": avg_buy_hist,
        "historical_avg_sell": avg_sell_hist,
        "top_plays": [
            {
                "bank": p.matched_bank,
                "buy_merchant": p.buy_merchant,
                "buy_price": p.buy_price,
                "buy_link": p.buy_merchant_link or p.buy_link,
                "sell_merchant": p.sell_merchant,
                "sell_price": p.sell_price,
                "sell_link": p.sell_merchant_link or p.sell_link,
                "net_profit_fiat": p.net_profit_fiat,
                "roi_pct": p.roi_pct,
                "gain_per_usdt": p.gain_per_usdt,
            }
            for p in top_plays
        ],
        "best_hours_to_buy": predictions.time_patterns.best_hours_to_buy if predictions.time_patterns else [],
        "best_hours_to_sell": predictions.time_patterns.best_hours_to_sell if predictions.time_patterns else [],
        "summary_insight": predictions.time_patterns.summary_insight if predictions.time_patterns else "",
        "buy_trend": predictions.buy_analysis.trend or "LATERAL",
        "sell_trend": predictions.sell_analysis.trend or "LATERAL",
    }


def format_report_messages(data: dict) -> tuple[str, str, str, str]:
    fiat = data["fiat"]
    asset = data["asset"]
    time_str = data["timestamp_local"]
    date_str = data["date_local"]
    capital = data["budget"]

    subject = f"[Informe P2P Nicaragua] 📊 Resumen de Mercado {asset}/{fiat} - {time_str}"

    # Texto Plano
    top_plays_text = ""
    for idx, p in enumerate(data["top_plays"], 1):
        top_plays_text += (
            f"  {idx}. {p['bank']}: Compras a {p['buy_merchant']} (C${p['buy_price']:.2f}) "
            f"➔ Vendes a {p['sell_merchant']} (C${p['sell_price']:.2f})\n"
            f"     Ganancia estimada con C${capital:,.0f}: +C${p['net_profit_fiat']:,.2f} ({p['roi_pct']}%) | Spread: C${p['gain_per_usdt']:.2f}/USDT\n"
            f"     Comprar: {p['buy_link']}\n"
            f"     Vender: {p['sell_link']}\n\n"
        )

    body_text = f"""====================================================
INFORME DE MERCADO BINANCE P2P NICARAGUA ({asset}/{fiat})
Fecha: {date_str} - Hora Local: {time_str}
====================================================

1. PRECIOS ACTUALES DEL MERCADO:
   • Mejor Compra Barata: C${data['best_buy_price']:.2f} (Comerciante: {data['best_buy_merchant']})
   • Mejor Venta Cara:    C${data['best_sell_price']:.2f} (Comerciante: {data['best_sell_merchant']})
   • Diferencial (Spread): C${data['current_spread']:.2f} por USDT
   • Tendencia Compra: {data['buy_trend']} | Tendencia Venta: {data['sell_trend']}

2. TOP JUGADAS GANADORAS CALCULADAS (Capital: C${capital:,.0f}):
{top_plays_text if top_plays_text else "  No hay suficientes cruces rentables en este instante.\\n"}
3. HORARIOS RECOMENDADOS PARA HOY:
   • Mejores horas para COMPRAR: {', '.join(data['best_hours_to_buy']) or 'N/D'}
   • Mejores horas para VENDER:  {', '.join(data['best_hours_to_sell']) or 'N/D'}
   • Consejo táctico: {data['summary_insight']}

====================================================
Este informe se genera periódicamente para que tomes las mejores decisiones comerciales.
"""

    # HTML enriquecido
    top_plays_html = ""
    for idx, p in enumerate(data["top_plays"], 1):
        color = "#10b981" if p["net_profit_fiat"] > 0 else "#64748b"
        top_plays_html += f"""
        <div style="background:#0f172a; border:1px solid #1e293b; border-radius:8px; padding:12px; margin-bottom:10px;">
          <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
            <b style="color:#f59e0b;">Opción #{idx}: {p['bank']}</b>
            <span style="color:{color}; font-weight:bold; font-family:monospace;">
              {'+' if p['net_profit_fiat'] > 0 else ''}C$ {p['net_profit_fiat']:,.2f} ({p['roi_pct']}%)
            </span>
          </div>
          <div style="font-size:12px; color:#cbd5e1; margin-bottom:6px;">
            🛒 <b>Compra:</b> C$ {p['buy_price']:.2f} con <a href="{p['buy_link']}" style="color:#38bdf8; text-decoration:none;"><b>{p['buy_merchant']} ↗</b></a>
          </div>
          <div style="font-size:12px; color:#cbd5e1; margin-bottom:8px;">
            💰 <b>Venta:</b> C$ {p['sell_price']:.2f} con <a href="{p['sell_link']}" style="color:#f43f5e; text-decoration:none;"><b>{p['sell_merchant']} ↗</b></a>
          </div>
          <div style="text-align:right;">
            <a href="{p['buy_link']}" style="background:#10b981; color:#022c22; padding:4px 8px; border-radius:4px; font-weight:bold; font-size:11px; text-decoration:none; margin-right:6px;">Comprar ↗</a>
            <a href="{p['sell_link']}" style="background:#f43f5e; color:#ffffff; padding:4px 8px; border-radius:4px; font-weight:bold; font-size:11px; text-decoration:none;">Vender ↗</a>
          </div>
        </div>
        """

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="background:#0b0f19; color:#f1f5f9; font-family:Arial,sans-serif; padding:20px; margin:0;">
      <div style="max-width:600px; margin:0 auto; background:#111827; border:1px solid #1f2937; border-radius:12px; overflow:hidden;">
        <div style="background:#1e293b; padding:16px 20px; border-bottom:1px solid #334155;">
          <h2 style="margin:0; font-size:18px; color:#ffffff;">📊 Informe de Mercado Binance P2P Nicaragua</h2>
          <span style="font-size:12px; color:#94a3b8;">Fecha: {date_str} | Hora: {time_str} (Nicaragua CST)</span>
        </div>

        <div style="padding:20px;">
          <!-- Resumen de Precios -->
          <div style="display:flex; justify-content:space-between; gap:10px; margin-bottom:20px;">
            <div style="flex:1; background:#064e3b; border:1px solid #047857; border-radius:8px; padding:12px; text-align:center;">
              <span style="font-size:11px; color:#a7f3d0; text-transform:uppercase; font-weight:bold;">🛒 Compra Barata</span>
              <div style="font-size:20px; font-weight:bold; color:#ffffff; font-family:monospace; margin:4px 0;">C$ {data['best_buy_price']:.2f}</div>
              <span style="font-size:11px; color:#cbd5e1;">{data['best_buy_merchant']}</span>
            </div>

            <div style="flex:1; background:#881337; border:1px solid #be123c; border-radius:8px; padding:12px; text-align:center;">
              <span style="font-size:11px; color:#fecdd3; text-transform:uppercase; font-weight:bold;">💰 Venta Cara</span>
              <div style="font-size:20px; font-weight:bold; color:#ffffff; font-family:monospace; margin:4px 0;">C$ {data['best_sell_price']:.2f}</div>
              <span style="font-size:11px; color:#cbd5e1;">{data['best_sell_merchant']}</span>
            </div>
          </div>

          <!-- Top Opciones de Ganancia -->
          <h3 style="font-size:14px; color:#f59e0b; margin-top:0; margin-bottom:10px; text-transform:uppercase;">
            🏆 Top Jugadas Ganadoras (Capital C$ {capital:,.0f})
          </h3>
          {top_plays_html}

          <!-- Horarios Óptimos -->
          <div style="background:#1e1b4b; border:1px solid #4338ca; border-radius:8px; padding:12px; margin-top:20px;">
            <b style="color:#a5b4fc; font-size:13px; display:block; margin-bottom:6px;">⏰ Horas Óptimas Detectadas por el Sistema:</b>
            <div style="font-size:12px; color:#e0e7ff; line-height:1.5;">
              • <b>Horas ideales de COMPRA:</b> {', '.join(data['best_hours_to_buy']) or 'N/D'}<br>
              • <b>Horas ideales de VENTA:</b> {', '.join(data['best_hours_to_sell']) or 'N/D'}
            </div>
            <p style="font-size:11px; color:#cbd5e1; margin:8px 0 0 0; font-style:italic;">
              {data['summary_insight']}
            </p>
          </div>
        </div>

        <div style="background:#0f172a; padding:12px 20px; text-align:center; font-size:11px; color:#64748b; border-top:1px solid #1e293b;">
          Monitor P2P USDT/NIO Nicaragua • Actualización periódica automatizada
        </div>
      </div>
    </body>
    </html>
    """

    # WhatsApp
    wa_plays = ""
    for idx, p in enumerate(data["top_plays"][:2], 1):
        wa_plays += (
            f"*{idx}. {p['bank']}:*\n"
            f"  • Compra: C${p['buy_price']:.2f} ({p['buy_merchant']})\n"
            f"  • Venta:  C${p['sell_price']:.2f} ({p['sell_merchant']})\n"
            f"  • Ganancia: *+C${p['net_profit_fiat']:,.2f}* (+{p['roi_pct']}%)\n"
        )

    body_wa = (
        f"📊 *INFORME DE MERCADO P2P NICARAGUA ({asset}/{fiat})*\n"
        f"⏰ {time_str} - {date_str}\n"
        f"----------------------------------\n"
        f"🛒 *Compra más barata:* C${data['best_buy_price']:.2f} ({data['best_buy_merchant']})\n"
        f"💰 *Venta más cara:* C${data['best_sell_price']:.2f} ({data['best_sell_merchant']})\n"
        f"📊 *Spread actual:* C${data['current_spread']:.2f}/USDT\n"
        f"----------------------------------\n"
        f"🏆 *OPCIONES GANADORAS CON C${capital:,.0f}:*\n"
        f"{wa_plays}\n"
        f"⏰ *Horas recomendadas hoy:*\n"
        f"• Compra: {', '.join(data['best_hours_to_buy'][:2]) or 'N/D'}\n"
        f"• Venta: {', '.join(data['best_hours_to_sell'][:2]) or 'N/D'}"
    )

    return subject, body_text, body_html, body_wa


async def dispatch_market_report(
    db: Session,
    fiat: str = "NIO",
    asset: str = "USDT",
    budget: float = 5000.0,
) -> dict:
    report_data = await generate_market_report(db, fiat=fiat, asset=asset, budget=budget)
    subject, body_text, body_html, body_wa = format_report_messages(report_data)

    sent_channels = []
    errors = {}

    # 1. Enviar Email (HTML + Texto)
    try:
        ok_email = await asyncio.to_thread(_send_email_sync, subject, body_text, body_html)
        if ok_email:
            sent_channels.append("email")
        else:
            errors["email"] = "Credenciales SMTP o destinatario no configurados."
    except Exception as exc:
        errors["email"] = str(exc)
        print(f"[Error Envío Informe Email] {exc}")

    # 2. Enviar WhatsApp vía WAHA
    try:
        wa_res = await send_waha_detailed(body_wa)
        if wa_res.get("ok"):
            sent_channels.append("whatsapp(waha)")
        elif wa_res.get("errors"):
            errors["whatsapp"] = "; ".join(wa_res["errors"])
    except Exception as exc:
        errors["whatsapp"] = str(exc)
        print(f"[Aviso WAHA Informe] {exc}")

    # Registrar en base de datos
    log = AlertLog(
        fiat=fiat.upper(),
        signal_type="PERIODIC_REPORT",
        price=report_data["best_buy_price"],
        channels_sent=",".join(sent_channels) if sent_channels else "none",
        message=f"Informe periódico emitido a las {report_data['timestamp_local']} con spread C${report_data['current_spread']:.2f}",
    )
    db.add(log)
    db.commit()

    return {
        "status": "success" if sent_channels else "failed",
        "channels": sent_channels,
        "errors": errors,
        "report": report_data,
    }

