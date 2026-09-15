from grid_up_anomaly_detection.models import AlarmStatus

def format_alarm_message(alarm):
    status_text = {
        AlarmStatus.CRITICAL: "🔴 KRİTİK ALARM",
        AlarmStatus.ACKNOWLEDGED: "🟡 GÖREV ÜSTLENİLDİ",
        AlarmStatus.RESOLVED: "🟢 ÇÖZÜLDÜ",
        AlarmStatus.NOT_RESOLVED: "❌ ÇÖZÜLMEDİ",
        AlarmStatus.FALSE_ALARM: "🚫 YANLIŞ İHBAR",
    }

    # Veri ihlalini önlemek için sadece gerekli minimum bilgileri veriyoruz
    return f"""🚨 PANO ARIZA ALARMI

Pano: {alarm.panel}
Konum: {alarm.location}

⏱ Durum: {status_text.get(alarm.status, "BİLİNMİYOR")}
"""
