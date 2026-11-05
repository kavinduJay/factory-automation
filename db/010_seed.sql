-- Seed data for site TF01: asset tree, device profiles, the 25 devices and
-- 78 measuring sensors from docs/DEVICES.md, plus the non-measuring
-- peripherals (thermocouple module, stack lights, QR scanners, tablet,
-- printer) and the default rules.
--
-- Alarm thresholds are proposed starting values; tune them from the
-- dashboard (rules) or by editing the profiles.

-- ---------------------------------------------------------------------------
-- Asset tree: site -> floor -> zone
-- ---------------------------------------------------------------------------

INSERT INTO asset (id, parent_id, type, code, name) VALUES
    ('TF01',   NULL,   'site',  'TF01', 'Tea factory TF01'),
    ('TF01-G', 'TF01', 'floor', 'G',    'Ground / outdoor'),
    ('TF01-U', 'TF01', 'floor', 'U',    'Upper floor'),
    ('TF01-L', 'TF01', 'floor', 'L',    'Lower floor');

INSERT INTO asset (id, parent_id, type, code, name, meta) VALUES
    ('TF01-G-ENV', 'TF01-G', 'zone', 'ENV', 'Ambient (outdoor)', '{}'),
    ('TF01-U-RCV', 'TF01-U', 'zone', 'RCV', 'Receiving (A)', '{"weigh_point": "A"}'),
    ('TF01-U-WWB', 'TF01-U', 'zone', 'WWB', 'Withered weigh (B)', '{"weigh_point": "B"}'),
    ('TF01-L-RC1', 'TF01-L', 'zone', 'RC1', 'Charging roller 1', '{"rolling_stage": 1}'),
    ('TF01-L-RC2', 'TF01-L', 'zone', 'RC2', 'Charging roller 2', '{"rolling_stage": 1}'),
    ('TF01-L-RC3', 'TF01-L', 'zone', 'RC3', 'Charging roller 3', '{"rolling_stage": 1}'),
    ('TF01-L-R21', 'TF01-L', 'zone', 'R21', 'Second roller 1', '{"rolling_stage": 2}'),
    ('TF01-L-R22', 'TF01-L', 'zone', 'R22', 'Second roller 2', '{"rolling_stage": 2}'),
    ('TF01-L-R23', 'TF01-L', 'zone', 'R23', 'Second roller 3', '{"rolling_stage": 2}'),
    ('TF01-L-R31', 'TF01-L', 'zone', 'R31', 'Third roller 1', '{"rolling_stage": 3}'),
    ('TF01-L-R32', 'TF01-L', 'zone', 'R32', 'Third roller 2', '{"rolling_stage": 3}'),
    ('TF01-L-R41', 'TF01-L', 'zone', 'R41', 'Fourth roller', '{"rolling_stage": 4}'),
    ('TF01-L-RW1', 'TF01-L', 'zone', 'RW1', 'Rolling weigh W1', '{"weigh_point": "W1", "stage": 1}'),
    ('TF01-L-RW2', 'TF01-L', 'zone', 'RW2', 'Rolling weigh W2', '{"weigh_point": "W2", "stage": 2}'),
    ('TF01-L-RW3', 'TF01-L', 'zone', 'RW3', 'Rolling weigh W3', '{"weigh_point": "W3", "stage": 3}'),
    ('TF01-L-RW4', 'TF01-L', 'zone', 'RW4', 'Rolling weigh W4', '{"weigh_point": "W4", "stage": 4}'),
    ('TF01-L-ROL', 'TF01-L', 'zone', 'ROL', 'Rolling area', '{}'),
    ('TF01-L-FER', 'TF01-L', 'zone', 'FER', 'Fermentation', '{}'),
    ('TF01-L-DRY', 'TF01-L', 'zone', 'DRY', 'Drier', '{}'),
    ('TF01-L-DRO', 'TF01-L', 'zone', 'DRO', 'Drier output (D)', '{"weigh_point": "D"}');

INSERT INTO asset (id, parent_id, type, code, name, meta)
SELECT format('TF01-U-TR%s', lpad(n::text, 2, '0')), 'TF01-U', 'zone',
       format('TR%s', lpad(n::text, 2, '0')), format('Trough %s', n),
       jsonb_build_object('trough_no', n, 'areas', 8)
FROM generate_series(1, 11) AS n;

-- ---------------------------------------------------------------------------
-- Device profiles
-- ---------------------------------------------------------------------------

