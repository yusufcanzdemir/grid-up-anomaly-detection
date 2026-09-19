import paho.mqtt.client as mqtt
import json
import time
import random

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "factory/panel_anomali/telemetry"

def simulate_mqtt_data():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    print("MQTT üzerinden sahte veri gönderimi başladı (30 saniyede bir)...")
    counter = 0
    try:
        while True:
            counter += 1
            # Yapay zeka motoru, "tek saniyelik" sıçramaları (gürültü/parazit) filtrelediği için
            # anomalinin uzun sürmesi gerekiyor (AI kuralları genelde 15-30 dk izler).
            # 10 normal, 30 anomali şeklinde çalışacak:
            is_anomaly = (counter % 40) >= 10
            
            if is_anomaly:
                # Kritik (Alarm) üretecek yüksek akım ve sıcaklık değerleri (Sürekli aşırı yük)
                current = round(random.uniform(490.0, 520.0), 1)
                temp = round(random.uniform(130.0, 140.0), 1)
                print(f"[{counter}] ANOMALİ ÜRETİLDİ -> Akım: {current}A, Sıcaklık: {temp}°C")
            else:
                # Normal (Sağlıklı) çalışma değerleri
                current = round(random.uniform(150.0, 250.0), 1)
                temp = round(random.uniform(25.0, 35.0), 1)
                print(f"[{counter}] Normal Veri     -> Akım: {current}A, Sıcaklık: {temp}°C")

            # Yapay zekanın "5 dakikalık izleme" gibi süre bazlı kurallarını 
            # gerçekte beklemeden hızlıca test etmek için sahte zamanı hızlandırıyoruz:
            fake_time = time.time() + (counter * 60) # Her veri 1 dakika sonrasını taklit eder
            
            payload = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fake_time)),
                "site_id": "SITE-01",
                "panel_id": "P-001",
                "module_id": "M-001",
                "profile": "LV_PANEL",
                "current_l1_a": current,
                "current_l2_a": round(current * random.uniform(0.9, 1.1), 1),
                "current_l3_a": round(current * random.uniform(0.9, 1.1), 1),
                "temp_l1_c": temp,
                "temp_l2_c": temp,
                "temp_l3_c": temp,
                "temp_internal_c": temp - 10.0,
                "humidity_internal_pct": round(random.uniform(40.0, 60.0), 1)
            }
            
            client.publish(MQTT_TOPIC, json.dumps(payload))
            time.sleep(3)
            
    except KeyboardInterrupt:
        print("Simülasyon durduruldu.")
        client.disconnect()

if __name__ == "__main__":
    simulate_mqtt_data()

