# Process, weigh points and formulas

## Stages

The factory runs 24 hours. Leaf moves through these stages in order.

| Stage | Location | Duration | Weigh point | Measured |
|---|---|---|---|---|
| Receiving | Upper floor intake (unloaded at ground level, conveyor up) | During collection | **A** | Supplier QR, sack gross/net, optional deductions, trough (1–11) and area (1–8), optional maturity and photos |
| Withering | Upper floor, 11 troughs, 1 × 7.5 hp fan each | ~8 h | none | Temperature and humidity at 3 points per trough, fan current |
| Withered weigh | Upper floor, above 3 discharge chutes | Per crate | **B** | Crate net weight with trough and area; maximum-weight limit with buzzer and red light |
| Rolling and sieving | Lower floor: 3 charging, 3 second, 2 third, 1 fourth roller; conveyor between stages; sifters | Unknown | **W1–W4** | Weight that continues after each sieving; temperature/humidity and motor current per roller |
| Fermentation | Lower floor | ~2.5 h | none | Room temperature and humidity (3 probes), leaf surface temperature at 8 spots |
| Drying | Wood-fired drier at outer wall, stove chamber behind the wall | ~21 min | **D** | Inlet, outlet, exhaust temperatures; made-tea weight with limit |
| Sorting and grading | Lower floor | — | none | Out of Phase 1 scope |

## Traceability

- Each supplier has a unique QR code, scanned on every sack at A.
- Each trough is split logically into 8 areas. The trough and area are recorded at A and again at B.
- One area usually holds one supplier, but may occasionally hold several; one supplier may span several areas. The data model supports both.
- At B, areas are unloaded one after another, into crates, so each crate belongs to exactly one area.
- Supplier identity is exact up to B. From the charging rollers onward leaf is mixed into a **batch**; batch results are attributed back to suppliers by their share of the batch's withered weight.

## Formulas

| Quantity | Formula |
|---|---|
| Net received per sack, N | gross − sack tare − wet-leaf deduction − coarse-leaf deduction (each deduction optional, 0 when off) |
| Withered weight per area, Bw(a) | sum of crate net weights from area a |
| Supplier share of a mixed area | Bw(s,a) = Bw(a) × N(s,a) ÷ N(a), marked as estimated |
| Moisture loss per supplier, % | (ΣN − ΣBw) ÷ ΣN × 100 |
| Batch charge, Wz | sum of B crate weights assigned to the batch |
| Dhool after stage n | Ws1 = Wz − W1, Ws2 = W1 − W2, Ws3 = W2 − W3, Ws4 = W3 − W4. Dhool is never weighed, always calculated |
| Bulk | W3 or W4, as marked by the operator; goes to fermentation |
| Batch out-turn, % | made tea at D ÷ green leaf (N) in the batch × 100 |
| Supplier share of a batch | Bw(s, batch) ÷ Wz |
| Made tea attributed to supplier | D(batch) × share, marked as estimated |

Made tea at D is assigned to a batch by time window (fermentation start + fermentation time + drying time), with operator override.

## Worked example

| Step | Value |
|---|---|
| A | SUP-007, 3 sacks, 102 kg net into trough 3, area 5 |
| B | 3 crates from T3-A5, 56 kg → moisture loss (102 − 56) ÷ 102 = 45% |
| Batch | 800 kg green leaf, Wz = 400 kg; SUP-007 share = 56 ÷ 400 = 14% |
| Rolling | W1 300 (dhool 100), W2 220 (dhool 80), W3 160 (dhool 60), W3 marked bulk |
| D | 176 kg made tea → batch out-turn 176 ÷ 800 = 22%; SUP-007 ≈ 25 kg |

## Validation rules

- W1 ≤ Wz, and each Wn ≤ W(n−1). A larger value raises a warning.
- A crate over the B limit is not recorded; the operator lightens it and weighs again.
- A weight is accepted only when the scale reports stable.
