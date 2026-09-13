import os
from dotenv import load_dotenv

load_dotenv()

class TelegramConfig:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class EmailConfig:
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = os.getenv("SMTP_PORT")
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

class AppConfig:
    TELEGRAM = TelegramConfig()
    EMAIL = EmailConfig()
    # SCADA_URL = ...
    # DB_CONNECTION_STRING = ...

config = AppConfig()