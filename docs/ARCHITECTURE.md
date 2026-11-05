# Architecture

Self-hosted. One Docker Compose stack runs on the owner's laptop for development, then unchanged on a VPS (plus HTTPS). No managed cloud IoT services.

```
 Factory                                      Laptop / VPS (docker compose)
 ┌──────────────────────────┐                 ┌─────────────────────────────────────────────┐
 │ Sensors ─RS-485─► Zone   │                 │  EMQX (MQTT 5, TLS, per-device auth)        │
 │ (Modbus)          node   │──┐              │     │                                       │
 │                  ESP32   │  │   MQTT/TLS   │     ▼                                       │
 │ Avery ─RS-232─► Scale    │  ├─ Wi-Fi ────► │  ingest worker ──► TimescaleDB ◄── api      │
 │ scale           bridge   │  │   internet   │  (backend)          (Postgres)     (REST,   │
 │                  ESP32   │──┘              │     ▲   alarm/rule engine            WebSocket)
 │ Tablet at A ─────────────┘── HTTPS ──────► │     └── settings & commands ──► EMQX        │
 └──────────────────────────┘                 │  Caddy ─► dashboard (static) + api          │
                                              │  Grafana (optional, ad-hoc charts)          │
                                              └─────────────────────────────────────────────┘
```

## Services

| Service | Choice | Role |
|---|---|---|
| `mqtt` | EMQX 5 | Device connections; per-device credentials and topic ACLs; last-will for online/offline; TLS on 8883 |
| `db` | TimescaleDB (PostgreSQL 16) | Time-series readings in hypertables plus relational business data (suppliers, areas, batches, weighings) in one database, so supplier-to-batch reports are SQL joins. Compression and retention policies |
| `backend` | Python 3.12, FastAPI, aiomqtt, asyncpg | Three parts in one codebase: **ingest** (MQTT → DB, validates against device profiles), **api** (REST + WebSocket for the dashboard and the tablet at A), **engine** (alarm rules, offline detection, settings push) |
| `dashboard` | Existing plant mimic (`dashboard/index.html`) | Served as static files; simulated data replaced by the API and WebSocket |
| `proxy` | Caddy | Single entry point; automatic HTTPS on the VPS |
| `grafana` | Grafana (optional) | Exploration and engineering charts direct from TimescaleDB |
| `simulator` | Python (dev only) | Publishes realistic data for all 25 devices so the stack runs without hardware |

## Ideas adopted

From ThingsBoard:

