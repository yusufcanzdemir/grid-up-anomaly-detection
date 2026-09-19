"""WhatsApp bildirimi (WhatsApp Business Cloud API).

Brief madde 7 WhatsApp'i acikca istiyor; madde 6 ise Public Cloud yasagi koyuyor. Bu ikisi
WhatsApp icin catisir: WhatsApp Business API disaridan calisan bir servistir. Cozum:

* **Olcum verisi disari cikmaz.** Gonderilen mesaj sadece pano kimligi, durum ve teshis metnidir -
  ham sensor verisi, zaman serisi veya musteri bilgisi gitmez.
* Kanal `.env` ile **kapatilabilir** (`WHATSAPP_ENABLED=false`, varsayilan kapali). Kapaliyken
  sistem SMS ile calismaya devam eder.

Yapilandirilmamissa dry-run'a duser ve True doner.
"""
from __future__ import annotations

import logging

import requests

from grid_up_anomaly_detection.communication.base_notifier import dry_run, format_sms
from grid_up_anomaly_detection.config import config
from grid_up_anomaly_detection.models import Alarm

log = logging.getLogger(__name__)

name = "whatsapp"


def is_configured() -> bool:
    c = config.WHATSAPP
    return bool(c.ENABLED and c.TOKEN and c.PHONE_NUMBER_ID and c.RECIPIENTS)


def send(alarm: Alarm) -> bool:
    text = format_sms(alarm)
    recipients = config.WHATSAPP.recipient_list()
    if not is_configured():
        return dry_run(name, ", ".join(recipients), text)
    c = config.WHATSAPP
    url = f"{c.API_BASE}/{c.API_VERSION}/{c.PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {c.TOKEN}", "Content-Type": "application/json"}
    ok = True
    for number in recipients:
        body = {"messaging_product": "whatsapp", "to": number,
                "type": "text", "text": {"preview_url": False, "body": text}}
        try:
            r = requests.post(url, json=body, headers=headers, timeout=15)
            if r.status_code >= 400:
                log.error("WhatsApp %s -> HTTP %s: %s", number, r.status_code, r.text[:200])
                ok = False
        except Exception as exc:                                # noqa: BLE001 - kanal cokmemeli
            log.error("WhatsApp gonderilemedi (%s): %s", number, exc)
            print(f"[whatsapp] gonderilemedi: {exc}")
            ok = False
    return ok

