"""Reason-code and condition catalog (stable codes for backend / dashboard / SCADA)."""
from __future__ import annotations

# code -> (int id for SCADA, Turkish message template, English message template)
REASONS: dict[str, tuple[int, str, str]] = {
    "CONNECTION_HEATING": (10, "{phase} bağlantısı aynı akımda devreye alma değerinin {value:.1f} katı ısınıyor",
                           "{phase} connection heats {value:.1f}x its commissioning baseline at the same current"),
    "PHASE_ASYMMETRY": (11, "{phase} fazı diğer fazlara göre {value:.1f} kat fazla ısınıyor (yük düzeltmeli)",
                        "{phase} heats {value:.1f}x more than the other phases (load-corrected)"),
    "LUG_RESIDUAL": (12, "Bağlantı sıcaklığı akım/ortam modelinin {value:.1f} sigma üzerinde",
                     "Connection temperature {value:.1f} sigma above current/ambient model"),
    "HEATING_TREND": (13, "Isınma indeksi günde +{value:.2f} artıyor (bozulma hızı)",
                      "Heating index rising +{value:.2f}/day (deterioration rate)"),
    "ABS_TEMPERATURE": (14, "Bağlantı sıcaklığı {value:.1f} °C", "Connection temperature {value:.1f} degC"),
    "CABINET_HEATING": (20, "Pano içi, aynı yükte beklenenin {value:.1f} katı ısınıyor (havalandırma)",
                        "Cabinet heats {value:.1f}x expected for this load (ventilation)"),
    "THERMAL_OVERLOAD": (30, "Termal yük imajı nominalin %{pct:.0f}'i", "Thermal load image at {pct:.0f}% of rated"),
    "NEUTRAL_CURRENT": (31, "Nötr akımı faz ortalamasının %{pct:.0f}'i", "Neutral current {pct:.0f}% of phase mean"),
    "HUMIDITY_HIGH": (40, "Pano içi bağıl nem %{value:.0f}", "Cabinet relative humidity {value:.0f}%"),
    "CONDENSATION": (41, "Yoğuşma payı {value:.1f} °C (yüzey sıcaklığı çiy noktasına yakın)",
                     "Condensation margin {value:.1f} degC (surface near dew point)"),
    "PD_ACTIVITY": (50, "Kısmi deşarj aktivitesi referansın {value:.1f} sigma üzerinde",
                    "Partial discharge activity {value:.1f} sigma above baseline"),
    "PD_TREND": (51, "Kısmi deşarj hızı artıyor (günlük x{value:.1f})", "PD rate increasing (x{value:.1f} per day)"),
    "ML_ANOMALY": (60, "Çok değişkenli davranış öğrenilmiş normalden sapıyor",
                   "Multivariate behaviour deviates from learned normal"),
    "ARC_TRIP": (90, "TVOC-2 ark koruması açtırdı", "TVOC-2 arc protection tripped"),
    "ARC_DETECTED_NO_TRIP": (97, "TVOC-2 ark algıladı ancak açma devresi tetiklenmedi — kesici kapalı",
                             "TVOC-2 detected an arc but the trip circuit did not fire — breaker still closed"),
    "ARC_SYSTEM_ERROR": (91, "Ark koruma sistemi hata bildiriyor — pano ark korumasız olabilir",
                         "Arc protection reports an error — panel may be unprotected"),
    "ARC_LIGHT_WARNING": (92, "Ark dedektörü ortam ışığı uyarısı (kapak açık / ışık kaynağı)",
                          "Arc detector ambient-light warning (door open / light source)"),
    "ABS_TEMP_CRITICAL": (93, "Mutlak sıcaklık kritik sınırın üzerinde", "Absolute temperature above critical limit"),
    "OVERLOAD_RULE": (94, "Sürekli aşırı yük (termal imaj > nominal)", "Sustained overload (thermal image > rated)"),
    "SENSOR_FAULT": (95, "Sensör arızası/veri kaybı: {channels}", "Sensor fault / data loss: {channels}"),
    "CONDENSATION_RULE": (96, "Yüzey sıcaklığı çiy noktasının altında — yoğuşma oluşuyor",
                          "Surface temperature below dew point — condensation forming"),
}
REASON_CODES = {k: v[0] for k, v in REASONS.items()}

