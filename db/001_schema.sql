-- TF01 database schema.
-- Runs once on an empty TimescaleDB volume (docker-entrypoint-initdb.d), in
-- file-name order: 001 schema, 002 time-series policies, 010 seed, 020 reports.
--
-- Platform tables are generic (assets, profiles, devices, sensors, telemetry,
-- attributes, alarms, rules). Business tables hold the tea process records.
-- Weighings are business records: they are append-only (see forbid_change).
-- A correction is a new row with corrects_id pointing at the original.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Platform
-- ---------------------------------------------------------------------------

-- Site -> floor -> zone. IDs follow docs/DEVICES.md: TF01, TF01-U, TF01-U-TR03.
CREATE TABLE asset (
    id          text PRIMARY KEY,
    parent_id   text REFERENCES asset(id),
    type        text NOT NULL CHECK (type IN ('site', 'floor', 'zone')),
    code        text NOT NULL,
    name        text NOT NULL,
    meta        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX asset_parent_idx ON asset(parent_id);

-- The extensibility point. A profile describes a device type:
--   telemetry_schema: {"<sensor kind>": {"<key>": {"unit", "min", "max", "type"}}}
--   event_schema:     {"<event type>": {"required": [...], "numeric": [...]}}
--   default_settings: shared attributes pushed to the device
--   alarm_rules:      [{"type","severity","message","sensor_kind","key","op",
--                       "value","for_s","hysteresis","position"}]
-- Adding a sensor type = adding a kind to a profile's telemetry_schema.
CREATE TABLE device_profile (
    id               text PRIMARY KEY,
    name             text NOT NULL,
    description      text NOT NULL DEFAULT '',
    device_kind      text NOT NULL CHECK (device_kind IN ('zone_node', 'scale_bridge')),
    telemetry_schema jsonb NOT NULL DEFAULT '{}',
    event_schema     jsonb NOT NULL DEFAULT '{}',
    default_settings jsonb NOT NULL DEFAULT '{}',
    alarm_rules      jsonb NOT NULL DEFAULT '[]',
    offline_after_s  integer NOT NULL DEFAULT 60
);

CREATE TABLE device (
    id                 text PRIMARY KEY,           -- e.g. TF01-U-TR03-NOD01
    profile_id         text NOT NULL REFERENCES device_profile(id),
    asset_id           text NOT NULL REFERENCES asset(id),
    name               text NOT NULL,
    point              text,                       -- weigh point A, B, W1..W4, D
    config             jsonb NOT NULL DEFAULT '{}',-- fixed per unit, e.g. {"stage": 2}
    credentials        text,                       -- stage 5: MQTT password hash
    online             boolean NOT NULL DEFAULT false,
    last_seen          timestamptz,
    status_changed_at  timestamptz
);

-- Measuring sensors plus non-measuring peripherals (thermocouple module,
-- stack lights, QR scanners, tablet, printer), told apart by `measuring`.
CREATE TABLE sensor (
    id           text PRIMARY KEY,                 -- e.g. TF01-U-TR03-THS01
    device_id    text NOT NULL REFERENCES device(id),
    asset_id     text NOT NULL REFERENCES asset(id),
    kind         text NOT NULL,                    -- THS, THH, IRS, TCK, TCM, CTS, STL, QRS, TAB, PRN
    name         text NOT NULL,
    position     text,                             -- plenum, near_end, inlet, ...
    measuring    boolean NOT NULL DEFAULT true,
    modbus_addr  integer,
    channel      integer,                          -- thermocouple channel on the TCM
    active       boolean NOT NULL DEFAULT true,
    meta         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX sensor_device_idx ON sensor(device_id);
CREATE INDEX sensor_asset_idx ON sensor(asset_id);

-- Readings. One row per sensor, key and timestamp. Booleans are stored as 0/1.
CREATE TABLE telemetry (
    ts         timestamptz NOT NULL,
    sensor_id  text NOT NULL,
    key        text NOT NULL,
    value      double precision NOT NULL
);
SELECT create_hypertable('telemetry', 'ts', chunk_time_interval => interval '1 day');
CREATE UNIQUE INDEX telemetry_sensor_key_ts_idx ON telemetry(sensor_id, key, ts DESC);

-- Latest value per sensor and key, kept by ingest for the live view.
CREATE TABLE telemetry_latest (
    sensor_id  text NOT NULL REFERENCES sensor(id),
    key        text NOT NULL,
    ts         timestamptz NOT NULL,
    value      double precision NOT NULL,
    PRIMARY KEY (sensor_id, key)
);

-- client: reported by the device; server: set by the platform;
-- shared: set on the server and pushed to the device (attributes/desired).
CREATE TABLE attribute (
    entity_id   text NOT NULL,
    scope       text NOT NULL CHECK (scope IN ('client', 'server', 'shared')),
    key         text NOT NULL,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_id, scope, key)
);

-- active -> acked -> cleared (or active -> cleared, acked later).
-- At most one open (not cleared) alarm per entity and type.
CREATE TABLE alarm (
    id          bigserial PRIMARY KEY,
    entity_id   text NOT NULL,                     -- sensor, device or batch ID
    device_id   text,
    type        text NOT NULL,
    severity    text NOT NULL CHECK (severity IN ('critical', 'major', 'warning')),
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'acked', 'cleared')),
    message     text NOT NULL DEFAULT '',
    started_at  timestamptz NOT NULL DEFAULT now(),
    acked_by    text,
    acked_at    timestamptz,
    cleared_at  timestamptz,
    rule_id     integer,
    details     jsonb NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX alarm_one_open_idx ON alarm(entity_id, type) WHERE cleared_at IS NULL;
