import threading
import asyncio
import uvicorn
from grid_up_anomaly_detection.communication.telegram.listener import start_telegram_listener
from grid_up_anomaly_detection.modbus_server import run_server

def start_modbus():
    asyncio.run(run_server())

if __name__ == "__main__":
    print("🚀 Grid Up Anomaly Detection Sistemi Başlatılıyor...")
    
    # Telegram Listener (Arka Plan)
    listener_thread = threading.Thread(target=start_telegram_listener, daemon=True)
    listener_thread.start()
    
    # Modbus Server (Arka Plan)
    modbus_thread = threading.Thread(target=start_modbus, daemon=True)
    modbus_thread.start()
    
    # FastAPI & AI Engine (Ana Thread)
    print("🌐 FastAPI AI Servisi 8000 portunda başlatılıyor...")
    try:
        uvicorn.run("grid_up_anomaly_detection.ai.service.app:app", host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        print("\nSistem kapatılıyor...")