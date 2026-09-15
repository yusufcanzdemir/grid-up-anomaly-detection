from grid_up_anomaly_detection.communication.telegram.bot import get_updates, answer_callback, edit_message
from grid_up_anomaly_detection.communication.telegram.formatters import format_alarm_message
from grid_up_anomaly_detection.communication.telegram.ui import get_main_keyboard
from grid_up_anomaly_detection.models import AlarmStatus

ACTIVE_ALARMS = {}

def notify_backend(alarm, action):
    """
    Backend ile iletişim fonksiyonu.
    Şu an için mock log bırakıyor, gerçek projede API çağrısı (requests.post vb.) yapılır.
    """
    print(f"[BACKEND İLETİŞİMİ] Backend'e iletiliyor -> Alarm ID: {alarm.id} | Aksiyon: '{action}' | Yeni Durum: {alarm.status.value}")

def update_alarm_message(chat_id, message_id, alarm):
    edit_message(
        chat_id=chat_id,
        message_id=message_id,
        text=format_alarm_message(alarm),
        reply_markup=get_main_keyboard(alarm.status),
    )

def handle_callback(callback_query):
    callback_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]
    action = callback_query["data"]
    
    answer_callback(callback_id)

    if message_id not in ACTIVE_ALARMS:
        print(f"Uyarı: {message_id} ID'li mesaj için aktif alarm bulunamadı veya süresi doldu!")
        return
        
    alarm = ACTIVE_ALARMS[message_id] 

    if action == "take_task":
        alarm.status = AlarmStatus.ACKNOWLEDGED
        update_alarm_message(chat_id, message_id, alarm)
        notify_backend(alarm, action)
        
    elif action == "resolved":
        alarm.status = AlarmStatus.RESOLVED
        update_alarm_message(chat_id, message_id, alarm)
        notify_backend(alarm, action)
        
    elif action == "not_resolved":
        alarm.status = AlarmStatus.NOT_RESOLVED
        update_alarm_message(chat_id, message_id, alarm)
        notify_backend(alarm, action)
        
    elif action == "false_alarm":
        alarm.status = AlarmStatus.FALSE_ALARM
        update_alarm_message(chat_id, message_id, alarm)
        notify_backend(alarm, action)

def start_telegram_listener():
    """Telegram'dan gelen buton tıklamalarını dinler."""
    offset = None
    print("Telegram butonu dinleyicisi başlatıldı...")
    
    while True:
        try:
            updates = get_updates(offset)
            if updates:
                for update in updates:
                    offset = update["update_id"] + 1
                    if "callback_query" in update:
                        handle_callback(update["callback_query"])
        except Exception as e:
            print(f"Telegram dinleme hatası: {e}")
            pass
