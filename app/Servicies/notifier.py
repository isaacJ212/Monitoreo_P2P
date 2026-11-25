import asyncio
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import httpx
from sqlalchemy.orm import Session
from app.config.Config import settings
from app.Models.models import AlertLog
from app.Schemas.schemas import AdDetail, ArbitrageMatch, PredictionSide


def is_in_cooldown(db: Session, fiat: str, signal_type: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.ALERT_COOLDOWN_MINUTES)
    recent = (
        db.query(AlertLog)
        .filter(
            AlertLog.fiat == fiat.upper(),
            AlertLog.signal_type == signal_type,
            AlertLog.timestamp >= cutoff,
        )
        .first()
    )
    return recent is not None


def format_alert_message(
    signal_type: str,
    fiat: str,
    asset: str,
    target_price: float,
    ad: AdDetail,
    prediction: PredictionSide,
    historical_avg: float | None = None,
) -> tuple[str, str, str, str]:
    is_buy = "BUY" in signal_type
    merchant_link = ad.merchant_link or ad.link or f"https://p2p.binance.com/es/trade/{'buy' if is_buy else 'sell'}/{asset}?fiat={fiat}"
    methods_str = ", ".join(ad.payment_methods) if ad.payment_methods else "Transferencia Bancaria"
    badge = "Verificado" if ad.is_verified_merchant else "Estándar"

    if is_buy:
        # ACCIÓN EXCLUSIVA DE COMPRA
        action_name = "COMPRA DE USDT"
        subject = f"[Binance P2P COMPRA] 🟢 Oportunidad: Comprar USDT a C${ad.price:.2f} con {ad.merchant_name}"
        action_hint = (
            "💡 ACCIÓN A REALIZAR: COMPRAR USDT AHORA (PASO SEPARADO)\n"
            "El precio de compra está bajo frente a tu meta. Paga en Córdobas por tu banco "
            "y recibe USDT baratos. Puedes conservarlos en tu billetera hasta que se active la alerta de venta cara."
        )
        accent_color = "#10b981"
        badge_bg = "#064e3b"
    else:
        # ACCIÓN EXCLUSIVA DE VENTA
        action_name = "VENTA DE USDT"
        subject = f"[Binance P2P VENTA] 🔴 Oportunidad: Vender USDT a C${ad.price:.2f} con {ad.merchant_name}"
        action_hint = (
            "💡 ACCIÓN A REALIZAR: VENDER USDT AHORA (PASO SEPARADO)\n"
            "El precio de venta está alto frente a tu meta. Si tienes USDT acumulados, "
            "es el momento óptimo para venderlos y cobrar la mayor cantidad de Córdobas en tu cuenta bancaria."
        )
        accent_color = "#f43f5e"
        badge_bg = "#881337"

    avg_text = f"Promedio histórico de referencia: C${historical_avg:.2f} {fiat}\n" if historical_avg else ""

    body_email = (
        f"====================================================\n"
        f"ALERTA INDEPENDIENTE: {action_name}\n"
        f"====================================================\n\n"
        f"{action_hint}\n\n"
        f"DETALLES DE LA OPERACIÓN:\n"
        f"• Par: {asset}/{fiat}\n"
        f"• Precio de la oferta: C${ad.price:.2f} {fiat}\n"
        f"• Tu precio objetivo:  C${target_price:.2f} {fiat}\n"
        f"{avg_text}"
        f"• Comerciante: {ad.merchant_name} ({badge} | {ad.finish_rate_pct}% efectividad en {ad.month_orders} órdenes)\n"
        f"• Límites admitidos: C${ad.min_limit:,.2f} a C${ad.max_limit:,.2f} {fiat}\n"
        f"• Bancos para operar: {methods_str}\n"
        f"----------------------------------------------------\n"
        f"Análisis estadístico: {prediction.recommendation}\n"
        f"Enlace directo Binance: {merchant_link}\n"
    )

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="background:#0b0f19; color:#f1f5f9; font-family:Arial,sans-serif; padding:20px; margin:0;">
      <div style="max-width:560px; margin:0 auto; background:#111827; border:1px solid #1f2937; border-radius:12px; overflow:hidden;">
        <div style="background:{badge_bg}; padding:16px 20px; border-bottom:1px solid #334155;">
          <span style="font-size:11px; text-transform:uppercase; font-weight:bold; color:#ffffff; background:rgba(0,0,0,0.3); padding:3px 8px; border-radius:4px;">
            {action_name}
          </span>
          <h2 style="margin:8px 0 0 0; font-size:18px; color:#ffffff;">{subject}</h2>
        </div>

        <div style="padding:20px;">
          <div style="background:#0f172a; border-left:4px solid {accent_color}; padding:12px; border-radius:4px; margin-bottom:16px; font-size:13px; color:#cbd5e1; line-height:1.5;">
            {action_hint.replace(chr(10), '<br>')}
          </div>

          <div style="background:#1e293b; padding:16px; border-radius:8px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
              <span style="color:#94a3b8; font-size:12px;">Precio Ofertado:</span>
              <b style="color:{accent_color}; font-size:18px; font-family:monospace;">C$ {ad.price:.2f} {fiat}</b>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:8px;">
              <span style="color:#94a3b8;">Comerciante:</span>
              <a href="{merchant_link}" style="color:#38bdf8; font-weight:bold; text-decoration:none;">{ad.merchant_name} ({ad.finish_rate_pct}%) ↗</a>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:8px;">
              <span style="color:#94a3b8;">Límites:</span>
              <span style="color:#ffffff;">C$ {ad.min_limit:,.0f} a C$ {ad.max_limit:,.0f}</span>
            </div>
            <div style="display:flex; justify-content:space-between; font-size:12px;">
              <span style="color:#94a3b8;">Bancos:</span>
              <span style="color:#f59e0b; font-weight:bold;">{methods_str}</span>
            </div>
          </div>

          <div style="text-align:center; margin-top:20px;">
            <a href="{merchant_link}" style="display:inline-block; background:{accent_color}; color:#000000; font-weight:bold; padding:12px 24px; border-radius:8px; text-decoration:none; font-size:13px;">
              Abrir Operación en Binance P2P &rarr;
            </a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """

    emoji = "🟢" if is_buy else "🔴"
    avg_wa = f"• Promedio histórico: *C${historical_avg:.2f}*\n" if historical_avg else ""
    body_whatsapp = (
        f"{emoji} *ALERTA BINANCE P2P: {action_name}*\n"
        f"----------------------------------\n"
        f"💵 *Precio:* C${ad.price:.2f} {fiat}\n"
        f"🎯 Meta: C${target_price:.2f} {fiat}\n"
        f"{avg_wa}"
        f"👤 *Comerciante:* {ad.merchant_name} ({ad.finish_rate_pct}%)\n"
        f"📊 *Límites:* C${ad.min_limit:,.0f} - C${ad.max_limit:,.0f}\n"
        f"💳 *Bancos:* {methods_str}\n"
        f"----------------------------------\n"
        f"💡 {action_name} (Acción por separado)\n"
        f"🔗 *Enlace directo:* {merchant_link}"
    )

    return subject, body_email, body_html, body_whatsapp


def format_arbitrage_message(fiat: str, asset: str, match: ArbitrageMatch) -> tuple[str, str, str, str]:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    subject = (
        f"[Binance P2P Arbitraje] 🏆 Ganancia en {match.matched_bank}: +C${match.gain_per_usdt:.2f}/USDT "
        f"(+{match.spread_pct}%)"
    )

    buy_link = match.buy_merchant_link or match.buy_link
    sell_link = match.sell_merchant_link or match.sell_link

    body_email = (
        f"🏆 JUGADA GANADORA DETECTADA: {clean_asset}/{clean_fiat}\n"
        f"============================================================\n"
        f"BANCO COINCIDENTE: {match.matched_bank}\n"
        f"Ganancia por cada 1 USDT: +C${match.gain_per_usdt:.2f} {clean_fiat} (+{match.spread_pct}%)\n"
        f"Ganancia estimada con C${match.simulated_budget:,.0f}: +C${match.net_profit_fiat:,.2f} {clean_fiat}\n"
        f"------------------------------------------------------------\n"
        f"1. PASO COMPRA (PRECIO MÁS BAJO):\n"
        f"   - Comerciante: {match.buy_merchant}\n"
        f"   - Precio de Compra: C${match.buy_price:.2f} {clean_fiat}\n"
        f"   - Límites: C${match.buy_min_limit:,.0f} a C${match.buy_max_limit:,.0f} {clean_fiat}\n"
        f"   - Enlace: {buy_link}\n\n"
        f"2. PASO VENTA (PRECIO MÁS ALTO):\n"
        f"   - Comerciante: {match.sell_merchant}\n"
        f"   - Precio de Venta: C${match.sell_price:.2f} {clean_fiat}\n"
        f"   - Límites: C${match.sell_min_limit:,.0f} a C${match.sell_max_limit:,.0f} {clean_fiat}\n"
        f"   - Enlace: {sell_link}\n\n"
        f"Spread bruto por USDT: C${match.gross_spread:.2f} {clean_fiat}\n"
        f"============================================================\n"
        f"Ambos comerciantes operan con {match.matched_bank}."
    )

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="background:#0b0f19; color:#f1f5f9; font-family:Arial,sans-serif; padding:20px; margin:0;">
      <div style="max-width:580px; margin:0 auto; background:#111827; border:1px solid #1f2937; border-radius:12px; overflow:hidden;">
        <div style="background:#1e293b; padding:16px 20px; border-bottom:1px solid #334155;">
          <span style="font-size:11px; text-transform:uppercase; font-weight:bold; color:#f59e0b; background:rgba(0,0,0,0.3); padding:3px 8px; border-radius:4px;">
            🏆 Arbitraje Inmediato ({match.matched_bank})
          </span>
          <h2 style="margin:8px 0 0 0; font-size:18px; color:#ffffff;">{subject}</h2>
        </div>

        <div style="padding:20px;">
          <div style="background:#0f172a; padding:16px; border-radius:8px; text-align:center; margin-bottom:16px; border:1px solid #334155;">
            <span style="font-size:12px; color:#94a3b8;">Ganancia Neta Estimada (Capital C$ {match.simulated_budget:,.0f}):</span>
            <div style="font-size:24px; font-weight:bold; color:#10b981; font-family:monospace; margin:4px 0;">
              +C$ {match.net_profit_fiat:,.2f} NIO (+{match.spread_pct}%)
            </div>
            <span style="font-size:12px; color:#f59e0b;">+C$ {match.gain_per_usdt:.2f} por cada USDT</span>
          </div>

          <!-- Paso 1 -->
          <div style="background:#064e3b; border:1px solid #047857; padding:12px; border-radius:8px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
              <b style="color:#a7f3d0; font-size:12px;">1. COMPRAS BARATO:</b>
              <b style="color:#ffffff; font-family:monospace;">C$ {match.buy_price:.2f}</b>
            </div>
            <span style="font-size:12px; color:#cbd5e1;">Comerciante: {match.buy_merchant}</span><br>
            <span style="font-size:11px; color:#94a3b8;">Límites: C$ {match.buy_min_limit:,.0f} a C$ {match.buy_max_limit:,.0f}</span><br>
            <a href="{buy_link}" style="display:inline-block; margin-top:6px; color:#38bdf8; font-weight:bold; font-size:11px; text-decoration:none;">Comprar en Binance ↗</a>
          </div>

          <!-- Paso 2 -->
          <div style="background:#881337; border:1px solid #be123c; padding:12px; border-radius:8px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
              <b style="color:#fecdd3; font-size:12px;">2. VENDES CARO:</b>
              <b style="color:#ffffff; font-family:monospace;">C$ {match.sell_price:.2f}</b>
            </div>
            <span style="font-size:12px; color:#cbd5e1;">Comerciante: {match.sell_merchant}</span><br>
            <span style="font-size:11px; color:#94a3b8;">Límites: C$ {match.sell_min_limit:,.0f} a C$ {match.sell_max_limit:,.0f}</span><br>
            <a href="{sell_link}" style="display:inline-block; margin-top:6px; color:#f43f5e; font-weight:bold; font-size:11px; text-decoration:none;">Vender en Binance ↗</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """

    body_whatsapp = (
        f"🏆 *¡JUGADA GANADORA P2P ({clean_asset}/{clean_fiat})!* 🚀\n"
        f"🏦 Banco coincidente: *{match.matched_bank}*\n"
        f"💰 *Ganancia: +C${match.gain_per_usdt:.2f} por USDT (+{match.spread_pct}%)*\n"
        f"💵 Ganas aprox: *+C${match.net_profit_fiat:,.2f} con C${match.simulated_budget:,.0f}*\n"
        f"----------------------------------\n"
        f"🟢 *1. COMPRAR USDT BARATO:*\n"
        f"• Vendedor: *{match.buy_merchant}*\n"
        f"• Precio: *C${match.buy_price:.2f}*\n"
        f"• Link: {buy_link}\n\n"
        f"🔴 *2. VENDER USDT CARO:*\n"
        f"• Comprador: *{match.sell_merchant}*\n"
        f"• Precio: *C${match.sell_price:.2f}*\n"
        f"• Link: {sell_link}\n"
    )

    return subject, body_email, body_html, body_whatsapp


