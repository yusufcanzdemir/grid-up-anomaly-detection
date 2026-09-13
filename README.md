# Grid Up — Anomaly Detection

Pano ve hücrelerde oluşabilecek anomalileri erken aşamada tespit etmek ve ilgili ekipleri kritik durumlar oluşmadan önce bilgilendirmek amacıyla geliştirilen izleme ve erken uyarı sistemi.

## Proje

Sistem; sıcaklık, akım, nem ve benzeri saha verilerini birlikte değerlendirerek normal çalışma koşullarından sapmaları tespit etmeyi ve olası arıza riskleri için erken uyarı üretmeyi hedefler.

## Temel Özellikler

* Sensör verilerinin izlenmesi
* Anomali ve risk tespiti
* Merkezi monitoring
* Alarm ve bildirim mekanizması
* SCADA / Modbus entegrasyonu
* On-premise çalışma
* Ölçeklenebilir sistem mimarisi

## Mimari

```
saha sensörleri / Modbus (MPR-53CS, TVOC-2) -> kanonik okuma -> AI risk motoru -> JSON çıktı sözleşmesi
                                                                   |                   |
                                                         kural + fizik tabanlı      backend / dashboard,
                                                         model + sınırlı ML         alarm, SCADA bloğu
```

## Bileşenler

| Klasör | İçerik |
|---|---|
| [`ai/`](ai/README.md) | Anomali tespiti ve risk skorlama motoru (`RiskEngine.update()`), konfigürasyon, testler, simülasyon/değerlendirme scriptleri, FastAPI prototipi |

Backend/monitoring, frontend, SCADA/Modbus entegrasyonu ve donanım dokümantasyonu içerik oluştukça
kendi klasörlerine eklenecek. Geliştirme kuralları: [SKILLS.md](SKILLS.md).

## AI testlerini çalıştırma

```bash
cd ai
poetry install --all-extras
poetry run pytest -q
```