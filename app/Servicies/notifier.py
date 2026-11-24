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

    # Mensaje Correo
    body_email = (
        f"ALERTA INTELIGENTE BINANCE P2P - {action_title}\n"
        f"====================================================\n"
        f"Par: {asset}/{fiat}\n"
        f"Precio detectado: C${ad.price:.2f} {fiat}\n"
        f"Meta configurada: C${target_price:.2f} {fiat}\n"
        f"{avg_text}"
        f"Comerciante: {ad.merchant_name} ({badge} | {ad.finish_rate_pct}% en {ad.month_orders} órdenes)\n"
        f"Límites de compra: C${ad.min_limit:,.2f} - C${ad.max_limit:,.2f} {fiat}\n"
        f"Monto sugerido: C${ad.suggested_amount_fiat:,.2f} {fiat} (~{ad.suggested_amount_asset:,.2f} {asset})\n"
        f"Métodos de pago: {methods_str}\n"
        f"----------------------------------------------------\n"
        f"Tendencia: {prediction.trend or 'N/D'} | Z-Score: {prediction.z_score or 'N/D'}\n"
        f"Proyección 30m: {prediction.projected_next_30m or 'N/D'} | 60m: {prediction.projected_next_60m or 'N/D'}\n"
        f"Recomendación: {prediction.recommendation}\n"
        f"Enlace Binance: {ad.link}\n"
    )

    # Mensaje WhatsApp
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
        f"📈 Proyección 30m: C${prediction.projected_next_30m or 'N/D'}\n"
        f"🔗 Abrir Binance: {ad.link}"
    )

    return subject, body_email, body_whatsapp


def format_arbitrage_message(fiat: str, asset: str, match: ArbitrageMatch) -> tuple[str, str, str]:
    clean_fiat = fiat.upper()
    clean_asset = asset.upper()

    subject = (
        f"[Binance P2P Arbitraje] 💰 Ganancia Estimada: +C${match.net_profit_fiat:,.2f} {clean_fiat} "
        f"(+{match.net_profit_pct}%)"
    )

    common_bancos = ", ".join(match.common_payment_methods) if match.common_payment_methods else "Transferencia / Distintos bancos"

    body_email = (
        f"🚀 MATCH DE ARBITRAJE DETECTADO: {clean_asset}/{clean_fiat}\n"
        f"============================================================\n"
        f"GANANCIA NETA ESTIMADA: +C${match.net_profit_fiat:,.2f} {clean_fiat} (+{match.net_profit_pct}% ROI)\n"
        f"Capital base simulado: C${match.simulated_budget:,.2f} {clean_fiat}\n"
        f"USDT comprados estimados: {match.usdt_obtained} {clean_asset}\n"
        f"Retorno estimado en venta: C${match.fiat_returned:,.2f} {clean_fiat}\n"
        f"------------------------------------------------------------\n"
        f"1. PASO COMPRA (PRECIO MÁS BAJO):\n"
        f"   - Comerciante: {match.buy_merchant}\n"
        f"   - Precio de Compra: C${match.buy_price:.2f} {clean_fiat}\n"
        f"   - Límites: C${match.buy_min_limit:,.0f} a C${match.buy_max_limit:,.0f} {clean_fiat}\n"
        f"   - Bancos: {', '.join(match.buy_payment_methods)}\n"
        f"   - Enlace: {match.buy_link}\n\n"
        f"2. PASO VENTA (PRECIO MÁS ALTO):\n"
        f"   - Comerciante: {match.sell_merchant}\n"
        f"   - Precio de Venta: C${match.sell_price:.2f} {clean_fiat}\n"
        f"   - Límites: C${match.sell_min_limit:,.0f} a C${match.sell_max_limit:,.0f} {clean_fiat}\n"
        f"   - Bancos: {', '.join(match.sell_payment_methods)}\n"
        f"   - Enlace: {match.sell_link}\n\n"
        f"Bancos compatibles entre ambas partes: {common_bancos}\n"
        f"Spread bruto por USDT: C${match.gross_spread:.2f} {clean_fiat}\n"
        f"============================================================\n"
        f"Recuerda verificar liquidez y realizar la transacción dentro de la app oficial de Binance."
    )

    body_whatsapp = (
        f"💰 *¡OPORTUNIDAD DE ARBITRAJE {clean_asset}/{clean_fiat}!* 🚀\n"
        f"*Ganancia Estimada: +C${match.net_profit_fiat:,.2f} NIO (+{match.net_profit_pct}%)*\n"
        f"💵 Capital simulado: C${match.simulated_budget:,.0f} {clean_fiat}\n"
        f"----------------------------------\n"
        f"🟢 *1. COMPRAR USDT BARATO:*\n"
        f"• Vendedor: *{match.buy_merchant}*\n"
        f"• Precio: *C${match.buy_price:.2f}*\n"
        f"• Límites: C${match.buy_min_limit:,.0f} - C${match.buy_max_limit:,.0f}\n"
        f"• Bancos: {', '.join(match.buy_payment_methods[:3])}\n\n"
        f"🔴 *2. VENDER USDT CARO:*\n"
        f"• Comprador: *{match.sell_merchant}*\n"
        f"• Precio: *C${match.sell_price:.2f}*\n"
        f"• Límites: C${match.sell_min_limit:,.0f} - C${match.sell_max_limit:,.0f}\n"
        f"• Bancos: {', '.join(match.sell_payment_methods[:3])}\n"
        f"----------------------------------\n"
        f"🏦 *Bancos coincidentes:* {common_bancos}\n"
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
    historical_avg: float | None = None,
) -> list[str]:
    if is_in_cooldown(db, fiat, signal_type):
        return []

    subject, body_email, body_wa = format_alert_message(
        signal_type, fiat, asset, target_price, ad, prediction, historical_avg
    )
    sent_channels: list[str] = []

    try:
        if await asyncio.to_thread(_send_email_sync, subject, body_email):
            sent_channels.append("email")
    except Exception as exc:
        print(f"[Error Email] {exc}")

    try:
        if await _send_twilio_message(settings.TWILIO_WHATSAPP_FROM, settings.TWILIO_WHATSAPP_TO, body_wa):
            sent_channels.append("whatsapp")
    except Exception as exc:
        print(f"[Error WhatsApp] {exc}")

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

    try:
        if await asyncio.to_thread(_send_email_sync, subject, body_email):
            sent_channels.append("email")
    except Exception as exc:
        print(f"[Error Email Arbitraje] {exc}")

    try:
        if await _send_twilio_message(settings.TWILIO_WHATSAPP_FROM, settings.TWILIO_WHATSAPP_TO, body_wa):
            sent_channels.append("whatsapp")
    except Exception as exc:
        print(f"[Error WhatsApp Arbitraje] {exc}")

    log = AlertLog(
        fiat=fiat.upper(),
        signal_type=signal_type,
        price=match.net_profit_fiat,
        channels_sent=",".join(sent_channels) if sent_channels else "db_only",
        message=body_email,
    )
    db.add(log)
    db.commit()

    return sent_channels