INSERT INTO device_profile (id, name, description, device_kind, telemetry_schema, event_schema, default_settings, alarm_rules, offline_after_s) VALUES
('trough-node', 'Trough zone node',
 'Withering trough: 3 temp/humidity sensors (plenum, near end, far end) and the fan current sensor.',
 'zone_node',
 '{"THS": {"t_c":    {"unit": "°C", "min": -10, "max": 80},
           "rh_pct": {"unit": "%",  "min": 0,   "max": 100}},
   "CTS": {"amp":    {"unit": "A",  "min": 0,   "max": 100},
           "run":    {"unit": "",   "type": "bool"}}}',
 '{}',
 '{"poll_s": 10}',
 '[{"type": "trough_air_hot", "severity": "major", "message": "Trough air above 35 °C",
    "sensor_kind": "THS", "key": "t_c", "op": ">", "value": 35, "for_s": 300, "hysteresis": 1},
   {"type": "fan_stopped", "severity": "warning", "message": "Trough fan not running",
    "sensor_kind": "CTS", "key": "amp", "op": "<", "value": 1, "for_s": 120, "hysteresis": 0.5},
   {"type": "fan_overcurrent", "severity": "major", "message": "Trough fan current high",
    "sensor_kind": "CTS", "key": "amp", "op": ">", "value": 14, "for_s": 30, "hysteresis": 1}]',
 60),

('rolling-node', 'Rolling zone node',
 'Three rollers: one temp/humidity sensor and one motor current sensor per roller.',
 'zone_node',
 '{"THS": {"t_c":    {"unit": "°C", "min": -10, "max": 80},
           "rh_pct": {"unit": "%",  "min": 0,   "max": 100}},
   "CTS": {"amp":    {"unit": "A",  "min": 0,   "max": 100},
           "run":    {"unit": "",   "type": "bool"}}}',
 '{}',
 '{"poll_s": 10}',
 '[{"type": "roller_hot", "severity": "warning", "message": "Leaf at roller above 38 °C",
    "sensor_kind": "THS", "key": "t_c", "op": ">", "value": 38, "for_s": 300, "hysteresis": 1},
   {"type": "roller_overcurrent", "severity": "major", "message": "Roller motor current high",
    "sensor_kind": "CTS", "key": "amp", "op": ">", "value": 30, "for_s": 30, "hysteresis": 2}]',
 60),

('fermentation-node', 'Fermentation zone node',
 'Room temperature and humidity (high-humidity probes) and leaf surface IR sensors.',
 'zone_node',
 '{"THH": {"t_c":    {"unit": "°C", "min": -10, "max": 80},
           "rh_pct": {"unit": "%",  "min": 0,   "max": 100}},
   "IRS": {"t_c":    {"unit": "°C", "min": -20, "max": 150}}}',
 '{}',
 '{"poll_s": 10}',
 '[{"type": "ferm_humidity_low", "severity": "warning", "message": "Fermentation humidity below 85 %",
    "sensor_kind": "THH", "key": "rh_pct", "op": "<", "value": 85, "for_s": 600, "hysteresis": 2},
   {"type": "ferm_room_hot", "severity": "warning", "message": "Fermentation room above 30 °C",
    "sensor_kind": "THH", "key": "t_c", "op": ">", "value": 30, "for_s": 600, "hysteresis": 0.5}]',
 60),

('drier-node', 'Drier zone node',
 'Thermocouple module with inlet, outlet and exhaust K-type probes, and the drier motor current.',
 'zone_node',
 '{"TCK": {"t_c": {"unit": "°C", "min": -20, "max": 600}},
   "CTS": {"amp": {"unit": "A",  "min": 0,   "max": 100},
           "run": {"unit": "",   "type": "bool"}}}',
 '{}',
 '{"poll_s": 10}',
 '[{"type": "drier_inlet_high", "severity": "major", "message": "Drier inlet above 125 °C",
    "sensor_kind": "TCK", "position": "inlet", "key": "t_c", "op": ">", "value": 125, "for_s": 120, "hysteresis": 3},
   {"type": "drier_inlet_low", "severity": "warning", "message": "Drier inlet below 85 °C",
    "sensor_kind": "TCK", "position": "inlet", "key": "t_c", "op": "<", "value": 85, "for_s": 300, "hysteresis": 3},
   {"type": "drier_motor_stopped", "severity": "major", "message": "Drier motor not running",
    "sensor_kind": "CTS", "key": "amp", "op": "<", "value": 1, "for_s": 60, "hysteresis": 0.5}]',
 60),

