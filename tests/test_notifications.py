"""Bildirim katmani: sozlesme ne vaat ediyorsa o kanala gitmeli, ve hicbir kosulda cokmemeli."""
from __future__ import annotations

import pytest

from grid_up_anomaly_detection.communication import dispatcher
from grid_up_anomaly_detection.communication.base_notifier import alarm_from_payload, format_sms
from grid_up_anomaly_detection.communication.sms import gateway as sms_gateway
from grid_up_anomaly_detection.communication.whatsapp import cloud_api as whatsapp_api


def payload(status: str, channels: list[str]) -> dict:
    return {
        "schema_version": "1.1", "module_id": "M-001", "panel_id": "P-001", "site_id": "SITE-01",
        "status": status, "status_code": 3, "risk_score": 92,
        "suspected_condition": {"code": "ARC_FLASH", "label": "Ark flas olayi"},
        "reasons": [{"code": "ARC_DETECTED_NO_TRIP", "message": "Ark algilandi, acma yapilmadi"}],
        "notify": {"channels": channels, "priority": "high"},
        "sensor_summary": {
            "temperature": {"max_c": 78.4}, "current": {"l1_a": 261.3},
            "humidity": {"rh_pct": 41.0}, "arc": {"trip_active": False, "detected_no_trip": True},
        },
    }


def test_payload_becomes_an_alarm_without_losing_the_diagnosis():
    alarm = alarm_from_payload(payload("CRITICAL", ["sms"]))
    assert alarm.panel == "P-001"
    assert alarm.ai_status == "CRITICAL"
    assert alarm.suspected_condition == "Ark flas olayi"
    assert alarm.temperature == pytest.approx(78.4)
    assert "Ark algilandi, acma yapilmadi" in alarm.reasons


def test_sms_text_is_short_enough_to_send():
    text = format_sms(alarm_from_payload(payload("CRITICAL", ["sms"])))
    assert len(text) <= 160
    assert "P-001" in text and "CRITICAL" in text


def test_sms_text_stays_in_the_gsm7_alphabet():
    """Turkce harf gecerse operator mesaji UCS-2'ye dusurur ve 160 -> 70 karaktere iner."""
    p = payload("CRITICAL", ["sms"])
    p["suspected_condition"]["label"] = "Gevşek / oksitlenmiş bağlantı şüphesi"
    text = format_sms(alarm_from_payload(p))
    assert text.isascii()
    assert "Gevsek" in text and "baglanti" in text


@pytest.mark.parametrize("status", ["NORMAL", "WATCH"])
def test_normal_and_watch_do_not_page_anyone(status):
    assert dispatcher.dispatch(payload(status, ["dashboard"])) == {}


def test_dashboard_and_scada_are_not_push_channels():
    out = dispatcher.dispatch(payload("CRITICAL", ["dashboard", "scada"]))
    assert out == {}


def test_critical_reaches_sms_and_whatsapp(monkeypatch):
    seen = []
    monkeypatch.setitem(dispatcher.PUSH_CHANNELS, "sms", lambda a: seen.append("sms") or True)
    monkeypatch.setitem(dispatcher.PUSH_CHANNELS, "whatsapp", lambda a: seen.append("whatsapp") or True)
    out = dispatcher.dispatch(payload("CRITICAL", ["dashboard", "sms", "whatsapp", "scada"]))
    assert out == {"sms": True, "whatsapp": True}
    assert seen == ["sms", "whatsapp"]


def test_unconfigured_channels_dry_run_instead_of_raising(capsys):
    """Kimlik bilgisi yokken demo cokmemeli: konsola yazip True donmeli."""
    alarm = alarm_from_payload(payload("CRITICAL", ["sms", "whatsapp"]))
    assert sms_gateway.send(alarm) is True
    assert whatsapp_api.send(alarm) is True
    printed = capsys.readouterr().out
    assert "DRY-RUN" in printed


def test_a_failing_channel_never_propagates(monkeypatch):
    """Gateway patlarsa False donmeli, exception firlatmamali - risk motoru durmaz."""
    def boom(*_a, **_kw):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(sms_gateway, "is_configured", lambda: True)
    monkeypatch.setattr(sms_gateway, "_send_via_http", boom)
    assert sms_gateway.send(alarm_from_payload(payload("CRITICAL", ["sms"]))) is False

