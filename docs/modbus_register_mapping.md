# Grid Up: Modbus Register Haritalama (SCADA Mapping)

> **Kapsam Notu:** Kısım A, sahada halihazırda bulunan (şartnameye uygun) cihazların tedarikçi kılavuzlarından alınan resmi okuma haritasıdır. Kısım B ise bu proje tarafından SCADA sistemlerine sunulmak üzere **önerilen** çıktı haritasıdır.

## A. Sahadaki Cihazlardan Okunan (READ) Register'lar

### A.1 MPR-53CS Şebeke Analizörü — Modbus RTU (RS485)

*Kaynak: `MPR-53CS_Modbus_Register_Map_EN.pdf`*
TEDAŞ şartnameleri gereği panolarda halihazırda bu analizör bulunmaktadır. Mevcut akım trafolarından (CT) beslendiği için panele yeni bir akım sensörü eklemeye gerek kalmadan bu harita üzerinden güç değerleri okunur.

| PDU Adresi | Register (Veri) | Birim | Çarpan | Kullanım Amacı |
|---|---|---|---|---|
| 6 / 8 / 10 | L1 / L2 / L3 Faz Akımı | A | 0.001 × CT | Ana model girdisi (yük normalizasyonu) |
| 12 | Nötr Akımı | A | 0.001 × CT | `NEUTRAL_CURRENT` anomali tespiti |
| 78 / 80 / 82 | L1 / L2 / L3 Akım THD | % | 0.1 | Harmonik yükleme analizi |
| 0 / 2 / 4 | L1 / L2 / L3 Faz Gerilimi | V | 0.1 × VT | Bağlam verisi |
| 58 | Frekans | Hz | 0.01 | Bağlam verisi |
| 32769 (0x8001) | Akım Trafosu (CT) Oranı | – | 1 | Ölçeklendirme için okunur |

### A.2 ABB TVOC-2-COM Ark Koruması — Modbus RTU (RS485)

*Kaynak: `1SFC170017M0201 Rev D`*
Ark tespiti için ortamdaki TVOC-2 cihazı periyodik olarak sorgulanır. **(Salt okunur, cihaza yazma yapılmaz.)**

| PDU Adresi | Register (Veri) | Kullanım Amacı |
|---|---|---|
| 1300 | Sistem Durumu (bit0: trip, bit1: error) | `ARC_TRIP`, `ARC_SYSTEM_ERROR` |
| 149 | Trip Sayısı | İki anket arasında gerçekleşen tripleri yakalar |
| 206 / 210 / 211 | Teşhis Trip + Dedektör Bit Alanı | Hangi hücrede ark görüldüğü |
| 212 | Teşhis Trip Rölesi | `ARC_DETECTED_NO_TRIP` (Röle çekmediği halde ark görülmesi) |
| 222 / 223 | Sensör Durumu X2 / X3 | Dedektör sağlığı (1 = OK) |
| 224 / 225 | Ortam Işığı Uyarısı X2 / X3 | `ARC_LIGHT_WARNING` (Kapak açık veya yanlış ışık) |

---

## B. SCADA'ya Sunulan ÇIKTI Bloğu (Yazılımın Önerdiği Çıktı)

Sistem tarafından hesaplanan AI analizleri ve sensör sonuçları, Modbus TCP üzerinden dış SCADA sistemlerine aşağıdaki sürekli blok yapısıyla sunulur.

**Temel Adresleme Mantığı:** Her bir modül (pano/hücre) için ardışık 32 adet Holding Register ayrılır.
`base_address(module_index) = 1000 + module_index × 32`

| Offset | İsim | Tip | Çarpan | Açıklama |
|---|---|---|---|---|
| 0 | `status_code` | u16 | 1 | 0: NORMAL, 1: WATCH, 2: WARNING, 3: CRITICAL |
| 1 | `risk_score` | u16 | 1 | 0–100 arası AI risk skoru |
| 2 | `health_score` | u16 | 1 | 0–100 arası genel sağlık |
| 3 | `confidence_pct` | u16 | ×100 | % 0–100 Güven (Sensör sağlığına göre) |
| 4 | `condition_code` | u16 | 1 | Şüpheli durum id'si |
| 5 | `top_reason_code` | u16 | 1 | En yüksek risk katkısını yapan olayın id'si |
| 6 | `alarm_bitmap` | u16 | – | (Bakınız: Alarm Bitmap Tablosu) |
| 7 | `sensor_health_bitmap` | u16 | – | 1 = Sensör sağlıklı, 0 = Hatalı |
| 8 | `temp_max_c` | i16 | ×10 | En sıcak bağlantı noktasının ısısı (0.1 °C) |
| 9–11 | `temp_l1_c` / `l2` / `l3` | i16 | ×10 | Fazlara ait spesifik ısılar |
| 12 | `temp_internal_c` | i16 | ×10 | Kabin/Pano içi ortam sıcaklığı |
| 13 | `temp_ambient_c` | i16 | ×10 | Dış ortam (Oda) sıcaklığı |
| 14 | `humidity_pct` | u16 | ×10 | %RH (Bağıl Nem) |
| 15 | `dew_margin_c` | i16 | ×10 | Yoğuşma marjı (Yüzey sıcaklığı - Çiy noktası) |
| 16–19 | `current_l1_a` / `l2` / `l3` / `n_a`| u16 | ×10 | Faz ve Nötr akımları (0.1 A) |
| 20 | `current_max_pct` | u16 | ×100 | Nominal akımın yüzde kaçının çekildiği |
| 22 | `pd_rate_per_min` | u16 | 1 | Kısmi Deşarj (PD) darbe sayısı / dakika |
| 24 | `arc_status` | u16 | 1 | 0: Ok, 1: Işık Uyarısı, 2: Sistem Hatası, 3: Trip, 4: Ark Görüldü ama Trip atılmadı |
| 25 | `time_to_critical_h` | u16 | ×10 | Kritik arızaya kalan süre tahmini (0.1 Saat) |
| 26 | `data_completeness_pct` | u16 | ×100 | Sensör verisi tamlık oranı (%) |
| 31 | `heartbeat` | u16 | 1 | Her güncellemeyle artar. Donarsa = Sistem kapandı |

*(Not: Müsait olmayan unsigned veriler için `0xFFFF`, signed veriler için `0x8000` kullanılır.)*

### B.1 `alarm_bitmap` (Bit Detayları)

| Bit | Anlamı | Bit | Anlamı |
|---|---|---|---|
| 0 | Ark Trip (TVOC-2) | 6 | Ortam Işığı Uyarısı |
| 1 | Ark Sistem Hatası | 7 | Durum ≥ WATCH (İzleme) |
| 2 | Mutlak Aşırı Isı | 8 | Durum ≥ WARNING (Uyarı) |
| 3 | Termal Aşırı Yükleme | 9 | Durum ≥ CRITICAL (Kritik) |
| 4 | Yoğuşma Tespiti | 10 | ML Katmanı Devre Dışı |
| 5 | Sensör Hatası | 12 | Ark tespit edildi ama devre kesici açmadı |

