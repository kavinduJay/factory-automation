# Devices and sensors

## Naming

`SITE-FLOOR-ZONE-TYPEnn`, for example `TF01-U-TR03-THS02` (trough 3, upper floor, temperature/humidity sensor 2).

| Part | Codes |
|---|---|
| Site | `TF01` |
| Floor | `G` ground/outdoor, `U` upper, `L` lower |
| Zone | `RCV` receiving · `TR01`–`TR11` troughs · `WWB` withered weigh · `RC1`–`RC3` charging rollers · `R21`–`R23` 2nd rolling · `R31`, `R32` 3rd rolling · `R41` 4th rolling · `RW1`–`RW4` rolling weigh points · `ROL` rolling area · `FER` fermentation · `DRY` drier · `DRO` drier output · `ENV` ambient |
| Type | `NOD` zone node · `SCB` scale bridge · `THS` temp/humidity · `THH` high-humidity temp/humidity · `IRS` IR surface temp · `TCK` K-type thermocouple · `TCM` thermocouple module · `CTS` current sensor · `STL` stack light · `QRS` QR scanner · `TAB` tablet · `PRN` printer |

## Totals

| Item | Count |
|---|---|
| Scale bridges | 7 |
| Zone nodes | 18 |
| Temperature/humidity sensors (THS) | 43 (33 troughs, 9 rollers, 1 outdoor) |
| High-humidity probes (THH) | 3 |
| IR surface sensors (IRS) | 8 |
| Thermocouples (TCK) + module (TCM) | 3 + 1 |
| Current sensors (CTS) | 21 (11 fans, 9 rollers, 1 drier) |
| **Measuring sensors in total** | **78** (the TCM module is counted as a module, not a sensor) |

## Scale bridges

All bridges: ESP32 (S3 in production), isolated RS-232 to an Avery indicator, keypad, display, real-time clock, flash buffer (≥ 7 days), Wi-Fi.

| Device ID | Point | Extra I/O | Records |
|---|---|---|---|
| `TF01-U-RCV-SCB01` | A | Tablet `TF01-U-RCV-TAB01` (Wi-Fi), QR scanner `TF01-U-RCV-QRS01` and printer `TF01-U-RCV-PRN01` (Bluetooth to tablet) | supplier_id, sack_seq, gross_kg, deductions, net_kg, trough_no, area_no, alloc_kg, maturity, photos |
| `TF01-U-WWB-SCB01` | B | QR scanner `TF01-U-WWB-QRS01` (serial), stack light `TF01-U-WWB-STL01` (relays R1 red+buzzer, R2 amber, R3 green) | trough_no, area_no, crate_id, gross_kg, tare_kg, net_kg, max_limit_kg, over_limit, batch_id |
| `TF01-L-RW1-SCB01` … `RW4-SCB01` | W1–W4 | Stage fixed per unit in config | batch_id, stage, net_kg, bulk_flag (W3/W4) |
| `TF01-L-DRO-SCB01` | D | Stack light `TF01-L-DRO-STL01` | batch_id, net_kg, max_limit_kg, over_limit, moisture_pct (manual) |

## Zone nodes and Modbus buses

Each node: industrial ESP32, isolated RS-485, 24 V, Wi-Fi. Bus: 2-pair shielded twisted pair, daisy-chained, 120 Ω terminator at the far end. Proposed settings 9600 baud 8N1. **Addresses are a proposed scheme, confirm at install.**

Address ranges: temp/humidity 1–9, current modules 21–29, IR sensors 31–38, thermocouple module 41.

| Node | Bus devices (address) |
|---|---|
| `TF01-U-TRnn-NOD01` × 11 | `TRnn-THS01` plenum (1), `THS02` above leaf near end (2), `THS03` above leaf far end (3), `CTS01` fan (21) |
| `TF01-L-ROL-NOD01` | RC1/RC2/RC3: `THS01` (1, 2, 3), `CTS01` (21, 22, 23) |
| `TF01-L-ROL-NOD02` | R21/R22/R23: `THS01` (1, 2, 3), `CTS01` (21, 22, 23) |
| `TF01-L-ROL-NOD03` | R31/R32/R41: `THS01` (1, 2, 3), `CTS01` (21, 22, 23) |
| `TF01-L-FER-NOD01` | `THH01`–`THH03` (1–3), `IRS01`–`IRS04` (31–34) |
| `TF01-L-FER-NOD02` | `IRS05`–`IRS08` (35–38) |
| `TF01-L-DRY-NOD01` | `TCM01` (41) with `TCK01` inlet on CH1, `TCK02` outlet CH2, `TCK03` exhaust CH3; `CTS01` drier motor (21) |
| `TF01-G-ENV-NOD01` | `THS01` outdoor, in radiation shield (1) |

## Proof of concept hardware (current)

Two ESP32-C3 boards on a breadboard: one simulates the Avery serial output, one acts as the bridge. A serial-to-TTL (RS-232) converter and an OLED display.