def _send_email_sync(subject: str, body_text: str, body_html: str | None = None) -> bool:
    if not (settings.SMTP_USER and settings.SMTP_PASSWORD and settings.ALERT_EMAIL_TO):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.ALERT_EMAIL_TO
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
    return True


async def _send_waha_message(text: str) -> bool:
    """Envío de mensaje WhatsApp a través de WAHA (WhatsApp HTTP API)."""
    if not (settings.WAHA_API_URL and settings.WAHA_CHAT_ID):
        return False

    chat_id = settings.WAHA_CHAT_ID.strip().replace("+", "").replace(" ", "")
    if not chat_id.endswith("@c.us") and not chat_id.endswith("@g.us"):
        chat_id = f"{chat_id}@c.us"

    payload = {
        "session": settings.WAHA_SESSION or "default",
        "chatId": chat_id,
        "text": text,
    }
    headers = {"Content-Type": "application/json"}
    if settings.WAHA_API_KEY:
        headers["X-Api-Key"] = settings.WAHA_API_KEY

    target_urls = [settings.WAHA_API_URL]
    if "localhost" in settings.WAHA_API_URL:
        target_urls.append(settings.WAHA_API_URL.replace("localhost", "waha"))

    async with httpx.AsyncClient(timeout=12.0) as client:
        last_exc = None
        for u in target_urls:
            try:
                res = await client.post(u, json=payload, headers=headers)
                res.raise_for_status()
                return True
            except Exception as e:
                last_exc = e
        if last_exc:
            raise last_exc
    return False