('ambient-node', 'Ambient node',
 'Outdoor temperature and humidity in a radiation shield.',
 'zone_node',
 '{"THS": {"t_c":    {"unit": "°C", "min": -10, "max": 80},
           "rh_pct": {"unit": "%",  "min": 0,   "max": 100}}}',
 '{}',
 '{"poll_s": 30}',
 '[]',
 120),

('scale-bridge-a', 'Scale bridge A (receiving)',
 'Avery scale at intake with tablet, QR scanner and printer. One event per sack.',
 'scale_bridge',
 '{}',
 '{"sack_weighed": {"required": ["supplier_id", "gross_kg", "net_kg", "trough_no", "area_no"],
                    "numeric":  ["gross_kg", "sack_tare_kg", "wet_deduction_kg", "coarse_deduction_kg", "net_kg"]}}',
 '{"min_weight_kg": 0.5, "stability_band_kg": 0.05, "default_sack_tare_kg": 1.0}',
 '[]',
 180),

('scale-bridge-b', 'Scale bridge B (withered weigh)',
 'Avery scale above the chutes with QR scanner and stack light. One event per crate.',
 'scale_bridge',
 '{}',
 '{"crate_weighed": {"required": ["trough_no", "area_no", "net_kg"],
                     "numeric":  ["gross_kg", "tare_kg", "net_kg", "max_limit_kg"]},
   "area_unloaded": {"required": ["trough_no", "area_no"], "numeric": []}}',
 '{"max_limit_kg": 25.0, "amber_pct": 5, "min_weight_kg": 0.5, "stability_band_kg": 0.05}',
 '[]',
 180),

('scale-bridge-w', 'Scale bridge W (rolling)',
 'Avery scale after a sifter. Stage fixed per unit in device config; W3/W4 can mark bulk.',
 'scale_bridge',
 '{}',
 '{"stage_weighed": {"required": ["batch_id", "net_kg"], "numeric": ["net_kg"]}}',
 '{"min_weight_kg": 0.5, "stability_band_kg": 0.05}',
 '[]',
 180),

('scale-bridge-d', 'Scale bridge D (drier output)',
 'Avery scale for made tea, with stack light. Moisture entered by hand.',
 'scale_bridge',
 '{}',
 '{"drier_output": {"required": ["net_kg"], "numeric": ["net_kg", "moisture_pct", "max_limit_kg"]}}',
 '{"max_limit_kg": 30.0, "amber_pct": 5, "min_weight_kg": 0.5, "stability_band_kg": 0.05}',
 '[]',
 180);

-- ---------------------------------------------------------------------------
-- Devices (7 scale bridges + 18 zone nodes = 25)
-- ---------------------------------------------------------------------------

INSERT INTO device (id, profile_id, asset_id, name, point, config) VALUES
    ('TF01-U-RCV-SCB01', 'scale-bridge-a', 'TF01-U-RCV', 'Scale bridge A',  'A',  '{}'),
    ('TF01-U-WWB-SCB01', 'scale-bridge-b', 'TF01-U-WWB', 'Scale bridge B',  'B',  '{}'),
    ('TF01-L-RW1-SCB01', 'scale-bridge-w', 'TF01-L-RW1', 'Scale bridge W1', 'W1', '{"stage": 1}'),
    ('TF01-L-RW2-SCB01', 'scale-bridge-w', 'TF01-L-RW2', 'Scale bridge W2', 'W2', '{"stage": 2}'),
    ('TF01-L-RW3-SCB01', 'scale-bridge-w', 'TF01-L-RW3', 'Scale bridge W3', 'W3', '{"stage": 3, "can_mark_bulk": true}'),
    ('TF01-L-RW4-SCB01', 'scale-bridge-w', 'TF01-L-RW4', 'Scale bridge W4', 'W4', '{"stage": 4, "can_mark_bulk": true}'),
    ('TF01-L-DRO-SCB01', 'scale-bridge-d', 'TF01-L-DRO', 'Scale bridge D',  'D',  '{}');

INSERT INTO device (id, profile_id, asset_id, name)
SELECT format('TF01-U-TR%s-NOD01', lpad(n::text, 2, '0')), 'trough-node',
       format('TF01-U-TR%s', lpad(n::text, 2, '0')), format('Trough %s node', n)
