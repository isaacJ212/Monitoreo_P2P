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
) -> tuple[str, str, str]:
    is_buy = "BUY" in signal_type
    action_title = "COMPRA BARATA (PRECIO BAJO)" if is_buy else "VENTA CARA (PRECIO ALTO)"
    subject = f"[Binance P2P] 🔥 {action_title} {asset}/{fiat} a C${ad.price:.2f}"

    methods_str = ", ".join(ad.payment_methods) if ad.payment_methods else "No especificado"
    badge = "Verificado" if ad.is_verified_merchant else "Estándar"

    avg_text = f"Promedio histórico reciente: C${historical_avg:.2f} {fiat}\n" if historical_avg else ""

    body_email = (
        f"ALERTA P2P - {action_title}\n"
        f"====================================================\n"
        f"Par: {asset}/{fiat}\n"
        f"Precio detectado: C${ad.price:.2f} {fiat}\n"
        f"Meta fijada: C${target_price:.2f} {fiat}\n"
        f"{avg_text}"
        f"Comerciante: {ad.merchant_name} ({badge} | {ad.finish_rate_pct}% en {ad.month_orders} órdenes)\n"
        f"Límites: C${ad.min_limit:,.2f} - C${ad.max_limit:,.2f} {fiat}\n"
        f"Bancos disponibles: {methods_str}\n"
        f"----------------------------------------------------\n"
        f"Recomendación: {prediction.recommendation}\n"
        f"Enlace Binance: {ad.link}\n"
    )

    avg_wa = f"• Promedio histórico: *C${historical_avg:.2f}*\n" if historical_avg else ""
    body_whatsapp = (
        f"🔔 *ALERTA BINANCE P2P: {action_title}*\n"
        f"🪙 Par: *{asset}/{fiat}*\n"
        f"💵 Precio: *C${ad.price:.2f} {fiat}*\n"
        f"🎯 Meta: C${target_price:.2f} {fiat}\n"
        f"{avg_wa}"
        f"👤 Comerciante: *{ad.merchant_name}* ({ad.finish_rate_pct}%)\n"
        f"📊 Límites: C${ad.min_limit:,.0f} - C${ad.max_limit:,.0f}\n"
        f"💳 Bancos: {methods_str}\n"
        f"🔗 Abrir Binance: {ad.link}"
    )

    return subject, body_email, body_whatsapp


def format_arbitrage_message(fiat: str, asset: str, match: ArbitrageMatch) -> tuple[str, str, str]:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    subject = (
        f"[Binance P2P Arbitraje] 💰 Ganancia en {match.matched_bank}: +C${match.gain_per_usdt:.2f}/USDT "
        f"(+{match.spread_pct}%)"
    )

    body_email = (
        f"🏆 JUGADA GANADORA DETECTADA: {clean_asset}/{clean_fiat}\n"
        f"============================================================\n"
        f"BANCO COINCIDENTE: {match.matched_bank}\n"
        f"Ganancia por cada 1 USDT: +C${match.gain_per_usdt:.2f} {clean_fiat} (+{match.spread_pct}%)\n"
        f"Ganancia estimada por cada C$1,000 invertidos: +C${match.gain_per_1000_fiat:.2f} {clean_fiat}\n"
        f"------------------------------------------------------------\n"
        f"1. PASO COMPRA (PRECIO MÁS BAJO):\n"
        f"   - Comerciante: {match.buy_merchant}\n"
        f"   - Precio de Compra: C${match.buy_price:.2f} {clean_fiat}\n"
        f"   - Límites: C${match.buy_min_limit:,.0f} a C${match.buy_max_limit:,.0f} {clean_fiat}\n"
        f"   - Enlace: {match.buy_link}\n\n"
        f"2. PASO VENTA (PRECIO MÁS ALTO):\n"
        f"   - Comerciante: {match.sell_merchant}\n"
        f"   - Precio de Venta: C${match.sell_price:.2f} {clean_fiat}\n"
        f"   - Límites: C${match.sell_min_limit:,.0f} a C${match.sell_max_limit:,.0f} {clean_fiat}\n"
        f"   - Enlace: {match.sell_link}\n\n"
        f"Spread bruto por USDT: C${match.gross_spread:.2f} {clean_fiat}\n"
        f"============================================================\n"
        f"Ambos comerciantes operan con {match.matched_bank}."
    )

    body_whatsapp = (
        f"🏆 *¡JUGADA GANADORA P2P ({clean_asset}/{clean_fiat})!* 🚀\n"
        f"🏦 Banco coincidente: *{match.matched_bank}*\n"
        f"💰 *Ganancia: +C${match.gain_per_usdt:.2f} por USDT (+{match.spread_pct}%)*\n"
        f"💵 Ganas aprox: *+C${match.gain_per_1000_fiat:.2f} por cada C$1,000*\n"
        f"----------------------------------\n"
        f"🟢 *1. COMPRAR USDT BARATO:*\n"
        f"• Vendedor: *{match.buy_merchant}*\n"
        f"• Precio: *C${match.buy_price:.2f}*\n"
        f"• Límites: C${match.buy_min_limit:,.0f} - C${match.buy_max_limit:,.0f}\n\n"
        f"🔴 *2. VENDER USDT CARO:*\n"
        f"• Comprador: *{match.sell_merchant}*\n"
        f"• Precio: *C${match.sell_price:.2f}*\n"
        f"• Límites: C${match.sell_min_limit:,.0f} - C${match.sell_max_limit:,.0f}\n"
        f"----------------------------------\n"
        f"🔗 *P2P Binance:* {match.buy_link}"
    )

    return subject, body_email, body_whatsapp


def _send_email_sync(subject: str, body: str) -> bool:
    if not (settings.SMTP_USER and settings.SMTP_PASSWORD and settings.ALERT_EMAIL_TO):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USER
    msg["To"] = settings.ALERT_EMAIL_TO
    msg.set_content(body)

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

    async with httpx.AsyncClient(timeout=12.0) as client:
        res = await client.post(settings.WAHA_API_URL, json=payload, headers=headers)
        res.raise_for_status()
    return True


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

    subject, body_email, body_wa = format_alert_message(
        signal_type, fiat, asset, target_price, ad, prediction, historical_avg
    )
    sent_channels: list[str] = []

    # 1. Correo electrónico
    try:
        if await asyncio.to_thread(_send_email_sync, subject, body_email):
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

    subject, body_email, body_wa = format_arbitrage_message(fiat, asset, match)
    sent_channels: list[str] = []

    # 1. Correo electrónico
    try:
        if await asyncio.to_thread(_send_email_sync, subject, body_email):
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
