-- Report views, per the formulas in docs/PROCESS.md. They read the *_effective
-- views, so corrections apply and voided weighings drop out.
--
--   N(s,a)    net received at A from supplier s into area cycle a
--   Bw(a)     sum of crate nets at B from area cycle a
--   Bw(s,a) = Bw(a) x N(s,a) / N(a)        (estimated when a has >1 supplier)
--   Wz        sum of B crates assigned to the batch
--   Ws1 = Wz - W1, Ws2 = W1 - W2, Ws3 = W2 - W3, Ws4 = W3 - W4   (dhool)
--   out-turn  = made tea at D / green leaf (N) in the batch x 100
--   share     = Bw(s, batch) / Wz;   made tea (s) = D x share    (estimated)
--
-- Days are factory-local (Asia/Colombo).

-- One row per area cycle: what went in at A and what came out at B.
CREATE VIEW area_cycle_summary AS
SELECT ac.id AS cycle_id, ac.trough_no, ac.area_no, ac.loaded_at, ac.unloaded_at,
       coalesce(n.n_kg, 0)        AS n_kg,
       coalesce(n.suppliers, 0)   AS suppliers,
       coalesce(n.sacks, 0)       AS sacks,
       coalesce(b.bw_kg, 0)       AS bw_kg,
       coalesce(b.crates, 0)      AS crates,
       CASE WHEN ac.unloaded_at IS NOT NULL AND n.n_kg > 0 AND b.bw_kg > 0
            THEN round((n.n_kg - b.bw_kg) / n.n_kg * 100, 2) END AS moisture_loss_pct
FROM area_cycle ac
LEFT JOIN (SELECT cycle_id, sum(net_kg) AS n_kg, count(DISTINCT supplier_id) AS suppliers,
                  count(*) AS sacks
           FROM sack_weighing_effective GROUP BY cycle_id) n ON n.cycle_id = ac.id
LEFT JOIN (SELECT cycle_id, sum(net_kg) AS bw_kg, count(*) AS crates
           FROM crate_weighing_effective GROUP BY cycle_id) b ON b.cycle_id = ac.id;

-- Supplier share of each area cycle.
CREATE VIEW supplier_area AS
SELECT s.cycle_id, s.supplier_id, a.trough_no, a.area_no, a.loaded_at, a.unloaded_at,
       s.n_kg,
       round(s.n_kg / nullif(a.n_kg, 0), 6)              AS share_of_area,
       round(a.bw_kg * s.n_kg / nullif(a.n_kg, 0), 3)    AS bw_kg,
       a.suppliers > 1                                   AS estimated
FROM (SELECT cycle_id, supplier_id, sum(net_kg) AS n_kg
      FROM sack_weighing_effective GROUP BY cycle_id, supplier_id) s
JOIN area_cycle_summary a ON a.cycle_id = s.cycle_id;

-- Moisture loss per supplier and loading day; only areas fully unloaded at B.
CREATE VIEW moisture_loss_supplier AS
SELECT supplier_id,
       (loaded_at AT TIME ZONE 'Asia/Colombo')::date     AS day,
       sum(n_kg)                                         AS n_kg,
       round(sum(bw_kg), 3)                              AS bw_kg,
       round((sum(n_kg) - sum(bw_kg)) / nullif(sum(n_kg), 0) * 100, 2) AS moisture_loss_pct,
       bool_or(estimated)                                AS estimated,
       count(*)                                          AS areas
FROM supplier_area
WHERE unloaded_at IS NOT NULL AND bw_kg > 0
GROUP BY supplier_id, day;

-- Crate weight per (area cycle, batch): how each area's withered leaf was
-- split between batches.
CREATE VIEW cycle_batch AS
SELECT c.cycle_id, c.batch_id, sum(c.net_kg) AS bw_kg
FROM crate_weighing_effective c
WHERE c.batch_id IS NOT NULL
GROUP BY c.cycle_id, c.batch_id;

