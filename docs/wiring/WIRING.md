# Scale bridge and zone node wiring

Text and connection tables for all 9 build variants: 4 scale bridge types (7 units) and 5 zone node types (18 units). **The wiring diagrams are in [`wiring-diagrams.pdf`](wiring-diagrams.pdf)**, one per section below. Editable source: https://claude.ai/code/artifact/714747cb-eab3-4c8a-b86b-068dc5d96788 (re-export the PDF when it changes).

## Key and conventions

- **Device IDs:** `SITE-FLOOR-ZONE-TYPEnn`, as in `docs/DEVICES.md` (`TF01-U-TR03-THS02` is trough 3, upper floor, temperature/humidity sensor 2). Each diagram shows one example unit; the table gives the IDs for the other units of that type.
- **RS-485 bus:** daisy-chained, never star-wired, 120 Ω terminator at the far end only. The node end has built-in termination; confirm on site.
- **Bus cable:** 2-pair shielded twisted pair (STP). Pair 1 carries A and B; pair 2 carries +24 V and 0 V for the sensors. Ground the shield at the node end only.
- **Bus settings (proposed):** 9600 baud, 8N1. Confirm against each sensor's datasheet.
- **Modbus addresses (proposed, installer confirms):** temperature/humidity 1–9, current modules 21–29, IR sensors 31–38, thermocouple module 41. Unique per node's own bus.
- **Terminal names** (+24 V, 0 V, RS-485 A/B, RS-232 TX/RX/GND, relays R1–R3) are functional labels. Map them to the terminal numbers of the controller bought; mark unknowns "confirm on site".

## Scale bridge A: receiving

One unit, `TF01-U-RCV-SCB01`. The bridge reads the scale. The tablet handles supplier, area, maturity and photos and talks to the bridge over Wi-Fi.

| Bridge terminal | Connects to | Device ID | Cable |
| --- | --- | --- | --- |
| RS-232 TX, RX, GND | Avery indicator data port | Scale (no ID) | Shielded RS-232, DB9, max 15 m |
| Wi-Fi | Rugged tablet | `TF01-U-RCV-TAB01` | None |
| Tablet Bluetooth | QR scanner | `TF01-U-RCV-QRS01` | None |
| Tablet Bluetooth | Receipt printer, optional | `TF01-U-RCV-PRN01` | None |
| +24 V, 0 V | 24 V DC supply | None | Internal |
| Keypad, display ports | Door-mounted keypad and display | None | Internal ribbon |

## Scale bridge B: withered weigh

One unit, `TF01-U-WWB-SCB01`. The relays switch the stack light locally, so the over-limit alarm works without a network.

| Bridge terminal | Connects to | Device ID | Cable |
| --- | --- | --- | --- |
| Serial 1, RS-232 TX, RX, GND | Avery indicator data port | Scale (no ID) | Shielded RS-232, DB9, max 15 m |
| Serial 2 | QR scanner | `TF01-U-WWB-QRS01` | RS-232 or TTL (confirm on site) |
| R1 | Stack light red and buzzer | `TF01-U-WWB-STL01` | 4-core, 24 V |
| R2 | Stack light amber | `TF01-U-WWB-STL01` | Same cable |
| R3 | Stack light green | `TF01-U-WWB-STL01` | Same cable |
| Relay common | +24 V | None | Same cable |
| +24 V, 0 V | 24 V DC supply | None | Internal |
| Keypad, display ports | Door-mounted keypad and display | None | Internal ribbon |

## Scale bridges W1 to W4: rolling

Four identical units, one per stage weigh point. Each unit's stage is set in its configuration, so the operator only enters the batch and, at W3 or W4, the bulk flag.

| Bridge terminal | Connects to | Device ID | Cable |
| --- | --- | --- | --- |
| RS-232 TX, RX, GND | Avery indicator at that stage | Scale (no ID) | Shielded RS-232, DB9, max 15 m |
| +24 V, 0 V | 24 V DC supply | None | Internal |
| Keypad, display ports | Door-mounted keypad and display | None | Internal ribbon |

Units: `TF01-L-RW1-SCB01`, `TF01-L-RW2-SCB01`, `TF01-L-RW3-SCB01`, `TF01-L-RW4-SCB01`.

## Scale bridge D: drier output

One unit, `TF01-L-DRO-SCB01`. Same as B without the scanner. The keypad also takes the made-tea moisture reading from the handheld meter.

| Bridge terminal | Connects to | Device ID | Cable |
| --- | --- | --- | --- |
| RS-232 TX, RX, GND | Avery indicator data port | Scale (no ID) | Shielded RS-232, DB9, max 15 m |
| R1 | Stack light red and buzzer | `TF01-L-DRO-STL01` | 4-core, 24 V |
| R2 | Stack light amber | `TF01-L-DRO-STL01` | Same cable |
| R3 | Stack light green | `TF01-L-DRO-STL01` | Same cable |
| Relay common | +24 V | None | Same cable |
| +24 V, 0 V | 24 V DC supply | None | Internal |
| Keypad, display ports | Door-mounted keypad and display | None | Internal ribbon |

## Trough node, 11 units

One node per trough, same build; only the trough number changes (`TF01-U-TR01-NOD01` to `TF01-U-TR11-NOD01`). Mount near the fan end so the bus runs from the plenum sensor to the far end.

