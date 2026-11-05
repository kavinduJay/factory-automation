# Backend

One Python process (FastAPI, aiomqtt, asyncpg) with three parts:

| Part | Code | Does |
|---|---|---|
| ingest | `app/ingest/` | Subscribes to `tf01/+/{telemetry,event,attributes,status}`; de-duplicates by `msg_id`; validates against the device profile (`validate.py`, pure); writes telemetry, raw events and business records (`business.py`) |
| engine | `app/engine/` | Alarm rules from profiles and the `rule` table (`rules.py`, pure); offline detection; settings push on retained `attributes/desired` (`settings.py`) |
| api | `app/api/` | REST under `/api`, WebSocket at `/api/ws`, login and roles (`auth.py`). OpenAPI docs at `/api/docs` |

The schema lives in `../db/*.sql` (applied by the TimescaleDB container on
first start), not in migrations. To change it on an existing volume, write an
idempotent SQL file and apply it with `psql`, or rebuild the volume in dev.

## Tests

The DB tests build a scratch database from `../db/*.sql` with `psql`, feed
device messages through ingest, and check the tables and report views,
including the worked example from `docs/PROCESS.md`.

```bash
cd deploy && docker compose run --rm backend pytest -q
```

Or locally, with Python 3.12+ and psql, against any TimescaleDB:

```bash
pip install -r requirements-dev.txt
TEST_DB_ADMIN_URL=postgresql://tf01:PASSWORD@localhost:5432/postgres pytest -q
```

## API overview

| Endpoint | Role |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/password` | any |
| `GET /api/live` (devices, latest readings, open alarms, settings, loaded areas, last events), `/api/summary` | any |
| `GET /api/history?sensor_id=..&key=..&from=..&to=..&resolution=auto\|raw\|1m\|1h` | any |
| `GET /api/assets`, `/profiles`, `/devices`, `/devices/{id}`, `/sensors`, `/areas`, `/suppliers`, `/events` | any |
| `GET /api/weighings/{sack\|crate\|stage\|drier}` (effective, or `history=true`) | any |
| `POST /api/weighings/{kind}/{id}/correct` `{changes, voided, reason}` | owner, manager, admin |
| `GET /api/batches`, `/batches/{id}`; `PATCH /api/batches/{id}` | any; edit: owner, manager, admin |
| `GET /api/reports/moisture-loss`, `/reports/supplier-attribution`, `/reports/areas` | any |
| `GET /api/alarms?status=open\|all\|cleared`; `POST /api/alarms/{id}/ack` | any |
| `GET/PUT /api/devices/{id}/settings` | view any; change: owner, manager, admin |
| `GET/POST/PUT/DELETE /api/rules` | view any; change: owner, manager, admin |
| `PATCH /api/profiles/{id}` (telemetry schema, alarm rules, defaults) | owner, admin |
| `GET/POST/PATCH /api/users` | owner, admin |
| `GET /api/audit`, `/ingest/stats`, `/ingest/rejects` | audit: owner, manager, admin |

WebSocket messages: `telemetry`, `event`, `alarm`, `device` (online/offline),
`attributes` (client or shared), `correction`, plus `hello`/`pong`.

## Known limits (stage 2)

- The "condition has held for `for_s`" timers are in memory, so a backend
  restart restarts them; open alarms survive and still clear.
- The trough `fan_stopped` rule also fires for an empty trough with its fan
  off. A rule condition cannot yet depend on trough state.
- MQTT has no authentication on the laptop; per-device credentials and ACLs
  come with TLS in stage 5.
- Tokens are stateless (12 h); disabling a user takes effect on their next
  request because every request re-checks the user.
