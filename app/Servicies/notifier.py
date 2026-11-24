import asyncio
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.Models.models import AlertLog
from app.Schemas.schemas import AdDetail, PredictionSide


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
) -> tuple[str, str]:
    action_title = "COMPRA BARATA (BAJÓ EL PRECIO)" if signal_type == "BUY_LOW" else "VENTA ALTA (SUBIÓ EL PRECIO)"
    subject = f"[Binance P2P] {action_title} {asset}/{fiat} a {ad.price:.2f} {fiat}"

    methods_str = ", ".join(ad.payment_methods) if ad.payment_methods else "No especificado"
    badge = "Verificado" if ad.is_verified_merchant else "Estándar"

    body = (
        f"ALERTA BINANCE P2P - {action_title}\n"
        f"Par: {asset}/{fiat}\n"
        f"Precio detectado: {ad.price:.2f} {fiat} (Objetivo: {target_price:.2f} {fiat})\n"
        f"Métodos de pago: {methods_str}\n"
        f"Límites del anuncio: Mín {ad.min_limit:,.2f} - Máx {ad.max_limit:,.2f} {fiat}\n"
        f"Monto sugerido a operar: {ad.suggested_amount_fiat:,.2f} {fiat} (~{ad.suggested_amount_asset:,.2f} {asset})\n"
        f"Liquidez disponible: {ad.available_asset:,.2f} {asset}\n"
        f"Comerciante: {ad.merchant_name} ({badge} | {ad.finish_rate_pct}% en {ad.month_orders} órdenes)\n"
        f"--- Análisis Predictivo ---\n"
        f"Tendencia: {prediction.trend or 'N/D'} | Z-Score: {prediction.z_score or 'N/D'}\n"
        f"Proyección 30m: {prediction.projected_next_30m or 'N/D'} {fiat} | 60m: {prediction.projected_next_60m or 'N/D'} {fiat}\n"
        f"Nota: {prediction.recommendation}\n"
        f"(Solo aviso automático. Verifica el anuncio dentro de la app oficial de Binance antes de operar.)"
    )
    return subject, body


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


async def _send_twilio_message(from_number: str, to_number: str, body: str) -> bool:
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
) -> list[str]:
    if is_in_cooldown(db, fiat, signal_type):
        return []

    subject, body = format_alert_message(signal_type, fiat, asset, target_price, ad, prediction)
    sent_channels: list[str] = []

    try:
        if await asyncio.to_thread(_send_email_sync, subject, body):
            sent_channels.append("email")
    except Exception as exc:
        print(f"[Error Email] {exc}")

    try:
        if await _send_twilio_message(settings.TWILIO_WHATSAPP_FROM, settings.TWILIO_WHATSAPP_TO, body):
            sent_channels.append("whatsapp")
    except Exception as exc:
        print(f"[Error WhatsApp] {exc}")

    try:
        if await _send_twilio_message(settings.TWILIO_SMS_FROM, settings.TWILIO_SMS_TO, body):
            sent_channels.append("sms")
    except Exception as exc:
        print(f"[Error SMS] {exc}")

    log = AlertLog(
        fiat=fiat.upper(),
        signal_type=signal_type,
        price=ad.price,
        channels_sent=",".join(sent_channels) if sent_channels else "db_only",
        message=body,
    )
    db.add(log)
    db.commit()

    return sent_channels