import threading
import time
from grid_up_anomaly_detection.models import Alarm, AlarmStatus
from grid_up_anomaly_detection.communication.telegram.bot import send_telegram_alert
from grid_up_anomaly_detection.communication.telegram.listener import start_telegram_listener, ACTIVE_ALARMS

def simulate_alarm():
    # 1. Sahte bir alarm objesi oluştur
    fake_alarm = Alarm(
        id=101,
        panel="TR-01 Ana Dağıtım Panosu",
        location="Trafo Merkezi",
        error="Aşırı Isınma Tespit Edildi",
        temperature=85.0,
        voltage=400.0,
        current=120.0,
        fan=False,
        humidity=45,
        status=AlarmStatus.CRITICAL
    )

    print("Telegram'a test alarmı gönderiliyor...")
    
    # 2. Alarmı gönder
    response = send_telegram_alert(fake_alarm)
    
    if response:
        # 3. Dinleyicinin mesajı tanıması için ACTIVE_ALARMS sözlüğüne ekle
        message_id = response["message_id"]
        ACTIVE_ALARMS[message_id] = fake_alarm
        print(f"Alarm gönderildi (Mesaj ID: {message_id})! Lütfen Telegram'ı kontrol et ve butonlara bas.")
    else:
        print("Hata: Alarm gönderilemedi. Lütfen .env dosyasındaki Token ve Chat ID'yi kontrol et.")

if __name__ == "__main__":
    # Önce alarmı yolla
    simulate_alarm()
    
    # Sonra senin tıklamalarını dinlemesi için dinleyiciyi başlat
    start_telegram_listener()