- **Device profiles.** A profile defines a device type's telemetry keys, units, valid ranges, default settings and alarm rules. Stored as data. Adding a sensor type in Phase 2 = add a profile.
- **Telemetry vs attributes.** Telemetry: time-stamped readings. Attributes: current values, in three kinds: *client* (reported by the device, e.g. firmware version), *server* (set by the platform, e.g. location), *shared* (set on the server and pushed to the device, e.g. B's max crate weight).
- **Alarms with a lifecycle:** active → acknowledged → cleared; severity (critical, major, warning); one open alarm per type per device.
- **RPC** for commands to devices. Reserved for Phase 2 control.

From OpenRemote:

- **Asset tree.** Site → floor → zone → device. Readings attach to devices; dashboards and reports query by asset, so a replaced sensor keeps the zone's history.
- **When-then rules stored as data**, editable from the dashboard, e.g. "fermentation surface > 30 °C for 5 min → major alarm".
- **Protocol adapters.** MQTT now; a Modbus TCP adapter later for gateways without an ESP32.
- **Edge gateway** (later): a small broker in the factory bridging to the VPS so the site keeps working through internet cuts. Devices already buffer ≥ 7 days.

## MQTT topic contract

Prefix `tf01/{device_id}/`. Device IDs from `docs/DEVICES.md`. QoS 1 for events and settings, QoS 0 allowed for high-rate telemetry.

| Topic | Direction | Content |
|---|---|---|
| `telemetry` | device → server | Batched sensor readings |
| `event` | device → server | Weighings and operator actions (A, B, W1–W4, D) |
| `attributes` | device → server | Client attributes: firmware, settings in use, RSSI |
| `attributes/desired` | server → device | Shared attributes (settings); **retained**, so a rebooted device gets them on connect |
| `rpc/req`, `rpc/res` | both | Commands with request ID (Phase 2) |
| `status` | device → server | `online` on connect; `offline` as last-will, retained |

Every message carries `ts` (device time, UTC ISO 8601 with ms) and a unique `msg_id` (ULID) so retransmits after an outage are de-duplicated.

```json
// tf01/TF01-U-TR03-NOD01/telemetry
{"msg_id":"01JC9X...","ts":"2026-11-05T08:15:00.000Z",
 "readings":[
  {"sensor":"TF01-U-TR03-THS01","t_c":31.4,"rh_pct":58.2},
  {"sensor":"TF01-U-TR03-CTS01","amp":9.8,"run":true}]}

// tf01/TF01-U-WWB-SCB01/event
{"msg_id":"01JC9Y...","ts":"2026-11-05T08:15:02.120Z","type":"crate_weighed",
 "trough_no":3,"area_no":5,"crate_id":"CR-017","gross_kg":24.6,"tare_kg":2.1,
 "net_kg":22.5,"max_limit_kg":25.0,"over_limit":false,"stable":true,"operator_id":"OP12"}

// tf01/TF01-U-WWB-SCB01/attributes/desired  (retained)
{"max_limit_kg":25.0,"amber_pct":5,"min_weight_kg":0.5,"stability_band_kg":0.05}
```

## Data model (TimescaleDB)

Platform tables (generic, reusable for any sensor):

| Table | Key columns | Notes |
|---|---|---|
| `asset` | id, parent_id, type (site/floor/zone), code, name | Tree |
| `device_profile` | id, name, telemetry_schema (JSON: keys, units, ranges), default_settings, alarm_rules | Extensibility point |
| `device` | id (e.g. `TF01-U-TR03-NOD01`), profile_id, asset_id, credentials, last_seen | |
| `sensor` | id (e.g. `TF01-U-TR03-THS01`), device_id, asset_id, kind, modbus_addr | |
| `telemetry` | ts, sensor_id, key, value (double) | **Hypertable**; compressed after 7 days; continuous aggregates per minute and hour |
| `attribute` | entity_id, scope (client/server/shared), key, value (JSON), updated_at | |
| `alarm` | id, entity_id, type, severity, status, started_at, acked_by, cleared_at, details | |
| `rule` | id, name, asset/profile scope, condition (JSON), action (JSON), enabled | When-then rules |
| `audit_log` | ts, user, entity, action, old, new, reason | Every setting change and correction |

Business tables (tea process):

| Table | Key columns |
|---|---|
| `supplier` | id (QR value), name, contact, active |
| `delivery`, `sack_weighing` | supplier, gross, deductions, net, ts |
| `area_load` | trough_no, area_no, supplier_id, alloc_kg, maturity, photos, loaded_at |
| `area_cycle` | trough_no, area_no, loaded_at, unloaded_at |
| `crate_weighing` | cycle_id, crate_id, net, over_limit, batch_id |
| `batch` | id, opened_at, Wz, bulk_stage, fermentation_start/end, status |
| `stage_weighing` | batch_id, stage (1–4), net |
| `drier_output` | batch_id, net, moisture_pct |

Reports (moisture loss, dhool, out-turn, supplier attribution) are SQL views over these, per the formulas in `docs/PROCESS.md`.

## Adding a new sensor type (Phase 2 example)

1. Insert a `device_profile` (or extend one) with the new telemetry keys, units, ranges and alarm rules.
2. Register the `sensor` rows with IDs following `docs/DEVICES.md`.
3. The node firmware adds the reading to its `telemetry` payload.
4. No backend or database schema change. The dashboard shows it through the generic device view; a custom mimic tile is optional.

## Security

- Per-device MQTT credentials, ACL: a device may publish only under its own `tf01/{device_id}/` and subscribe only to its own `attributes/desired` and `rpc/req`.
- TLS on MQTT and HTTPS on the VPS; plain MQTT 1883 allowed only on the laptop dev network.
- Dashboard users with roles: owner, manager, operator, admin.
- Daily `pg_dump` plus volume backups on the VPS.

## Repo layout (target)

```
deploy/            docker-compose.yml, .env.example, emqx/, caddy/, grafana/
backend/           FastAPI app: ingest/, api/, engine/, models/, migrations/
db/                SQL schema, seed data (assets, profiles, devices, sensors)
simulator/         dev data generator for all devices
dashboard/         plant-mimic UI
firmware/
  scale-bridge/    ESP32 Avery bridge (PlatformIO)
  zone-node/       ESP32 Modbus node (PlatformIO)
  avery-sim/       ESP32-C3 fake Avery for the bench POC
tools/             avery-capture script, provisioning scripts
docs/
```
