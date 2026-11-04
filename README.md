# Tea Factory Automation

IoT data collection for a two-floor orthodox black tea factory, currently run fully by hand. Phase 1 collects weights and conditions. Phase 2 will add control.

## How the leaf moves, and where it is weighed

| Step | Where | Measured |
|---|---|---|
| Receiving (A) | Upper floor intake | Supplier QR, sack weight, trough (1–11) and area (1–8) |
| Withering, ~8 h | 11 troughs, 1 × 7.5 hp fan each | Temperature and humidity (3 per trough), fan current |
| Withered weigh (B) | Above 3 chutes | Crate weight by trough and area; max-weight limit with buzzer and red light |
| Rolling (W1–W4) | Lower floor: 3 charging, 3 second, 2 third, 1 fourth roller | Weight continuing after each sieving; dhool calculated |
| Fermentation, ~2.5 h | Lower floor | Room temperature and humidity, 8 surface temperature spots |
| Drying (D), ~21 min | Wood-fired drier at outer wall | Inlet, outlet and exhaust temperatures; made-tea weight |

## Key calculations

- Moisture loss per supplier = (received at A − withered at B) ÷ received at A
- Dhool: `Ws1 = Wz − W1`, `Ws2 = W1 − W2`, `Ws3 = W2 − W3`, `Ws4 = W3 − W4`; W3 or W4 is marked as bulk
- Batch out-turn = made tea at D ÷ green leaf in the batch
- Supplier share of a batch = supplier's withered weight ÷ Wz

## Hardware approach

- Avery scales (RS-232) read by custom ESP32 scale bridges: 7 units (A, B, W1–W4, D)
- Sensors wired on RS-485 Modbus to 18 industrial ESP32 zone nodes
- Nodes and bridges send over Wi-Fi to AWS IoT Core

## Repository

- `dashboard/index.html`: plant-mimic dashboard prototype (simulated data)
- `docs/floor-plans/`: original floor sketches and the reference layout
