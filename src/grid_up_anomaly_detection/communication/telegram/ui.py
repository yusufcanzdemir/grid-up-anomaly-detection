from grid_up_anomaly_detection.models import AlarmStatus

def get_main_keyboard(status):
    if status == AlarmStatus.CRITICAL:
        return {
            "inline_keyboard": [
                [{"text": "🔎 Detaylar", "callback_data": "details"}, {"text": "🛠 Çözüm Önerisi", "callback_data": "solution"}],
                [{"text": "📊 Sensörler", "callback_data": "sensors"}, {"text": "✅ Alarmı Üstlen", "callback_data": "acknowledge"}]
            ]
        }
    if status == AlarmStatus.ACKNOWLEDGED:
        return {
            "inline_keyboard": [
                [{"text": "🔎 Detaylar", "callback_data": "details"}, {"text": "🛠 Çözüm Önerisi", "callback_data": "solution"}],
                [{"text": "📊 Sensörler", "callback_data": "sensors"}, {"text": "🟢 Alarmı Çözüldü Olarak İşaretle", "callback_data": "resolve"}]
            ]
        }
    return {"inline_keyboard": [[{"text": "🔎 Alarm Detayı", "callback_data": "details"}]]}