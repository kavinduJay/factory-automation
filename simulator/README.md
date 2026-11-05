# Simulator

Publishes realistic MQTT traffic for all 25 TF01 devices so the stack runs
without hardware. Dev only: `docker compose --profile sim up -d` in `deploy/`.

Each device is its own MQTT client and behaves like the firmware will:
retained `online`/`offline` status with a last-will, applies the retained
`attributes/desired` settings and reports them back in its `attributes`, ULID
`msg_id` and device `ts` on every message, and an outbox that buffers while
the device is off the air.

## What it does

- **Zone nodes** send telemetry every `poll_s` seconds (a device setting,
  10 s by default): trough air and fan current, roller leaf temperature and
  motor current, fermentation room and leaf surface, drier inlet, outlet and
  exhaust, outdoor ambient. Temperatures follow a day curve on the process
  clock.
- **Leaf flow** on a process clock running `SIM_SPEED` times real time
  (default 60, so an 8 h wither takes 8 min): sacks at A into trough areas,
  withering, crates at B per area into batches of about 400 kg, rolling
  stages W1-W3 (or W4) with the last marked bulk, fermentation, drying, and
  made tea at D at about 22 % out-turn. About 6 % of crates are overfilled;
  B rejects them and the operator re-weighs a lighter crate.
- **Faults** (`SIM_FAULTS=1`), one every 4-9 min: a hot fermentation spot,
  a hot trough, a tripped trough fan, a hot drier inlet (each long enough to
  trip its rule, then recovering), or a zone node off the air for 150 s that
  then flushes its buffer. Every 1-3 min a node re-sends an old message to
  exercise de-duplication.

At `SIM_SPEED` above 1, D always names the batch, because the backend assigns
unnamed made tea by a fermentation + drying window in real minutes.