async def _send_twilio_message(from_number: str, to_number: str, body: str) -> bool:
    """Envío alternativo mediante Twilio si está configurado."""
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and from_number and to_number):
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={"From": from_number, "To": to_number, "Body": body},
        )
        res.raise_for_status()
    return True


async def dispatch_alert(
    db: Session,
    fiat: str,
    asset: str,
    signal_type: str,
    target_price: float,
    ad: AdDetail,
    prediction: PredictionSide,
    historical_avg: float | None = None,
) -> list[str]:
    if is_in_cooldown(db, fiat, signal_type):
        return []

    subject, body_email, body_html, body_wa = format_alert_message(
        signal_type, fiat, asset, target_price, ad, prediction, historical_avg
    )
    sent_channels: list[str] = []

    # 1. Correo electrónico (HTML + Texto plano)
    try:
        if await asyncio.to_thread(_send_email_sync, subject, body_email, body_html):
            sent_channels.append("email")
    except Exception as exc:
        print(f"[Error Email] {exc}")

    # 2. WhatsApp vía WAHA (preferido) o Twilio (fallback)
    wa_sent = False
    try:
        if await _send_waha_message(body_wa):
            sent_channels.append("whatsapp(waha)")
            wa_sent = True
    except Exception as exc:
        print(f"[Aviso WAHA] {exc}")

    if not wa_sent:
        try:
            if await _send_twilio_message(settings.TWILIO_WHATSAPP_FROM, settings.TWILIO_WHATSAPP_TO, body_wa):
                sent_channels.append("whatsapp(twilio)")
        except Exception:
            pass

    log = AlertLog(
        fiat=fiat.upper(),
        signal_type=signal_type,
        price=ad.price,
        channels_sent=",".join(sent_channels) if sent_channels else "db_only",
        message=body_email,
    )
    db.add(log)
    db.commit()

    return sent_channels