-- Supplier attribution per batch.
CREATE VIEW supplier_batch AS
SELECT cb.batch_id, sa.supplier_id,
       round(sum(cb.bw_kg * sa.share_of_area), 3)                             AS bw_kg,
       round(sum(sa.n_kg * cb.bw_kg / nullif(ac.bw_kg, 0)), 3)                AS green_leaf_kg,
       bool_or(sa.estimated)                                                  AS bw_estimated
FROM cycle_batch cb
JOIN supplier_area sa ON sa.cycle_id = cb.cycle_id
JOIN area_cycle_summary ac ON ac.cycle_id = cb.cycle_id
GROUP BY cb.batch_id, sa.supplier_id;

-- Batch figures: Wz, W1..W4, dhool, green leaf, made tea, out-turn, warnings.
CREATE VIEW batch_summary AS
WITH w AS (
    SELECT batch_id,
           sum(net_kg) FILTER (WHERE stage = 1) AS w1,
           sum(net_kg) FILTER (WHERE stage = 2) AS w2,
           sum(net_kg) FILTER (WHERE stage = 3) AS w3,
           sum(net_kg) FILTER (WHERE stage = 4) AS w4
    FROM stage_weighing_effective GROUP BY batch_id
), z AS (
    SELECT batch_id, sum(net_kg) AS wz, count(*) AS crates
    FROM crate_weighing_effective WHERE batch_id IS NOT NULL GROUP BY batch_id
), g AS (
    SELECT batch_id, sum(green_leaf_kg) AS green_leaf_kg, count(*) AS suppliers
    FROM supplier_batch GROUP BY batch_id
), d AS (
    SELECT batch_id, sum(net_kg) AS made_tea_kg, count(*) AS drier_loads
    FROM drier_output_effective WHERE batch_id IS NOT NULL GROUP BY batch_id
)
SELECT b.id AS batch_id, b.opened_at, b.status, b.bulk_stage,
       b.fermentation_start, b.fermentation_end, b.notes,
       coalesce(z.wz, 0) AS wz_kg, coalesce(z.crates, 0) AS crates,
       w.w1 AS w1_kg, w.w2 AS w2_kg, w.w3 AS w3_kg, w.w4 AS w4_kg,
       z.wz - w.w1 AS ws1_kg,
       w.w1 - w.w2 AS ws2_kg,
       w.w2 - w.w3 AS ws3_kg,
       w.w3 - w.w4 AS ws4_kg,
       CASE b.bulk_stage WHEN 3 THEN w.w3 WHEN 4 THEN w.w4 END AS bulk_kg,
       round(g.green_leaf_kg, 3) AS green_leaf_kg,
       coalesce(g.suppliers, 0) AS suppliers,
       coalesce(d.made_tea_kg, 0) AS made_tea_kg,
       coalesce(d.drier_loads, 0) AS drier_loads,
       round(d.made_tea_kg / nullif(g.green_leaf_kg, 0) * 100, 2) AS out_turn_pct,
       array_remove(ARRAY[
           CASE WHEN w.w1 > z.wz THEN 'W1 > Wz' END,
           CASE WHEN w.w2 > w.w1 THEN 'W2 > W1' END,
           CASE WHEN w.w3 > w.w2 THEN 'W3 > W2' END,
           CASE WHEN w.w4 > w.w3 THEN 'W4 > W3' END
       ], NULL) AS warnings
FROM batch b
LEFT JOIN z ON z.batch_id = b.id
LEFT JOIN w ON w.batch_id = b.id
LEFT JOIN g ON g.batch_id = b.id
LEFT JOIN d ON d.batch_id = b.id;

-- Supplier share of each batch and the made tea attributed to them.
CREATE VIEW supplier_batch_attribution AS
SELECT sb.batch_id, sb.supplier_id, sb.bw_kg, sb.green_leaf_kg,
       round(sb.bw_kg / nullif(bs.wz_kg, 0) * 100, 2)          AS share_pct,
       round(bs.made_tea_kg * sb.bw_kg / nullif(bs.wz_kg, 0), 3) AS made_tea_kg,
       sb.bw_estimated,
       true                                                    AS made_tea_estimated
FROM supplier_batch sb
JOIN batch_summary bs ON bs.batch_id = sb.batch_id;
