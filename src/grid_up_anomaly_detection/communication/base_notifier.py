"""Tüm bildirim sistemleri için ortak şablon.

Bir bildirim kanalı iki şeye uyar:

* `send(alarm) -> bool` — gönderdiyse True, gönderemediyse False. **Asla exception fırlatmaz.**
  Bir bildirim kanalının çökmesi risk motorunu durduramaz; alarm zaten SCADA bloğunda ve
  dashboard'da duruyor.
* `is_configured() -> bool` — gerekli ayarlar var mı. Yoksa kanal "dry-run" (log) moduna düşer,
  mesajı konsola yazar ve True döner. Demo, hiçbir kimlik bilgisi olmadan da uçtan uca çalışır.

`Alarm` nesnesi `grid_up_anomaly_detection.models.Alarm`. AI çıktısından (inference payload)
üretmek için `alarm_from_payload()` kullanın.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from grid_up_anomaly_detection.models import Alarm, AlarmStatus

log = logging.getLogger(__name__)

# Sadece bu durumlar dışarı bildirim üretir; WATCH ve NORMAL yalnızca dashboard'da görünür.
PUSH_STATUSES = ("WARNING", "CRITICAL")


class Notifier(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def send(self, alarm: Alarm) -> bool: ...


def alarm_from_payload(payload: dict[str, Any], alarm_id: int = 0, location: str = "") -> Alarm:
    """AI inference payload (inference_contract.md) -> Alarm.

    Eksik alanlar None olabilir; hiçbir alan zorunlu değil, çünkü bir sensör yoksa sözleşme
    null gönderiyor.
    """
    summary = payload.get("sensor_summary") or {}
    temp = summary.get("temperature") or {}
    cur = summary.get("current") or {}
    hum = summary.get("humidity") or {}
    condition = payload.get("suspected_condition") or {}
    return Alarm(
        id=alarm_id,
        panel=str(payload.get("panel_id") or payload.get("module_id") or "?"),
        location=location or str(payload.get("site_id") or ""),
        error=str(condition.get("label") or ""),
        temperature=_num(temp.get("max_c")),
        current=_num(cur.get("l1_a")),
        humidity=int(_num(hum.get("rh_pct"))),
        status=AlarmStatus.CRITICAL,
        ai_status=str(payload.get("status") or ""),
        suspected_condition=str(condition.get("label") or ""),
        reasons=[r.get("message") for r in (payload.get("reasons") or []) if r.get("message")],
    )


# Türkçe harfler GSM-7 alfabesinde yok. Biri bile geçerse operatör mesajı UCS-2'ye düşürür ve
# tek SMS 160 yerine 70 karaktere iner; GSM modem yolunda ise "?" olur. Bu yüzden çevriliyor.
_GSM7_SAFE = str.maketrans({
    "ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G",
    "ü": "u", "Ü": "U", "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
    "â": "a", "î": "i", "û": "u", "–": "-", "—": "-", "’": "'", "“": '"', "”": '"',
})

SMS_MAX_CHARS = 160


def format_sms(alarm: Alarm) -> str:
    """Tek SMS'e sığan kısa metin. Uzun gerekçe listesi dashboard'da, burada değil."""
    parts = [f"GRID UP {alarm.ai_status or 'ALARM'}", f"Pano {alarm.panel}"]
    if alarm.location:
        parts.append(alarm.location)
    if alarm.suspected_condition:
        parts.append(alarm.suspected_condition)
    if alarm.temperature:
        parts.append(f"{alarm.temperature:.0f}C")
    text = " | ".join(parts).translate(_GSM7_SAFE)
    # kalan ASCII dışı karakter varsa o da düşürülür: operatör gateway'i reddetmesin
    text = text.encode("ascii", "ignore").decode("ascii")
    return text[:SMS_MAX_CHARS]


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def dry_run(channel: str, target: str, text: str) -> bool:
    """Kimlik bilgisi yokken: gönderiyormuş gibi yap, konsola yaz, True dön."""
    log.warning("[%s] yapilandirilmamis -> DRY-RUN. Alici=%s Mesaj=%s", channel, target or "-", text)
    print(f"[{channel} DRY-RUN] -> {target or '(alici tanimsiz)'}: {text}")
    return True
