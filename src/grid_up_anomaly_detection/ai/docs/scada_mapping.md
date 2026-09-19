# SCADA / Modbus mapping

> **Scope and honesty note.** Section A is transcribed from the manuals supplied with the challenge.
> **Section B is a proposal created by this project.** It is *not* an ADM/GDZ register map, it is not
> taken from any supplied document, and it must be reviewed by the DSO before any field use.
> No connection to a real SCADA system is made anywhere in this repository.

Implementation: `src/grid_up_anomaly_detection/ai/modbus_maps.py`. Live encoding of any module: `GET /scada/{module_id}`.

---

## A. Registers we READ from equipment that already exists in the panel

### A.1 MPR-53CS energy analyzer — Modbus RTU (RS485)

Source: `MPR-53CS_Modbus_Register_Map_EN.pdf`. The LV panel specification (TEDAŞ-MLZ/2003-06.B,
§2.2.11) already requires an energy analyzer with an RS485 Modbus port in every panel, so **the
current measurement needs no new sensor and no new CT in the panel**.

| PDU address | Register | Unit | Multiplier | Used for |
|---|---|---|---|---|
| 6 / 8 / 10 | L1 / L2 / L3 phase current | A | 0.001 × CT | primary model input (load normaliser) |
| 12 | Neutral current | A | 0.001 × CT | `NEUTRAL_CURRENT` evidence |
| 78 / 80 / 82 | L1 / L2 / L3 current THD | % | 0.1 | harmonic loading context |
| 0 / 2 / 4 | L1 / L2 / L3 phase voltage | V | 0.1 × VT | context (not used by the risk engine yet) |
| 58 | Frequency | Hz | 0.01 | context |
| 32769 (0x8001) | Current transformer ratio | – | 1 | scaling |

Open questions (both unspecified in the map, tracked in `DEGISIKLIK.md`): 32-bit **word order**, and
whether the value is already multiplied by the CT ratio.

### A.2 ABB TVOC-2-COM arc guard — Modbus RTU (RS485)

Source: `1SFC170017M0201 Rev D`. Default 19200 8E1, slave ID 248 means *communication disabled*
(valid range 1–247). Read-only polling; **we never write to this device.**

| PDU address | Register | Used for |
|---|---|---|
| 1300 | System state (bit0 trip active, bit1 error active, bit2 start sequence, bit3 diagnostics running) | `ARC_TRIP`, `ARC_SYSTEM_ERROR` |
| 149 | Number of trips | catches trips that occurred between polls |
| 206 / 210 / 211 | Diagnostics trip + detector bitfields (X1:1–X3:10) | which cubicle saw the arc |
| 212 | Diagnostics trip relay (bit0 K4, bit1 K5, bit2 K6 — manual 4.4.1.3) | `ARC_DETECTED_NO_TRIP`: detectors set while no relay operated |
| 222 / 223 | Sensor status X2 / X3 (1 = OK) | detector health |
| 224 / 225 | Ambient light warning X2 / X3 | `ARC_LIGHT_WARNING` (door open / light source) |
| 1301–1306 | Active diagnostic trouble codes | shown with the protection-unavailable alarm |

⚠️ The manual documents the ambient-light polarity inconsistently (§4.4.2 vs §4.4.3.8); confirm on a
real device before trusting that bit.

⚠️ **Arc mode 1 is an inference, not a documented register.** The DSO asked for both arc modes
("caught but did not trip" and "caught and tripped") to be carried. The supplied Modbus manual has no
mode register, so `ARC_DETECTED_NO_TRIP` is derived from *detector words 210/211 non-zero while relay
word 212 is zero*. §4.4.2 also notes these registers read `0x0000` when there is no active trip record
at all, so this derivation may not fire on a real device. **Must be verified on real hardware before
field use** — until then treat the channel as best-effort and keep `arc_trip_active` authoritative.

**Bus constraint:** Modbus RTU allows exactly one master per RS485 segment. If the OSOS/AMR modem
already polls these devices, our edge module needs its own port or a Modbus gateway. Unresolved.

---

## B. OUR PROPOSED output block (this project's proposal — not an existing DSO map)

One contiguous block of **32 holding registers per module**, so a SCADA/RTU can poll modules
independently or in bulk.

```
base_address(module_index) = 1000 + module_index × 32
100 modules → registers 1000 … 4199 (well within one Modbus TCP server)
```

Recommended polling: 1 register block per module every 5–30 s (the engine updates once per minute);
`heartbeat` increments on every update, so a frozen heartbeat means the engine stopped.

