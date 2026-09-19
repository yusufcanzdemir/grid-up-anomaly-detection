import asyncio
import time
import requests
import threading
from pymodbus.server import StartAsyncTcpServer
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.datastore import ModbusDeviceContext as ModbusSlaveContext
from pymodbus import ModbusDeviceIdentification

# 100 modül için 3200 register (100 * 32)
store = ModbusSlaveContext(
    hr=ModbusSequentialDataBlock(1000, [0] * 3200),
    ir=ModbusSequentialDataBlock(1000, [0] * 3200)
)
context = ModbusServerContext(devices=store, single=True)

async def update_modbus_data():
    """Her saniye API'den (veya DB'den) veriyi okuyup Modbus belleğini günceller."""
    while True:
        try:
            # Tüm modülleri al
            modules_res = requests.get("http://localhost:8000/modules", timeout=2)
            if modules_res.status_code == 200:
                modules = modules_res.json().get("modules", [])
                
                # Her bir modül için SCADA verisini al ve Modbus belleğine yaz
                for idx, mod in enumerate(modules):
                    module_id = mod.get("module_id")
                    if not module_id:
                        continue
                        
                    scada_res = requests.get(f"http://localhost:8000/scada/{module_id}?module_index={idx}", timeout=2)
                    if scada_res.status_code == 200:
                        data = scada_res.json()
                        raw_registers = data.get("raw", [])
                        base_address = data.get("base_address", 1000 + (idx * 32))
                        
                        if raw_registers:
                            await context.async_setValues(0, 3, base_address, raw_registers)
                            await context.async_setValues(0, 4, base_address, raw_registers)
                            
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

