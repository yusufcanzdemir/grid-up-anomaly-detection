import asyncio
import time
import requests
import threading
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext
from pymodbus import ModbusDeviceIdentification

# AI API'den (veya DB'den) veri çekilecek endpoint (Örn: Pano 1)
SCADA_API_URL = "http://localhost:8000/scada/M-001"

store = ModbusSlaveContext(
    hr=ModbusSequentialDataBlock(1000, [0] * 32),
    ir=ModbusSequentialDataBlock(1000, [0] * 32)
)
context = ModbusServerContext(devices=store, single=True)

async def update_modbus_data():
    """Her saniye API'den (veya DB'den) veriyi okuyup Modbus belleğini günceller."""
    while True:
        try:
            # Not: requests senkron bir kütüphane olsa da arka planda küçük bir veri çektiği için 
            # asenkron döngüyü çok yormayacaktır. Daha büyük projelerde aiohttp tercih edilebilir.
            response = requests.get(SCADA_API_URL, timeout=2)
            if response.status_code == 200:
                data = response.json()
                raw_registers = data.get("raw", [])
                
                if raw_registers:
                    # Modbus Slave 0 (single=True olduğu için id 0), Input(3) ve Holding(4) Register
                    await context.async_setValues(0, 3, 1000, raw_registers)
                    await context.async_setValues(0, 4, 1000, raw_registers)
                    print(f"Modbus verileri güncellendi: {raw_registers[:5]}...")
        except requests.exceptions.ConnectionError:
            pass # API Kapalı, hatayı yut
        except Exception as e:
            print(f"Modbus güncelleme hatası: {e}")
        
        await asyncio.sleep(2) # 2 saniyede bir güncelle

async def run_server():
    print("Modbus TCP Server 5020 portunda başlatılıyor...")
    identity = ModbusDeviceIdentification()
    identity.VendorName = 'Gdz Hackathon'
    identity.ProductCode = 'PM'
    identity.VendorUrl = 'http://github.com/orgs/gdz'
    identity.ProductName = 'Pano Anomali Modbus Server'
    identity.ModelName = 'Modbus TCP Node'
    identity.MajorMinorRevision = '1.0'

    # Arka planda veri güncelleyiciyi başlat
    asyncio.create_task(update_modbus_data())

    # Modbus TCP Server başlat (0.0.0.0 = Tüm IP'lere açık, Port 5020)
    await StartAsyncTcpServer(context=context, identity=identity, address=("0.0.0.0", 5020))

if __name__ == "__main__":
    asyncio.run(run_server())