async def dispatch_arbitrage_alert(
    db: Session,
    fiat: str,
    asset: str,
    match: ArbitrageMatch,
) -> list[str]:
    signal_type = "ARBITRAGE_MATCH"
    if is_in_cooldown(db, fiat, signal_type):
        return []

    subject, body_email, body_html, body_wa = format_arbitrage_message(fiat, asset, match)
    sent_channels: list[str] = []

    # 1. Correo electrónico (HTML + Texto plano)
    try:
        if await asyncio.to_thread(_send_email_sync, subject, body_email, body_html):
            sent_channels.append("email")
    except Exception as exc:
        print(f"[Error Email Arbitraje] {exc}")

    # 2. WhatsApp vía WAHA
    wa_sent = False
    try:
        if await _send_waha_message(body_wa):
            sent_channels.append("whatsapp(waha)")
            wa_sent = True
    except Exception as exc:
        print(f"[Aviso WAHA Arbitraje] {exc}")

    if not wa_sent:
        try:
            if await _send_twilio_message(settings.TWILIO_WHATSAPP_FROM, settings.TWILIO_WHATSAPP_TO, body_wa):
                sent_channels.append("whatsapp(twilio)")
        except Exception:
            pass

    log = AlertLog(
        fiat=fiat.upper(),
        signal_type=signal_type,
        price=match.gain_per_usdt,
        channels_sent=",".join(sent_channels) if sent_channels else "db_only",
        message=body_email,
    )
    db.add(log)
    db.commit()

    return sent_channels
