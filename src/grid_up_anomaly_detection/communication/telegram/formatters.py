from grid_up_anomaly_detection.models import AlarmStatus

def format_alarm_message(alarm):
    status_text = {
        AlarmStatus.CRITICAL: "🔴 KRİTİK",
        AlarmStatus.ACKNOWLEDGED: "🟡 İNCELENİYOR",
        AlarmStatus.RESOLVED: "🟢 ÇÖZÜLDÜ",
    }
    fan_status = "Çalışıyor" if alarm.fan else "Çalışmıyor"

    return f"""🚨 PANO ARIZA ALARMI

Pano: {alarm.panel}
Konum: {alarm.location}

Arıza: {alarm.error}

🌡 Sıcaklık: {alarm.temperature} °C
⚡ Gerilim: {alarm.voltage} V
🔌 Akım: {alarm.current} A
🌀 Fan: {fan_status}
💧 Nem: {alarm.humidity} %

⏱ Durum: {status_text[alarm.status]}

Müdahale gerekiyor.
"""

def get_details(alarm):
    return f"🔎 ALARM DETAYI\n\nAlarm ID: {alarm.id}\nPano: {alarm.panel}\nKonum: {alarm.location}\n\nArıza: {alarm.error}\nDurum: {alarm.status.value}"

def get_sensors(alarm):
    fan_status = "Çalışıyor" if alarm.fan else "Çalışmıyor"
    return f"📊 SENSÖR VERİLERİ\n\n🌡 Sıcaklık: {alarm.temperature} °C\n💧 Nem: {alarm.humidity} %\n⚡ Gerilim: {alarm.voltage} V\n🔌 Akım: {alarm.current} A\n🌀 Fan: {fan_status}"

def get_solution(alarm):
    return f"🛠 ÇÖZÜM ÖNERİSİ\n\nPano: {alarm.panel}\nArıza: {alarm.error}\n\n1. Fan bağlantısını kontrol edin.\n2. Pano içi sıcaklık değerini kontrol edin.\n\n⚠️ Müdahale öncesi gerekli iş güvenliği prosedürlerini uygulayın."