CREATE INDEX alarm_started_idx ON alarm(started_at DESC);

-- When-then rules stored as data, editable from the dashboard.
--   condition: {"sensor_kind","key","op","value","for_s","hysteresis","position"}
--   action:    {"alarm_type","severity","message"}
-- Scope: a rule applies to sensors under scope_asset_id (any depth) and/or on
-- devices of scope_profile_id. Both null = every sensor.
CREATE TABLE rule (
    id                serial PRIMARY KEY,
    name              text NOT NULL,
    scope_asset_id    text REFERENCES asset(id),
    scope_profile_id  text REFERENCES device_profile(id),
    condition         jsonb NOT NULL,
    action            jsonb NOT NULL,
    enabled           boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id        bigserial PRIMARY KEY,
    ts        timestamptz NOT NULL DEFAULT now(),
    username  text NOT NULL,
    entity    text NOT NULL,
    action    text NOT NULL,
    old       jsonb,
    new       jsonb,
    reason    text
);
CREATE INDEX audit_log_ts_idx ON audit_log(ts DESC);

CREATE TABLE app_user (
    id             serial PRIMARY KEY,
    username       text NOT NULL UNIQUE,
    display_name   text NOT NULL DEFAULT '',
    password_hash  text NOT NULL,
    role           text NOT NULL CHECK (role IN ('owner', 'manager', 'operator', 'admin')),
    active         boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Every accepted MQTT message ID, for de-duplication of retransmits after an
-- outage. Devices buffer up to 7 days; the engine prunes rows older than 30.
CREATE TABLE ingest_msg (
    msg_id       text PRIMARY KEY,
    device_id    text NOT NULL,
    topic_kind   text NOT NULL,
    ts           timestamptz,
    received_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ingest_msg_received_idx ON ingest_msg(received_at);

-- Messages or readings that failed profile validation, kept for diagnosis.
CREATE TABLE ingest_reject (
    id           bigserial PRIMARY KEY,
    received_at  timestamptz NOT NULL DEFAULT now(),
    device_id    text,
    topic        text NOT NULL,
    reason       text NOT NULL,
    payload      jsonb
);
CREATE INDEX ingest_reject_received_idx ON ingest_reject(received_at DESC);

-- Raw copy of every device event (weighings and operator actions), as sent.
CREATE TABLE event_log (
    msg_id       text PRIMARY KEY,
    device_id    text NOT NULL REFERENCES device(id),
    ts           timestamptz NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now(),
    type         text NOT NULL,
    payload      jsonb NOT NULL
);
CREATE INDEX event_log_ts_idx ON event_log(ts DESC);

-- ---------------------------------------------------------------------------
-- Business (tea process)
-- ---------------------------------------------------------------------------

-- id is the value in the supplier's QR code. Unknown QR values seen at A are
-- registered automatically (auto_created) so a weighing is never dropped.
CREATE TABLE supplier (
    id            text PRIMARY KEY,
    name          text NOT NULL,
    contact       text,
    active        boolean NOT NULL DEFAULT true,
    auto_created  boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- One supplier visit at A; groups its sacks.
CREATE TABLE delivery (
    id           text PRIMARY KEY,
    supplier_id  text NOT NULL REFERENCES supplier(id),
    device_id    text REFERENCES device(id),
    started_at   timestamptz NOT NULL
);

-- One fill-and-empty of a trough area: opened by the first sack loaded at A,
-- closed when B reports the area unloaded (or the next load starts after
-- crates were taken).
CREATE TABLE area_cycle (
    id           bigserial PRIMARY KEY,
    trough_no    integer NOT NULL CHECK (trough_no BETWEEN 1 AND 11),
    area_no      integer NOT NULL CHECK (area_no BETWEEN 1 AND 8),
    loaded_at    timestamptz NOT NULL,
    unloaded_at  timestamptz
);
CREATE UNIQUE INDEX area_cycle_one_open_idx ON area_cycle(trough_no, area_no) WHERE unloaded_at IS NULL;

CREATE TABLE batch (
    id                  text PRIMARY KEY,          -- e.g. B20261105-03
    opened_at           timestamptz NOT NULL,
    bulk_stage          integer CHECK (bulk_stage IN (3, 4)),
    fermentation_start  timestamptz,
    fermentation_end    timestamptz,
    status              text NOT NULL DEFAULT 'withered'
                        CHECK (status IN ('withered', 'rolling', 'fermenting', 'drying', 'done')),
    notes               text
);

-- Columns shared by every weighing table:
--   msg_id       the device message it came from (null for manual entries)
--   corrects_id  the original row this one corrects (always the original,
--                never another correction); null for originals
--   voided       true when the correction cancels the original
--   reason, created_by   who corrected it and why

-- N: one sack at A. net_kg = gross - tare - deductions.
CREATE TABLE sack_weighing (
    id                   bigserial PRIMARY KEY,
    msg_id               text UNIQUE,
    ts                   timestamptz NOT NULL,
    device_id            text REFERENCES device(id),
    delivery_id          text REFERENCES delivery(id),
    supplier_id          text NOT NULL REFERENCES supplier(id),
    sack_seq             integer,
    gross_kg             numeric(8,2) NOT NULL,
    sack_tare_kg         numeric(8,2) NOT NULL DEFAULT 0,
    wet_deduction_kg     numeric(8,2) NOT NULL DEFAULT 0,
    coarse_deduction_kg  numeric(8,2) NOT NULL DEFAULT 0,
    net_kg               numeric(8,2) NOT NULL,
    trough_no            integer NOT NULL CHECK (trough_no BETWEEN 1 AND 11),
    area_no              integer NOT NULL CHECK (area_no BETWEEN 1 AND 8),
    cycle_id             bigint NOT NULL REFERENCES area_cycle(id),
    maturity             text,
    photos               jsonb NOT NULL DEFAULT '[]',
    operator_id          text,
    corrects_id          bigint REFERENCES sack_weighing(id),
    voided               boolean NOT NULL DEFAULT false,
    reason               text,
    created_by           text,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sack_weighing_cycle_idx ON sack_weighing(cycle_id);
CREATE INDEX sack_weighing_supplier_idx ON sack_weighing(supplier_id, ts);
CREATE INDEX sack_weighing_corrects_idx ON sack_weighing(corrects_id);

-- Bw: one crate at B. Over-limit crates are not recorded here (the operator
-- lightens and re-weighs); they stay in event_log and raise an alarm.
CREATE TABLE crate_weighing (
    id             bigserial PRIMARY KEY,
    msg_id         text UNIQUE,
    ts             timestamptz NOT NULL,
    device_id      text REFERENCES device(id),
    cycle_id       bigint NOT NULL REFERENCES area_cycle(id),
    trough_no      integer NOT NULL CHECK (trough_no BETWEEN 1 AND 11),
    area_no        integer NOT NULL CHECK (area_no BETWEEN 1 AND 8),
    crate_id       text,
    gross_kg       numeric(8,2),
    tare_kg        numeric(8,2),
    net_kg         numeric(8,2) NOT NULL,
    max_limit_kg   numeric(8,2),
    batch_id       text REFERENCES batch(id),
    operator_id    text,
    corrects_id    bigint REFERENCES crate_weighing(id),
    voided         boolean NOT NULL DEFAULT false,
    reason         text,
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX crate_weighing_cycle_idx ON crate_weighing(cycle_id);
CREATE INDEX crate_weighing_batch_idx ON crate_weighing(batch_id);
CREATE INDEX crate_weighing_corrects_idx ON crate_weighing(corrects_id);

-- W1..W4: leaf that continues after each sieving. Several loads per stage
-- add up.
CREATE TABLE stage_weighing (
    id           bigserial PRIMARY KEY,
    msg_id       text UNIQUE,
    ts           timestamptz NOT NULL,
    device_id    text REFERENCES device(id),
    batch_id     text NOT NULL REFERENCES batch(id),
    stage        integer NOT NULL CHECK (stage BETWEEN 1 AND 4),
    net_kg       numeric(8,2) NOT NULL,
    bulk         boolean NOT NULL DEFAULT false,
    operator_id  text,
    corrects_id  bigint REFERENCES stage_weighing(id),
    voided       boolean NOT NULL DEFAULT false,
    reason       text,
    created_by   text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stage_weighing_batch_idx ON stage_weighing(batch_id, stage);
CREATE INDEX stage_weighing_corrects_idx ON stage_weighing(corrects_id);

-- D: made tea out of the drier.
CREATE TABLE drier_output (
    id             bigserial PRIMARY KEY,
    msg_id         text UNIQUE,
    ts             timestamptz NOT NULL,
    device_id      text REFERENCES device(id),
    batch_id       text REFERENCES batch(id),
    batch_assigned text NOT NULL DEFAULT 'device'
                   CHECK (batch_assigned IN ('device', 'time_window', 'operator')),
    net_kg         numeric(8,2) NOT NULL,
    moisture_pct   numeric(5,2),
    max_limit_kg   numeric(8,2),
    operator_id    text,
    corrects_id    bigint REFERENCES drier_output(id),
    voided         boolean NOT NULL DEFAULT false,
    reason         text,
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX drier_output_batch_idx ON drier_output(batch_id);
CREATE INDEX drier_output_corrects_idx ON drier_output(corrects_id);

-- ---------------------------------------------------------------------------
-- Append-only guard for business records
-- ---------------------------------------------------------------------------

CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: insert a correction referencing the original instead', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END $$;

-- A correction must point at an original, not at another correction, so the
-- latest correction of an original is easy to find.
CREATE FUNCTION check_correction() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_corrects bigint;
BEGIN
    IF NEW.corrects_id IS NOT NULL THEN
        EXECUTE format('SELECT corrects_id FROM %I WHERE id = $1', TG_TABLE_NAME)
            INTO parent_corrects USING NEW.corrects_id;
        IF parent_corrects IS NOT NULL THEN
            RAISE EXCEPTION 'corrects_id must reference the original record (%), not a correction', parent_corrects;
        END IF;
    END IF;
    RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['sack_weighing', 'crate_weighing', 'stage_weighing', 'drier_output'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_change()', t || '_append_only', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION check_correction()', t || '_correction', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['event_log', 'audit_log'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_change()', t || '_append_only', t);
    END LOOP;
END $$;

-- Effective weighings: for each original, its latest correction (or itself),
-- with voided ones removed. Reports read these views, never the raw tables.
CREATE VIEW sack_weighing_effective AS
SELECT * FROM (
    SELECT DISTINCT ON (coalesce(corrects_id, id)) coalesce(corrects_id, id) AS original_id, *
    FROM sack_weighing ORDER BY coalesce(corrects_id, id), id DESC
) s WHERE NOT voided;

CREATE VIEW crate_weighing_effective AS
SELECT * FROM (
    SELECT DISTINCT ON (coalesce(corrects_id, id)) coalesce(corrects_id, id) AS original_id, *
    FROM crate_weighing ORDER BY coalesce(corrects_id, id), id DESC
) s WHERE NOT voided;

CREATE VIEW stage_weighing_effective AS
SELECT * FROM (
    SELECT DISTINCT ON (coalesce(corrects_id, id)) coalesce(corrects_id, id) AS original_id, *
    FROM stage_weighing ORDER BY coalesce(corrects_id, id), id DESC
) s WHERE NOT voided;

CREATE VIEW drier_output_effective AS
SELECT * FROM (
    SELECT DISTINCT ON (coalesce(corrects_id, id)) coalesce(corrects_id, id) AS original_id, *
    FROM drier_output ORDER BY coalesce(corrects_id, id), id DESC
) s WHERE NOT voided;
