from grid_up_anomaly_detection.models import AlarmStatus

def get_main_keyboard(status):
    # Kritik veya Çözülemedi durumlarında "Görevi Üstlen" butonu çıksın
    if status in (AlarmStatus.CRITICAL, AlarmStatus.NOT_RESOLVED):
        return {
            "inline_keyboard": [
                [{"text": "🛠 Görevi Üstlen", "callback_data": "take_task"}]
            ]
        }
        
    # Görev üstlenildiğinde çözüm seçenekleri çıksın
    if status == AlarmStatus.ACKNOWLEDGED:
        return {
            "inline_keyboard": [
                [{"text": "✅ Çözüldü", "callback_data": "resolved"}],
                [{"text": "❌ Çözülmedi", "callback_data": "not_resolved"}],
                [{"text": "🚫 Yanlış İhbar", "callback_data": "false_alarm"}],
            ]
        }
    
    # Eylem sonlandığında (Çözüldü/Yanlış İhbar) butonları gizle
    return {"inline_keyboard": []}
