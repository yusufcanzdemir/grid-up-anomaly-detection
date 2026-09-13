import json
import requests
from grid_up_anomaly_detection.config import config
from grid_up_anomaly_detection.communication.telegram.formatters import format_alarm_message
from grid_up_anomaly_detection.communication.telegram.ui import get_main_keyboard

BASE_URL = f"https://api.telegram.org/bot{config.TELEGRAM.BOT_TOKEN}"

def telegram_request(method, data=None):
    response = requests.post(f"{BASE_URL}/{method}", data=data, timeout=35)
    result = response.json()
    if not result.get("ok"):
        print(f"Telegram API hatası: {result.get('description')}")
    return result.get("result")

def send_telegram_alert(alarm):
    """Sistemde bir anomali çıktığında bu fonksiyon çağrılacak."""
    data = {
        "chat_id": config.TELEGRAM.CHAT_ID,
        "text": format_alarm_message(alarm),
        "reply_markup": json.dumps(get_main_keyboard(alarm.status))
    }
    return telegram_request("sendMessage", data)

def edit_message(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    return telegram_request("editMessageText", data)

def answer_callback(callback_query_id):
    return telegram_request(
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id},
    )

def get_updates(offset=None):
    data = {"timeout": 30}
    if offset is not None:
        data["offset"] = offset
    return telegram_request("getUpdates", data)