import time
import random
import threading
from grid_up_anomaly_detection.analysis.detector import analyze_sensor_data, on_anomaly_detected
from grid_up_anomaly_detection.communication.telegram.listener import start_telegram_listener, ACTIVE_ALARMS

def simulate_scada_data_stream():
    print("SCADA Veri Okuma Simülasyonu Başladı...")
    panel_isimleri = ["MCC-01", "MCC-02", "TRF-01"]
    
    while True:
        sensor_data = {
            "panel": random.choice(panel_isimleri),
            "location": "Ana Üretim Hattı",
            "temperature": round(random.uniform(40.0, 85.0), 1),
            "voltage": round(random.uniform(380.0, 410.0), 1),
            "current": round(random.uniform(10.0, 20.0), 1),
            "fan_status": random.choice([True, True, False]),
            "humidity": random.randint(30, 65)
        }
        
        alarm_objesi, msg_id = analyze_sensor_data(sensor_data)
        
        if alarm_objesi and msg_id:
            ACTIVE_ALARMS[msg_id] = alarm_objesi
            print(f"Alarm hafızaya eklendi (Mesaj ID: {msg_id})")
        
        time.sleep(10)

if __name__ == "__main__":
    listener_thread = threading.Thread(target=start_telegram_listener, daemon=True)
    listener_thread.start()

    try:
        simulate_scada_data_stream()
    except KeyboardInterrupt:
        print("\nSistem kapatılıyor...")