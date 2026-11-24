from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./p2p_monitor.db"
    POLL_INTERVAL_MINUTES: int = 3
    ALERT_COOLDOWN_MINUTES: int = 20

    # Filtro de seguridad para comerciantes
    MIN_FINISH_RATE: float = 0.90
    MIN_MONTH_ORDERS: int = 10
    ONLY_VERIFIED_MERCHANTS: bool = False

    # Configuración de correo SMTP (Gmail u otro)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ALERT_EMAIL_TO: str = ""

    # Configuración de WAHA (WhatsApp HTTP API)
    WAHA_API_URL: str = "http://localhost:3008/api/sendText"
    WAHA_SESSION: str = "default"
    WAHA_API_KEY: str = ""
    WAHA_CHAT_ID: str = ""  # Ej: 50588888888@c.us o número telefónico

    # Configuración de Twilio (opcional como fallback)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = ""
    TWILIO_WHATSAPP_TO: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()


# Reglas de moneda por defecto
FIAT_RULES: dict[str, dict] = {
    "NIO": {
        "asset": "USDT",
        "buy_target": 36.80,
        "sell_target": 40.00,
        "budget": 2000.0,
        "pay_types": [],
        "enabled": True,
    },
    "USD": {
        "asset": "USDT",
        "buy_target": 1.00,
        "sell_target": 1.02,
        "budget": 150.0,
        "pay_types": [],
        "enabled": False,
    },
}
