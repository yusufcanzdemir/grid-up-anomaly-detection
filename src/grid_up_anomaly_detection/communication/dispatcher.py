"""Tek giris noktasi: bir AI inference payload'unu, sozlesmesinin istedigi kanallara dagitir.

`inference_contract.md` her cikti icin bir `notify` blogu uretiyor:

    {"channels": ["dashboard", "sms", "whatsapp", "scada"], "priority": "high"}

Bu modul o listeyi okur ve **push** kanallarini calistirir. `dashboard` ve `scada` push degildir -
dashboard payload'u zaten cekiyor, SCADA da Modbus blogunu pollluyor; ikisi burada atlanir.

Kullanim:

    from grid_up_anomaly_detection.communication.dispatcher import dispatch
    dispatch(payload)            # -> {"sms": True, "whatsapp": True}

Hicbir kanal exception firlatmaz; sonuc sozlugunde False = gonderilemedi.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from grid_up_anomaly_detection.communication.base_notifier import PUSH_STATUSES, alarm_from_payload
from grid_up_anomaly_detection.communication.sms import gateway as sms_gateway
from grid_up_anomaly_detection.communication.whatsapp import cloud_api as whatsapp_api
from grid_up_anomaly_detection.models import Alarm

log = logging.getLogger(__name__)

# Payload'daki kanal adi -> gonderici. Dashboard/SCADA push degil, bilerek yok.
PUSH_CHANNELS: dict[str, Callable[[Alarm], bool]] = {
    "sms": sms_gateway.send,
    "whatsapp": whatsapp_api.send,
}


def dispatch(payload: dict[str, Any], alarm_id: int = 0, location: str = "",
             telegram: bool = False) -> dict[str, bool]:
    """Payload'u kanallarina dagit. Sonuc: {kanal: gonderildi_mi}.

    `telegram=True` verilirse mevcut Telegram/Gmail hatti da tetiklenir (varsayilan kapali,
    cunku o hat kendi listener'i uzerinden de calisabiliyor).
    """
    status = str(payload.get("status") or "")
    if status not in PUSH_STATUSES:
        return {}                                   # NORMAL / WATCH -> sadece dashboard

    channels = (payload.get("notify") or {}).get("channels") or []
    alarm = alarm_from_payload(payload, alarm_id=alarm_id, location=location)
    results: dict[str, bool] = {}
    for channel in channels:
        sender = PUSH_CHANNELS.get(channel)
        if sender is None:
            continue                                # dashboard, scada -> push degil
        results[channel] = bool(sender(alarm))

    if telegram:
        results["telegram"] = _send_telegram(alarm)
    return results


def _send_telegram(alarm: Alarm) -> bool:
    """Telegram/Gmail hatti opsiyonel: token yoksa veya modul yuklenemezse sessizce False."""
    try:
        from grid_up_anomaly_detection.communication.telegram.bot import send_telegram_alert
        send_telegram_alert(alarm)
        return True
    except Exception as exc:                        # noqa: BLE001 - kanal cokmemeli
        log.error("Telegram gonderilemedi: %s", exc)
        return False

