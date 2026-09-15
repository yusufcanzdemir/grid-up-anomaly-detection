from grid_up_anomaly_detection.models import Alarm, AlarmStatus
from grid_up_anomaly_detection.communication.telegram.bot import send_telegram_alert
import time

def on_anomaly_detected(sensor_data, error_reason):
    print(f"⚠️ ANOMALİ TESPİT EDİLDİ: {error_reason}")
    
    alarm = Alarm(
        id=int(time.time()),
        panel=sensor_data.get("panel", "Bilinmeyen Pano"),
        location=sensor_data.get("location", "Bilinmeyen Konum"),
        error=error_reason,
        temperature=sensor_data.get("temperature", 0.0),
        voltage=sensor_data.get("voltage", 0.0),
        current=sensor_data.get("current", 0.0),
        fan=sensor_data.get("fan_status", False),
        humidity=sensor_data.get("humidity", 0)
    )

    try:
        result = send_telegram_alert(alarm)
        print("Telegram bildirimi başarıyla gönderildi.")
        return alarm, result.get("message_id")
    except Exception as e:
        print(f"Telegram bildirimi gönderilemedi: {e}")
        return None, None

def analyze_sensor_data(sensor_data):
    if sensor_data["temperature"] > 80.0 and not sensor_data["fan_status"]:
        return on_anomaly_detected(sensor_data, "Aşırı sıcaklık ve fan arızası!")
    
    elif sensor_data["current"] > 15.0:
        return on_anomaly_detected(sensor_data, "Yüksek akım çekimi (Aşırı yük)!")
        
    return None, None