| Order on bus | Device ID (trough nn) | Device | Modbus address (proposed) | Cable |
| --- | --- | --- | --- | --- |
| 1 | `TF01-U-TRnn-THS01` | Temperature/humidity, plenum | 1 | 2-pair STP |
| 2 | `TF01-U-TRnn-THS02` | Temperature/humidity, above leaf, near end | 2 | 2-pair STP |
| 3 | `TF01-U-TRnn-THS03` | Temperature/humidity, above leaf, far end | 3 | 2-pair STP |
| 4 | `TF01-U-TRnn-CTS01` | Current module, clamp on the 7.5 hp fan supply | 21 | 2-pair STP; clamp lead as supplied |
| End | Terminator | 120 Ω across A and B | None | None |

The current clamp goes around one phase conductor of the fan supply, not the whole cable. A qualified electrician fits it.

## Rolling nodes, 3 units

Each node serves three rollers, with one temperature/humidity sensor and one motor current module per roller, wired roller by roller along the floor.

| Node | Order on bus | Device ID | Modbus address (proposed) |
| --- | --- | --- | --- |
| `TF01-L-ROL-NOD01` | 1 to 6 | RC1-THS01, RC1-CTS01, RC2-THS01, RC2-CTS01, RC3-THS01, RC3-CTS01 | 1, 21, 2, 22, 3, 23 |
| `TF01-L-ROL-NOD02` | 1 to 6 | R21-THS01, R21-CTS01, R22-THS01, R22-CTS01, R23-THS01, R23-CTS01 | 1, 21, 2, 22, 3, 23 |
| `TF01-L-ROL-NOD03` | 1 to 6 | R31-THS01, R31-CTS01, R32-THS01, R32-CTS01, R41-THS01, R41-CTS01 | 1, 21, 2, 22, 3, 23 |

All IDs carry the `TF01-L-` prefix. 2-pair STP throughout, 120 Ω terminator after the last device on each bus.

## Fermentation nodes, 2 units

The 8 IR sensors are split across two nodes so no bus run crosses the whole room. Assumes Modbus IR sensors; a 4–20 mA model would wire to the node's analogue inputs instead (confirm on site).

| Node | Order on bus | Device ID | Device | Modbus address (proposed) |
| --- | --- | --- | --- | --- |
| `TF01-L-FER-NOD01` | 1 to 3 | `TF01-L-FER-THH01` to `THH03` | Room temperature/humidity, condensing-rated | 1, 2, 3 |
| `TF01-L-FER-NOD01` | 4 to 7 | `TF01-L-FER-IRS01` to `IRS04` | IR surface sensor, spots 1 to 4 | 31 to 34 |
| `TF01-L-FER-NOD02` | 1 to 4 | `TF01-L-FER-IRS05` to `IRS08` | IR surface sensor, spots 5 to 8 | 35 to 38 |

Aim each IR sensor straight down at its spot, at a height that keeps its view on the leaf (check field of view on site). Mount room probes away from doors and humidifier outlets.

## Drier node, 1 unit

The three thermocouples connect to a 4-channel thermocouple module; only the module sits on the RS-485 bus. Keep the node box out of the drier's heat; only the probe tips go into the hot air.

| Order on bus | Device ID | Device | Modbus address (proposed) | Cable |
| --- | --- | --- | --- | --- |
| 1 | `TF01-L-DRY-TCM01` | 4-channel thermocouple module | 41 | 2-pair STP |
| CH1 on TCM01 | `TF01-L-DRY-TCK01` | K-type, inlet duct from the stove | None | K-type compensating cable, observe polarity |
| CH2 on TCM01 | `TF01-L-DRY-TCK02` | K-type, made-tea outlet | None | K-type compensating cable |
| CH3 on TCM01 | `TF01-L-DRY-TCK03` | K-type, exhaust duct | None | K-type compensating cable |
| 2 | `TF01-L-DRY-CTS01` | Current module, drier fan and chain motor | 21 | 2-pair STP; clamp lead as supplied |
| End | Terminator | 120 Ω across A and B | None | None |

## Ambient node, 1 unit

One outdoor sensor. On a very short run (a few metres) the terminator may not be needed; confirm on site.

| Order on bus | Device ID | Device | Modbus address (proposed) | Cable |
| --- | --- | --- | --- | --- |
| 1 | `TF01-G-ENV-THS01` | Outdoor temperature/humidity in radiation shield | 1 | 2-pair STP, UV-resistant jacket outdoors |
| End | Terminator | 120 Ω across A and B | None | None |

## Common parts for one box

| Part | Specification | Per box |
| --- | --- | --- |
| Enclosure | IP65 polycarbonate, with a display window on bridges | 1 |
| DIN rail | 35 mm, cut to fit | 1 |
| Circuit breaker or fuse | On the 230 V supply | 1 |
| Surge protector | DIN-rail, 230 V AC | 1 |
| 24 V DC supply | DIN-rail, rated for controller plus all bus sensors | 1 |
| Controller | Industrial ESP32 (nodes) or ESP32-S3 bridge board (bridges), DIN-rail | 1 |
| Terminal blocks | For 230 V, 24 V, RS-485 A/B/0 V, relays | As needed |
| Earth bar | Protective earth and bus cable shields | 1 |
| Cable glands | IP68, sized to each cable | 1 per cable |
| 120 Ω terminator | Far end of each RS-485 bus | 1 per node |
| External Wi-Fi antenna | Only if the enclosure blocks the signal; confirm on site | 0 or 1 |
| ID label | Engraved or printed with the device ID | 1 |

Totals: 7 scale bridges, 18 zone nodes; on the buses 43 temperature/humidity sensors, 3 condensing-rated probes, 8 IR sensors, 1 thermocouple module with 3 thermocouples, 21 current modules.