FROM generate_series(1, 11) AS n;

INSERT INTO device (id, profile_id, asset_id, name) VALUES
    ('TF01-L-ROL-NOD01', 'rolling-node',      'TF01-L-ROL', 'Rolling node 1 (RC1-RC3)'),
    ('TF01-L-ROL-NOD02', 'rolling-node',      'TF01-L-ROL', 'Rolling node 2 (R21-R23)'),
    ('TF01-L-ROL-NOD03', 'rolling-node',      'TF01-L-ROL', 'Rolling node 3 (R31, R32, R41)'),
    ('TF01-L-FER-NOD01', 'fermentation-node', 'TF01-L-FER', 'Fermentation node 1'),
    ('TF01-L-FER-NOD02', 'fermentation-node', 'TF01-L-FER', 'Fermentation node 2'),
    ('TF01-L-DRY-NOD01', 'drier-node',        'TF01-L-DRY', 'Drier node'),
    ('TF01-G-ENV-NOD01', 'ambient-node',      'TF01-G-ENV', 'Ambient node');

-- ---------------------------------------------------------------------------
-- Sensors
-- ---------------------------------------------------------------------------

-- Troughs: 3 THS + 1 CTS each (33 THS, 11 CTS)
INSERT INTO sensor (id, device_id, asset_id, kind, name, position, modbus_addr)
SELECT format('TF01-U-TR%s-THS0%s', lpad(t::text, 2, '0'), p.n),
       format('TF01-U-TR%s-NOD01', lpad(t::text, 2, '0')),
       format('TF01-U-TR%s', lpad(t::text, 2, '0')),
       'THS', format('Trough %s %s', t, p.label), p.position, p.n
FROM generate_series(1, 11) AS t
CROSS JOIN (VALUES (1, 'plenum', 'plenum'),
                   (2, 'near_end', 'above leaf, near end'),
                   (3, 'far_end', 'above leaf, far end')) AS p(n, position, label);

INSERT INTO sensor (id, device_id, asset_id, kind, name, position, modbus_addr)
SELECT format('TF01-U-TR%s-CTS01', lpad(t::text, 2, '0')),
       format('TF01-U-TR%s-NOD01', lpad(t::text, 2, '0')),
       format('TF01-U-TR%s', lpad(t::text, 2, '0')),
       'CTS', format('Trough %s fan', t), 'fan', 21
FROM generate_series(1, 11) AS t;

-- Rollers: 1 THS + 1 CTS each (9 THS, 9 CTS), three per rolling node
INSERT INTO sensor (id, device_id, asset_id, kind, name, position, modbus_addr)
SELECT format('TF01-L-%s-%s01', r.zone, k.kind), r.node, format('TF01-L-%s', r.zone),
       k.kind, format('%s %s', r.label, k.label), k.position, k.base + r.slot
FROM (VALUES ('RC1', 'TF01-L-ROL-NOD01', 0, 'Charging roller 1'),
             ('RC2', 'TF01-L-ROL-NOD01', 1, 'Charging roller 2'),
             ('RC3', 'TF01-L-ROL-NOD01', 2, 'Charging roller 3'),
             ('R21', 'TF01-L-ROL-NOD02', 0, 'Second roller 1'),
             ('R22', 'TF01-L-ROL-NOD02', 1, 'Second roller 2'),
             ('R23', 'TF01-L-ROL-NOD02', 2, 'Second roller 3'),
             ('R31', 'TF01-L-ROL-NOD03', 0, 'Third roller 1'),
             ('R32', 'TF01-L-ROL-NOD03', 1, 'Third roller 2'),
             ('R41', 'TF01-L-ROL-NOD03', 2, 'Fourth roller')) AS r(zone, node, slot, label)
CROSS JOIN (VALUES ('THS', 1,  'leaf', 'temp/humidity'),
                   ('CTS', 21, 'motor', 'motor')) AS k(kind, base, position, label);

-- Fermentation: 3 THH + 8 IRS
INSERT INTO sensor (id, device_id, asset_id, kind, name, position, modbus_addr)
SELECT format('TF01-L-FER-THH0%s', n), 'TF01-L-FER-NOD01', 'TF01-L-FER',
       'THH', format('Fermentation room probe %s', n), 'room', n
FROM generate_series(1, 3) AS n;