# Which subsystem produced the reason. Shown in the payload as `source` so an operator (and the
# dashboard) can tell a learned-model finding from a hard rule or from the ML layer.
REASON_SOURCES: dict[str, str] = {
    "CONNECTION_HEATING": "thermal_model",
    "PHASE_ASYMMETRY": "thermal_model",
    "LUG_RESIDUAL": "thermal_model",
    "HEATING_TREND": "trend_analysis",
    "ABS_TEMPERATURE": "temperature_sensor",
    "CABINET_HEATING": "thermal_model",
    "THERMAL_OVERLOAD": "thermal_image",
    "NEUTRAL_CURRENT": "energy_analyzer",
    "HUMIDITY_HIGH": "humidity_sensor",
    "CONDENSATION": "psychrometrics",
    "PD_ACTIVITY": "hfct_pd",
    "PD_TREND": "trend_analysis",
    "ML_ANOMALY": "isolation_forest",
    "ARC_TRIP": "tvoc2_arc_guard",
    "ARC_DETECTED_NO_TRIP": "tvoc2_arc_guard",
    "ARC_SYSTEM_ERROR": "tvoc2_arc_guard",
    "ARC_LIGHT_WARNING": "tvoc2_arc_guard",
    "ABS_TEMP_CRITICAL": "safety_rule",
    "OVERLOAD_RULE": "safety_rule",
    "SENSOR_FAULT": "sensor_health",
    "CONDENSATION_RULE": "safety_rule",
}

CONDITIONS: dict[str, tuple[int, str, str]] = {
    "NONE": (0, "Normal çalışma", "Normal operation"),
    "LOOSE_CONNECTION": (1, "Gevşek / oksitlenmiş bağlantı şüphesi",
                         "Planlı kesintide ilgili faz bağlantısını termal kamera ile kontrol edin, tork kontrolü yapın; yükü mümkünse azaltın."),
    "VENTILATION_DEGRADATION": (2, "Havalandırma / soğutma bozulması",
                                "Havalandırma menfezleri ve filtreleri kontrol edin (şartname 2.2.8.5); pano çevresini açın."),
    "OVERLOAD": (3, "Sürekli aşırı yük", "Yük dağılımını gözden geçirin, fider yükünü azaltın; koruma ayarlarını doğrulayın."),
    "CONDENSATION_RISK": (4, "Yoğuşma / nem riski",
                          "Pano sızdırmazlığını ve kablo girişlerini kontrol edin; ısıtıcı/nem alma değerlendirin."),
    "INSULATION_DEGRADATION": (5, "İzolasyon bozulması / gelişen kısmi deşarj",
                               "Kısmi deşarj ölçümü ve izolasyon testi planlayın; nem kaynağını giderin."),
    "ARC_FLASH": (6, "Ark flaş olayı", "Sahaya ekip gönderin. Enerjiyi yeniden vermeden önce panoyu muayene edin."),
    "SENSOR_FAULT": (7, "İzleme sensörü arızası", "Sensörü/haberleşmeyi kontrol edin; diğer sensörlerle izleme sürüyor."),
    "PROTECTION_UNAVAILABLE": (8, "Ark koruma sistemi arızalı", "TVOC-2 hata kodunu (DTC) okuyun ve sistemi onarın."),
    "UNEXPLAINED_ANOMALY": (9, "Açıklanamayan anomali", "Trendleri inceleyin; bir sonraki bakımda kontrol edin."),
}
CONDITION_CODES = {k: v[0] for k, v in CONDITIONS.items()}
CONDITION_LABELS = {k: v[1] for k, v in CONDITIONS.items()}
RECOMMENDED_ACTIONS = {k: v[2] for k, v in CONDITIONS.items()}
RECOMMENDED_ACTIONS["NONE"] = "İşlem gerekmiyor."

# Diagnosis signatures: weights over evidence severities (positive = supports, negative = contradicts)
SIGNATURES: dict[str, dict[str, float]] = {
    "LOOSE_CONNECTION": {"PHASE_ASYMMETRY": 1.0, "CONNECTION_HEATING": 0.6, "HEATING_TREND": 0.4,
                         "LUG_RESIDUAL": 0.3, "CABINET_HEATING": -0.4, "THERMAL_OVERLOAD": -0.3},
    "VENTILATION_DEGRADATION": {"CABINET_HEATING": 1.0, "PHASE_ASYMMETRY": -0.6},
    "OVERLOAD": {"THERMAL_OVERLOAD": 1.0, "PHASE_ASYMMETRY": -0.4, "CONNECTION_HEATING": -0.3},
    "CONDENSATION_RISK": {"CONDENSATION": 1.0, "HUMIDITY_HIGH": 0.5, "PD_ACTIVITY": -0.3},
    "INSULATION_DEGRADATION": {"PD_ACTIVITY": 1.0, "PD_TREND": 0.6},
    "UNEXPLAINED_ANOMALY": {"ML_ANOMALY": 0.5},
}
