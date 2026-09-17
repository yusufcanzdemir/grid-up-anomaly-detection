import paho.mqtt.client as mqtt
import json
import time
import random

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "factory/panel_anomali/telemetry"

def simulate_mqtt_data():
    client = mqtt.Client()
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    print("MQTT üzerinden sahte veri gönderimi başladı (Her 3 saniyede 1)...")
    try:
        while True:
            # Kritik (Alarm) üretecek yüksek akım ve sıcaklık değerleri
            payload = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "site_id": "SITE-01",
                "panel_id": "P-001",
                "module_id": "M-001",
                "profile": "LV_PANEL",
                "current_l1_a": round(random.uniform(390.0, 420.0), 1),  # Yüksek Akım
                "current_l2_a": round(random.uniform(390.0, 420.0), 1),
                "current_l3_a": round(random.uniform(390.0, 420.0), 1),
                "temp_internal_c": round(random.uniform(65.0, 85.0), 1), # Yüksek Sıcaklık
                "humidity_internal_pct": round(random.uniform(40.0, 60.0), 1)
            }
            
            client.publish(MQTT_TOPIC, json.dumps(payload))
            print(f"Veri Gönderildi: {payload['current_l1_a']}A, {payload['temp_internal_c']}°C")
            time.sleep(3)
            
    except KeyboardInterrupt:
        print("Simülasyon durduruldu.")
        client.disconnect()

if __name__ == "__main__":
    simulate_mqtt_data()