| Offset | Name | Type | Scale | Description |
|---|---|---|---|---|
| 0 | `status_code` | u16 | 1 | 0 NORMAL, 1 WATCH, 2 WARNING, 3 CRITICAL |
| 1 | `risk_score` | u16 | 1 | 0–100 |
| 2 | `health_score` | u16 | 1 | 0–100 |
| 3 | `confidence_pct` | u16 | ×100 | 0–100 % |
| 4 | `condition_code` | u16 | 1 | suspected condition (see contract doc) |
| 5 | `top_reason_code` | u16 | 1 | highest-contribution reason code |
| 6 | `alarm_bitmap` | u16 | – | see B.1 |
| 7 | `sensor_health_bitmap` | u16 | – | see B.2, 1 = healthy |
| 8 | `temp_max_c` | i16 | ×10 | hottest monitored connection, 0.1 °C |
| 9–11 | `temp_l1_c` / `temp_l2_c` / `temp_l3_c` | i16 | ×10 | per-phase connection temperature |
| 12 | `temp_internal_c` | i16 | ×10 | cabinet air |
| 13 | `temp_ambient_c` | i16 | ×10 | room |
| 14 | `humidity_pct` | u16 | ×10 | cabinet relative humidity |
| 15 | `dew_margin_c` | i16 | ×10 | surface temperature − dew point |
| 16–19 | `current_l1_a` / `l2` / `l3` / `n_a` | u16 | ×10 | 0.1 A (2312 A × 10 fits in u16) |
| 20 | `current_max_pct` | u16 | ×100 | % of rated current |
| 21 | `thermal_image_pct` | u16 | ×100 | % of rated thermal state (θ) |
| 22 | `pd_rate_per_min` | u16 | 1 | PD pulses/min (MV_CELL only) |
| 23 | `pd_peak_mv` | u16 | 1 | PD peak amplitude, mV |
| 24 | `arc_status` | u16 | 1 | 0 ok, 1 light warning, 2 system error, 3 trip, **4 arc detected, trip circuit did not fire** |
| 25 | `time_to_critical_h` | u16 | ×10 | trend extrapolation, 0.1 h |
| 26 | `data_completeness_pct` | u16 | ×100 | % of installed channels present |
| 27–28 | `reason_2_code`, `reason_3_code` | u16 | 1 | supporting reasons, 0 = none |
| 29–30 | `timestamp_high`, `timestamp_low` | u16 | 1 | unix seconds of the reading (high/low word) |
| 31 | `heartbeat` | u16 | 1 | increments each update |

**Not-available encoding:** unsigned fields use `0xFFFF`, signed fields use `0x8000` (−32768).
A panel with no PD channel therefore reports `0xFFFF`, never `0`, so SCADA cannot mistake
"no sensor" for "no discharge". Signed values are two's complement.

### B.1 `alarm_bitmap`

| Bit | Meaning | Bit | Meaning |
|---|---|---|---|
| 0 | arc trip (TVOC-2) | 6 | arc detector ambient-light warning |
| 1 | arc protection system error | 7 | status ≥ WATCH |
| 2 | absolute temperature critical *(PLACEHOLDER limit)* | 8 | status ≥ WARNING |
| 3 | sustained overload (thermal image) | 9 | status ≥ CRITICAL |
| 4 | condensation on surfaces | 10 | ML layer unavailable |
| 5 | sensor fault | 11 | thermal baseline invalid |
| | | 12 | arc detected, trip circuit did not fire |

### B.2 `sensor_health_bitmap` (1 = present and healthy)

| Bit | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| Channel | temp L1 | temp L2 | temp L3 | cabinet temp | ambient temp | humidity | currents | PD | arc link |

### B.3 Design notes

* **Read-only integration.** The monitoring system never writes to protection or control devices; the
  proposed block is an output image for SCADA to read. Tripping stays with the TVOC-2 and the breaker.
* **Threshold provenance.** `abs temperature critical` and the overload limits are `PLACEHOLDER` /
  `CONFIGURABLE` values in `ai/configs/default.yaml`. The panel specification (§2.2.3) defers
  temperature-rise limits to TS EN 61439-1 Çizelge 8, **which was not supplied**, so no absolute
  thermal limit in this repository should be presented as authoritative.
* **Why a block and not one register per signal:** a DSO RTU can map a whole module with one
  `read holding registers` call, and adding a module never renumbers existing ones.