INSERT INTO sensor (id, device_id, asset_id, kind, name, position, modbus_addr)
SELECT format('TF01-L-FER-IRS0%s', n),
       CASE WHEN n <= 4 THEN 'TF01-L-FER-NOD01' ELSE 'TF01-L-FER-NOD02' END,
       'TF01-L-FER', 'IRS', format('Leaf surface spot %s', n), 'surface', 30 + n
FROM generate_series(1, 8) AS n;

-- Drier: TCM module (not measuring) with 3 TCK channels, motor CTS
INSERT INTO sensor (id, device_id, asset_id, kind, name, position, measuring, modbus_addr, channel) VALUES
    ('TF01-L-DRY-TCM01', 'TF01-L-DRY-NOD01', 'TF01-L-DRY', 'TCM', 'Thermocouple module', NULL,      false, 41, NULL),
    ('TF01-L-DRY-TCK01', 'TF01-L-DRY-NOD01', 'TF01-L-DRY', 'TCK', 'Drier inlet',         'inlet',   true,  41, 1),
    ('TF01-L-DRY-TCK02', 'TF01-L-DRY-NOD01', 'TF01-L-DRY', 'TCK', 'Drier outlet',        'outlet',  true,  41, 2),
    ('TF01-L-DRY-TCK03', 'TF01-L-DRY-NOD01', 'TF01-L-DRY', 'TCK', 'Drier exhaust',       'exhaust', true,  41, 3),
    ('TF01-L-DRY-CTS01', 'TF01-L-DRY-NOD01', 'TF01-L-DRY', 'CTS', 'Drier motor',         'motor',   true,  21, NULL);

-- Ambient: 1 THS
INSERT INTO sensor (id, device_id, asset_id, kind, name, position, modbus_addr) VALUES
    ('TF01-G-ENV-THS01', 'TF01-G-ENV-NOD01', 'TF01-G-ENV', 'THS', 'Outdoor', 'outdoor', 1);

-- Peripherals on the scale bridges (not measuring)
INSERT INTO sensor (id, device_id, asset_id, kind, name, measuring) VALUES
    ('TF01-U-RCV-TAB01', 'TF01-U-RCV-SCB01', 'TF01-U-RCV', 'TAB', 'Tablet at A',           false),
    ('TF01-U-RCV-QRS01', 'TF01-U-RCV-SCB01', 'TF01-U-RCV', 'QRS', 'QR scanner at A',       false),
    ('TF01-U-RCV-PRN01', 'TF01-U-RCV-SCB01', 'TF01-U-RCV', 'PRN', 'Receipt printer at A',  false),
    ('TF01-U-WWB-QRS01', 'TF01-U-WWB-SCB01', 'TF01-U-WWB', 'QRS', 'QR scanner at B',       false),
    ('TF01-U-WWB-STL01', 'TF01-U-WWB-SCB01', 'TF01-U-WWB', 'STL', 'Stack light at B',      false),
    ('TF01-L-DRO-STL01', 'TF01-L-DRO-SCB01', 'TF01-L-DRO', 'STL', 'Stack light at D',      false);

-- Shared attributes start as the profile defaults.
INSERT INTO attribute (entity_id, scope, key, value)
SELECT d.id, 'shared', s.key, s.value
FROM device d
JOIN device_profile p ON p.id = d.profile_id
CROSS JOIN LATERAL jsonb_each(p.default_settings) AS s(key, value);

-- ---------------------------------------------------------------------------
-- Rules (when-then, editable from the dashboard)
-- ---------------------------------------------------------------------------

INSERT INTO rule (name, scope_asset_id, condition, action) VALUES
    ('Fermentation surface above 30 °C for 5 min', 'TF01-L-FER',
     '{"sensor_kind": "IRS", "key": "t_c", "op": ">", "value": 30, "for_s": 300, "hysteresis": 0.5}',
     '{"alarm_type": "ferm_surface_high", "severity": "major", "message": "Leaf surface above 30 °C"}');

-- Sanity check against docs/DEVICES.md totals.
DO $$
DECLARE devices int; sensors int;
BEGIN
    SELECT count(*) INTO devices FROM device;
    SELECT count(*) INTO sensors FROM sensor WHERE measuring;
    IF devices <> 25 OR sensors <> 78 THEN
        RAISE EXCEPTION 'seed mismatch: % devices (want 25), % measuring sensors (want 78)', devices, sensors;
    END IF;
END $$;
