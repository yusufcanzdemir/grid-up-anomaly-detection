import base64
import requests
from email.mime.text import MIMEText
from grid_up_anomaly_detection.config import config
from grid_up_anomaly_detection.models import AlarmStatus

def refresh_access_token():
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": config.EMAIL.GMAIL_CLIENT_ID,
        "client_secret": config.EMAIL.GMAIL_CLIENT_SECRET,
        "refresh_token": config.EMAIL.GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token"
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json().get("access_token")

def send_gmail(subject, body):
    if not all([config.EMAIL.GMAIL_CLIENT_ID, config.EMAIL.GMAIL_CLIENT_SECRET, config.EMAIL.GMAIL_REFRESH_TOKEN]):
        print("Uyarı: Gmail ayarları eksik. Mail gönderilemiyor.")
        return

    try:
        access_token = refresh_access_token()
    except Exception as e:
        print(f"Gmail token yenileme hatası: {e}")
        return

    message = MIMEText(body)
    message["to"] = config.EMAIL.RECIPIENT_EMAIL
    message["from"] = config.EMAIL.GMAIL_SENDER_ADDRESS
    message["subject"] = subject

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, headers=headers, json={"raw": raw_message})
        response.raise_for_status()
        print("E-posta başarıyla gönderildi!")
    except Exception as e:
        print(f"Gmail gönderme hatası: {e}")

def notify_email(alarm, is_update=False):
    status_text = {
        AlarmStatus.CRITICAL: "🔴 KRİTİK ALARM",
        AlarmStatus.ACKNOWLEDGED: "🟡 GÖREV ÜSTLENİLDİ",
        AlarmStatus.RESOLVED: "🟢 ÇÖZÜLDÜ",
        AlarmStatus.NOT_RESOLVED: "❌ ÇÖZÜLMEDİ",
        AlarmStatus.FALSE_ALARM: "🚫 YANLIŞ İHBAR",
    }
    
    status_msg = status_text.get(alarm.status, "BİLİNMİYOR")
    
    if not is_update:
        subject = f"YENİ ALARM: {alarm.panel} - {alarm.error}"
        body = f"""Grid Up Sisteminde yeni bir anomali tespit edildi.

Pano: {alarm.panel}
Konum: {alarm.location}
Arıza: {alarm.error}

Lütfen en kısa sürede kontrol ediniz. Telegram üzerinden 'Görevi Üstlen' butonuna basarak müdahaleye başlayabilirsiniz.
"""
    else:
        subject = f"ALARM GÜNCELLEMESİ ({status_msg}): {alarm.panel}"
        body = f"""Grid Up sistemindeki alarmın durumu güncellendi.

Pano: {alarm.panel}
Konum: {alarm.location}
Arıza: {alarm.error}

YENİ DURUM: {status_msg}
"""
    send_gmail(subject, body)
