import json
import time
import requests
import psycopg2
import paho.mqtt.client as mqtt
from grid_up_anomaly_detection.models import Alarm, AlarmStatus
from grid_up_anomaly_detection.communication.telegram.bot import send_telegram_alert
from grid_up_anomaly_detection.communication.telegram.listener import ACTIVE_ALARMS
import threading
from grid_up_anomaly_detection.communication.telegram.listener import start_telegram_listener

# Veritabanı (TimescaleDB) Ayarları
DB_CONFIG = {
    "dbname": "gridup",
    "user": "admin",
    "password": "adminpassword",
    "host": "localhost",
    "port": "5432"
}

# MQTT Ayarları
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "factory/panel_anomali/telemetry"

# AI Backend API (Kişi 1'in yazdığı FastAPI)
API_URL = "http://localhost:9090/ingest"

def init_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Basit bir sensör tablosu oluştur
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                module_id VARCHAR(50) NOT NULL,
                current_l1_a FLOAT,
                temp_internal_c FLOAT,
                humidity_internal_pct FLOAT,
                risk_score INT,
                status_code INT
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Veritabanı tablosu hazır.")
    except Exception as e:
        print(f"Veritabanı bağlantı hatası: {e}")

def on_connect(client, userdata, flags, rc):
    print(f"MQTT Broker'a bağlanıldı (Sonuç Kodu: {rc})")
    client.subscribe(MQTT_TOPIC)
    print(f"{MQTT_TOPIC} dinleniyor...")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"Yeni Veri Geldi: {payload.get('module_id')}")
        
        # 1. Kişi 1'in yazdığı AI API'sine gönder
        response = requests.post(API_URL, json=payload)
        if response.status_code == 200:
            ai_result = response.json()
            risk_score = ai_result.get("risk_score", 0)
            status_code = ai_result.get("status_code", 0)
            print(f"AI Analizi -> Risk Skoru: {risk_score} | Status Code: {status_code}")
            
            # 2. Alarm kontrolü (Durum Makinesi / Telegram)
            if status_code >= 2: # 2 = WARNING, 3 = CRITICAL
                alarm = Alarm(
                    id=int(time.time()),
                    panel=payload.get("panel_id", "P-Bilinmeyen"),
                    location=payload.get("site_id", "Bilinmeyen Saha"),
                    error=ai_result.get("condition_code", "Bilinmeyen Hata"),
                    temperature=payload.get("temp_internal_c", 0.0),
                    voltage=400.0,
                    current=payload.get("current_l1_a", 0.0),
                    fan=False,
                    humidity=payload.get("humidity_internal_pct", 0)
                )
                
                # Telegram mesajı gönder ve hafızaya al
                result = send_telegram_alert(alarm)
                if result:
                    ACTIVE_ALARMS[result.get("message_id")] = alarm
                    print(f"Telegram alarmı oluşturuldu: {alarm.error}")
            
            # 3. Veritabanına kaydet
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sensor_data 
                (timestamp, module_id, current_l1_a, temp_internal_c, humidity_internal_pct, risk_score, status_code)
                VALUES (NOW(), %s, %s, %s, %s, %s, %s)
            """, (payload.get('module_id'), payload.get('current_l1_a'), payload.get('temp_internal_c'), 
                  payload.get('humidity_internal_pct'), risk_score, status_code))
            conn.commit()
            cur.close()
            conn.close()

    except Exception as e:
        print(f"Veri işlenirken hata oluştu: {e}")

if __name__ == "__main__":
    init_db()
    
    # Telegram Listener'ı arka planda başlat
    listener_thread = threading.Thread(target=start_telegram_listener, daemon=True)
    listener_thread.start()
    
    # MQTT İstemcisi Başlat
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("Sistem kapatılıyor...")

