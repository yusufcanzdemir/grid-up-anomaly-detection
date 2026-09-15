import os
from dotenv import load_dotenv

load_dotenv()

class TelegramConfig:
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

class EmailConfig:
    GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
    GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
    GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
    GMAIL_SENDER_ADDRESS = os.getenv("GMAIL_SENDER_ADDRESS")
    RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", os.getenv("GMAIL_SENDER_ADDRESS"))

class AppConfig:
    TELEGRAM = TelegramConfig()
    EMAIL = EmailConfig()

config = AppConfig()
