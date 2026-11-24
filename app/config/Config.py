from pydantic_settings import BaseSettings, SettingsConfigDict





class Settings(BaseException):
    Database_Url = str = "" 
    POLL_INTERVAL_MINUTES : int = 3
    ALERT_COOLDOWN_MINUTES : int = 20


    ## filtro de seguridad para tener buenos comerciantes 
    MIN_FINISH_RATE = 0.90
    MIN_MONTH_ORDERS= 10 
    ONLY_VERIFIED_MERCHANTS = bool = False


    ## configuracion del cprreo
    SMTP_HOST = str =  "smtp.gmail.com"
    SMTP_PORt = int = 587
    SMTP_USER = str = ""
    SMTP_PASSWORD = str = ""
    ALERT_EMAIL_TO = str= ""

    Model_Config = SettingsConfigDict(env_file=".env")



settings = Settings()


# reglas de moneda 


FIAT_RULES : dict[str, dict] = {
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