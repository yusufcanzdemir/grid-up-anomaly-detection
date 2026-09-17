from grid_up_anomaly_detection.models import AlarmStatus

def format_alarm_message(alarm):
    workflow_text = {
        AlarmStatus.CRITICAL: "🔴 Beklemede (Müdahale Edilmedi)",
        AlarmStatus.ACKNOWLEDGED: "🟡 Görev Üstlenildi",
        AlarmStatus.RESOLVED: "🟢 Çözüldü",
        AlarmStatus.NOT_RESOLVED: "❌ Çözülmedi",
        AlarmStatus.FALSE_ALARM: "🚫 Yanlış İhbar",
    }

    ai_level = alarm.ai_status.upper() if alarm.ai_status else "BİLİNMİYOR"
    title_icon = "🔴" if ai_level == "CRITICAL" else "🟠" if ai_level == "WARNING" else "🚨"

    message = f"""{title_icon} YAPAY ZEKA TESPİTİ: {ai_level}

Pano: {alarm.panel}
Konum: {alarm.location}

⏱ Görev Durumu: {workflow_text.get(alarm.status, "BİLİNMİYOR")}
"""
    if alarm.suspected_condition:
        message += f"🔍 Yapay Zeka Teşhisi: {alarm.suspected_condition}\n"
    
    if alarm.reasons:
        message += "⚠️ Tespit Edilen Nedenler:\n"
        for r in alarm.reasons:
            message += f"  - {r}\n"
            
    if alarm.ai_status:
        message += f"📊 AI Risk Seviyesi: {alarm.ai_status}\n"
        
    return message
