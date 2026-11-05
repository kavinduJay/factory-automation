# Roadmap

"You" = Kavindu, on site or with hardware. "Claude" = can be done in a coding session. Tick items as they are done.

## Stage 1: Project context and plan

- [x] README, dashboard prototype and floor-plan sketches in the repo
- [x] `CLAUDE.md`, `docs/PROCESS.md`, `docs/DEVICES.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`
- [ ] You: review the docs and correct anything wrong

**Done when** a fresh session in the repo can explain the project without being told.

## Stage 2: Docker stack on the laptop, with simulated devices

No hardware needed. Gives the whole system running end to end.

- [ ] Claude: `deploy/docker-compose.yml` with EMQX, TimescaleDB, backend, dashboard, Caddy, optional Grafana; `.env.example`
- [ ] Claude: `db/` schema (platform + business tables, hypertable, compression, continuous aggregates) and seed data for TF01 assets, profiles, all 25 devices and 78 sensors
- [ ] Claude: backend ingest (MQTT → DB, profile validation, de-duplication by `msg_id`)
- [ ] Claude: backend API (REST + WebSocket): live state, history, weighings, batches, alarms, settings
- [ ] Claude: engine: alarm rules from profiles and `rule` table, offline detection, settings push via retained `attributes/desired`
- [ ] Claude: `simulator/` publishing realistic telemetry and weighing events for all devices
- [ ] Claude: dashboard switched from built-in simulation to the API and WebSocket
- [ ] Claude: SQL views for moisture loss, dhool, out-turn, supplier attribution; tests on the worked example in `docs/PROCESS.md`
- [ ] You: `docker compose up` on the laptop and click through

**Done when** the simulator's data shows live on the dashboard, alarms fire and clear, and a setting changed on the dashboard reaches the simulated device.

## Stage 3: Capture the Avery scale output

- [ ] Claude: `tools/avery-capture/` script: logs the raw serial stream to file, tries 9600/4800/2400 baud, shows text and hex
- [ ] You: buy a USB-to-RS-232 adapter (FTDI or Prolific chip)
- [ ] You: at the factory, note the scale model, photograph the indicator settings menu
- [ ] You: record empty, 10 kg and 20 kg; try continuous and print modes
- [ ] Claude: work out the format and write the parser with tests against the log

**Done when** the parser turns the recorded stream into weight + stable flag.

## Stage 4: Scale-bridge firmware on the bench (2 × ESP32-C3)

- [ ] Claude: `firmware/avery-sim/` fake Avery sending the captured format (or a generic format until stage 3 is done)
- [ ] Claude: `firmware/scale-bridge/` read serial via TTL converter, stability check, OLED display
- [ ] Claude: keypad entry for trough, area, stage; operator flow per station
- [ ] Claude: over-limit red/amber/green + buzzer, limit from `attributes/desired`
- [ ] Claude: MQTT to the laptop EMQX, flash buffer for outages, `msg_id` per event
- [ ] You: wire the breadboard, flash both boards, test settling, over-limit and Wi-Fi loss

**Done when** a bench weight appears on the laptop dashboard with trough and area, the alarm fires over the limit, and a Wi-Fi outage loses nothing.

## Stage 5: Move to the VPS

- [ ] You: provision a VPS and a domain or subdomain
- [ ] Claude: Caddy HTTPS, EMQX TLS on 8883, per-device credentials, firewall, backups
- [ ] Claude: deploy script; same compose file with a VPS `.env`
- [ ] You: point the bench bridge at the VPS

**Done when** the bench bridge reports to the VPS over TLS and the dashboard is reachable over HTTPS.

## Stage 6: Scale out in the factory

- [ ] Real bridges: A (with tablet app), B (with stack light), W1–W4, D, on industrial boards in IP65 enclosures
- [ ] `firmware/zone-node/` Modbus RS-485 polling per `docs/DEVICES.md`
- [ ] One trough node with 3 THS + fan CTS; test on one trough
- [ ] Remaining troughs, rolling, fermentation, drier, ambient nodes
- [ ] Supplier and batch reports, receipts at A
- [ ] Trial alongside paper records; operator training

**Done when** all 7 bridges and 18 nodes report and the figures match the paper records.

## Phase 2 (later)

- More sensor types via device profiles
- Edge gateway in the factory
- Control: trough fan speed (VFDs), fermentation humidity, drier inlet temperature; advisory first, then closed loop with manual override
