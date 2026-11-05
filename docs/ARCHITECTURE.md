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
| `audit_log` | ts, user, entity, action, old, new, reason | Every setting change and correction; append-only |
| `telemetry_latest` | sensor_id, key, ts, value | Latest value per sensor and key, for the live view |
| `app_user` | username, password_hash (scrypt), role | Dashboard users: owner, manager, operator, admin |
| `ingest_msg` | msg_id, device_id, topic_kind, ts | Accepted message IDs for de-duplication; pruned after 30 days |
| `ingest_reject` | received_at, device_id, topic, reason, payload | Messages or readings that failed validation |
| `event_log` | msg_id, device_id, ts, type, payload | Raw copy of every device event as sent; append-only |

Telemetry is stored per sensor and key; booleans (e.g. `run`) as 0/1. The
`sensor` table also holds non-measuring peripherals (`measuring = false`):
the thermocouple module, stack lights, QR scanners, the tablet and printer.

Business tables (tea process):

| Table | Key columns |
|---|---|
| `supplier` | id (QR value), name, contact, active, auto_created (unknown QR seen at A) |
| `delivery` | id, supplier_id, started_at (one supplier visit at A) |
| `sack_weighing` | delivery, supplier, gross, tare, wet/coarse deductions, net, trough_no, area_no, cycle_id, maturity, photos |
| `area_cycle` | trough_no, area_no, loaded_at, unloaded_at (one fill and empty of an area) |
| `crate_weighing` | cycle_id, trough_no, area_no, crate_id, net, max_limit_kg, batch_id |
| `batch` | id, opened_at, bulk_stage, fermentation_start/end, status (Wz is computed) |
| `stage_weighing` | batch_id, stage (1–4), net, bulk |
| `drier_output` | batch_id, batch_assigned (device, time_window, operator), net, moisture_pct |

**Weighings are append-only.** Triggers refuse UPDATE and DELETE on the four
weighing tables (and on `event_log`, `audit_log`). A correction is a new row
with `corrects_id` pointing at the original (never at another correction),
`voided`, `reason` and `created_by`. The `*_effective` views give the latest
version of each original with voided ones removed; reports read only those.
Over-limit crates at B and made tea at D are not recorded as weighings (the
operator re-weighs); they stay in `event_log` and raise an `over_limit` alarm.

Reports are SQL views, per the formulas in `docs/PROCESS.md` (`db/020_reports.sql`):
`area_cycle_summary`, `supplier_area` (supplier share of an area, the
earlier `area_load` idea), `moisture_loss_supplier`, `cycle_batch`,
`supplier_batch`, `batch_summary` (Wz, W1–W4, dhool, green leaf, made tea,
out-turn, stage warnings) and `supplier_batch_attribution`.

## Adding a new sensor type (Phase 2 example)

1. Insert a `device_profile` (or extend one) with the new telemetry keys, units, ranges and alarm rules.
2. Register the `sensor` rows with IDs following `docs/DEVICES.md`.
3. The node firmware adds the reading to its `telemetry` payload.
4. No backend or database schema change. The dashboard shows it through the generic device view; a custom mimic tile is optional.

## Alarms and rules in practice

- Rule condition: `{"sensor_kind","key","op","value","for_s","hysteresis","position"}`.
  Raises once the condition has held `for_s` seconds of device time; clears
  when the value is back past the threshold by `hysteresis`. The same format
  is used in profile `alarm_rules` and the `rule` table.
- Built-in alarm types besides rules: `offline` (last-will, or no data for the
  profile's `offline_after_s`), `over_limit` (B, D), `wN_exceeds_previous`
  (validation rule Wn ≤ W(n−1), on the batch).
- Settings: shared attributes, validated against the profile's
  `default_settings` keys and types, audited, published retained on
  `attributes/desired` and re-published to every device whenever the
  backend reconnects. The device reports what it uses in its `settings`
  client attribute; the dashboard shows desired vs reported.

## Security

- Per-device MQTT credentials, ACL: a device may publish only under its own `tf01/{device_id}/` and subscribe only to its own `attributes/desired` and `rpc/req`.
- TLS on MQTT and HTTPS on the VPS; plain MQTT 1883 allowed only on the laptop dev network.
- Dashboard users with roles: owner, manager, operator, admin. Every role views and acknowledges alarms; owner, manager and admin change settings and rules, correct weighings and edit batches; owner and admin manage users and profiles. Passwords are scrypt-hashed; the API issues HMAC-signed bearer tokens (12 h). The first admin comes from `ADMIN_USERNAME`/`ADMIN_PASSWORD`.
- Daily `pg_dump` plus volume backups on the VPS.

## Repo layout

```
deploy/            docker-compose.yml, .env.example, emqx/, caddy/, grafana/
backend/           FastAPI app: app/ingest/, app/engine/, app/api/; tests/
db/                SQL applied on first start: 001 schema, 002 time-series
                   policies, 010 seed (assets, profiles, devices, sensors),
                   020 report views
simulator/         dev data generator for all devices
dashboard/         plant-mimic UI: index.html, css/, js/ (ES modules, no
                   build); prototype.html is the original simulated mock-up
firmware/
  scale-bridge/    ESP32 Avery bridge (PlatformIO)
  zone-node/       ESP32 Modbus node (PlatformIO)
  avery-sim/       ESP32-C3 fake Avery for the bench POC
tools/             avery-capture script, provisioning scripts
docs/
```
