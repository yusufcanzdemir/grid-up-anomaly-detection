import os

from dotenv import load_dotenv

load_dotenv()


######
def _csv(name: str, default: str = "") -> list[str]:
    """Virgul veya noktali virgulle ayrilmis liste = temizlenmis liste."""
    raw = os.getenv(name, default) or ""
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]




class TelegramConfig:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class EmailConfig:
    GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
    GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
    GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
    GMAIL_SENDER_ADDRESS = os.getenv("GMAIL_SENDER_ADDRESS")
    RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", os.getenv("GMAIL_SENDER_ADDRESS"))


######
class SmsConfig:
    """SMS gateway. Varsayilan `http`: operator kurumsal gateway'i / sirket ici SMS sunucusu.

    Alan adlari degiskenle veriliyor cunku her operatorun gateway'i farkli isim kullaniyor.
    Hicbiri set edilmezse kanal dry-run calisir (bkz. base_notifier.dry_run).
    """
    PROVIDER = (os.getenv("SMS_PROVIDER", "http") or "http").lower()
    RECIPIENTS = os.getenv("SMS_RECIPIENTS", "")
    SENDER = os.getenv("SMS_SENDER", "")

    GATEWAY_URL = os.getenv("SMS_GATEWAY_URL", "")
    USERNAME = os.getenv("SMS_USERNAME", "")
    PASSWORD = os.getenv("SMS_PASSWORD", "")
    AUTH_HEADER = os.getenv("SMS_AUTH_HEADER", "")
    FIELD_TO = os.getenv("SMS_FIELD_TO", "to")
    FIELD_TEXT = os.getenv("SMS_FIELD_TEXT", "message")
    FIELD_USER = os.getenv("SMS_FIELD_USER", "username")
    FIELD_PASS = os.getenv("SMS_FIELD_PASS", "password")
    FIELD_FROM = os.getenv("SMS_FIELD_FROM", "from")

    MODEM_PORT = os.getenv("SMS_MODEM_PORT", "")
    MODEM_BAUD = int(os.getenv("SMS_MODEM_BAUD", "115200"))

    def recipient_list(self) -> list[str]:
        return _csv("SMS_RECIPIENTS")


class WhatsAppConfig:
    """WhatsApp Business Cloud API. Varsayilan KAPALI - bkz. whatsapp/cloud_api.py aciklamasi."""
    ENABLED = (os.getenv("WHATSAPP_ENABLED", "false") or "false").lower() in ("1", "true", "yes", "evet")
    TOKEN = os.getenv("WHATSAPP_TOKEN", "")
    PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    RECIPIENTS = os.getenv("WHATSAPP_RECIPIENTS", "")
    API_BASE = os.getenv("WHATSAPP_API_BASE", "https://graph.facebook.com")
    API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")

    def recipient_list(self) -> list[str]:
        return _csv("WHATSAPP_RECIPIENTS")




class AppConfig:
    TELEGRAM = TelegramConfig()
    EMAIL = EmailConfig()
    ######
    SMS = SmsConfig()
    WHATSAPP = WhatsAppConfig()

config = AppConfig()
