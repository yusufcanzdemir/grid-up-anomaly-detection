######
"""SMS bildirimi.

Brief "Public Cloud kullanilmamalidir" diyor, bu yuzden saglayici secilebilir tutuldu ve
varsayilan kurumsal/yerel gateway. Uc mod var, `SMS_PROVIDER` ile secilir:

* `http`  (varsayilan) — operatorun kurumsal SMS gateway'i veya sirket ici SMS sunucusu.
                          URL ve alan adlari .env'den gelir, hicbir saglayiciya bagimli degil.
* `modem` — panodaki/merkezdeki GSM modemine seri port uzerinden AT komutu. Tamamen on-premise,
            internet gerektirmez. `pyserial` kurulu degilse kendiliginden dry-run'a duser.
* `log`   — hicbir sey gondermez, konsola yazar. Demo ve test icin.

Hicbiri yapilandirilmamissa otomatik olarak dry-run calisir ve True doner; bildirim katmani
risk motorunu asla durdurmaz.
"""
from __future__ import annotations

import logging

import requests

from grid_up_anomaly_detection.communication.base_notifier import dry_run, format_sms
from grid_up_anomaly_detection.config import config
from grid_up_anomaly_detection.models import Alarm

log = logging.getLogger(__name__)

name = "sms"


def is_configured() -> bool:
    c = config.SMS
    if c.PROVIDER == "http":
        return bool(c.GATEWAY_URL and c.RECIPIENTS)
    if c.PROVIDER == "modem":
        return bool(c.MODEM_PORT and c.RECIPIENTS)
    return False


def send(alarm: Alarm) -> bool:
    """Alarmi SMS olarak gonderir. Exception firlatmaz."""
    text = format_sms(alarm)
    recipients = config.SMS.recipient_list()
    if not is_configured():
        return dry_run(name, ", ".join(recipients), text)
    try:
        if config.SMS.PROVIDER == "modem":
            return _send_via_modem(recipients, text)
        return _send_via_http(recipients, text)
    except Exception as exc:                                   
        log.error("SMS gonderilemedi: %s", exc)
        print(f"[sms] gonderilemedi: {exc}")
        return False


def _send_via_http(recipients: list[str], text: str) -> bool:
    """Genel amacli HTTP gateway. Alan adlari .env'den, cunku her operatorde farkli."""
    c = config.SMS
    ok = True
    for number in recipients:
        payload = {c.FIELD_TO: number, c.FIELD_TEXT: text}
        if c.USERNAME:
            payload[c.FIELD_USER] = c.USERNAME
        if c.PASSWORD:
            payload[c.FIELD_PASS] = c.PASSWORD
        if c.SENDER:
            payload[c.FIELD_FROM] = c.SENDER
        headers = {"Authorization": c.AUTH_HEADER} if c.AUTH_HEADER else {}
        r = requests.post(c.GATEWAY_URL, data=payload, headers=headers, timeout=15)
        if r.status_code >= 400:
            log.error("SMS gateway %s -> HTTP %s: %s", number, r.status_code, r.text[:200])
            ok = False
    return ok


def _send_via_modem(recipients: list[str], text: str) -> bool:
    """Yerel GSM modem, AT komutu. pyserial opsiyonel bagimlilik."""
    try:
        import serial
    except ImportError:
        log.warning("SMS_PROVIDER=modem ama pyserial kurulu degil -> dry-run")
        return dry_run(name, ", ".join(recipients), text)
    c = config.SMS
    with serial.Serial(c.MODEM_PORT, c.MODEM_BAUD, timeout=5) as ser:
        for number in recipients:
            ser.write(b'AT+CMGF=1\r')                            
            ser.read_until(b'OK', 200)
            ser.write(f'AT+CMGS="{number}"\r'.encode())
            ser.read_until(b'>', 200)
            ser.write(text.encode("ascii", "replace") + b'\x1a')  
            ser.read_until(b'OK', 200)
    return True

