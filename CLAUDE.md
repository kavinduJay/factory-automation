# CLAUDE.md

Context for Claude Code sessions in this repo. Read this first, then the docs it points to.

## What this project is

IoT data collection for a real two-floor orthodox black tea factory in Sri Lanka (site code `TF01`), currently run fully by hand. Phase 1 collects weights and conditions. Phase 2 adds control (fans, fermentation humidity, drier). The owner is Kavindu (GitHub `kavinduJay`), a DevOps/cloud engineer.

## Rules

- **Commits:** author and committer must be `kavinduJay <kavindushashimal@gmail.com>`. Never use Claude as author or committer, and never add `Co-Authored-By: Claude` or any Claude attribution lines to commits or PRs.
- **Hosting:** self-hosted. Docker Compose on the owner's laptop first, then the same stack on a VPS. No AWS or other managed cloud IoT services.
- **Extensibility:** new sensor types must be addable as data (a device profile), not new code. Keep the topic contract and asset model stable.
- **Device and sensor IDs** follow the naming scheme in `docs/DEVICES.md`. Do not invent new formats.
- **Weights are business records** (they drive supplier payments). Never overwrite a weighing; corrections are new records referencing the original.
- Firmware targets ESP32 (ESP32-C3 for the proof of concept, ESP32-S3 for production bridges).

## Where things are

| Doc | What it holds |
|---|---|
| `docs/PROCESS.md` | Process stages, weigh points, formulas, worked example |
| `docs/ARCHITECTURE.md` | Docker stack, data model, MQTT topic contract, payloads, extensibility |
| `docs/DEVICES.md` | Every device and sensor ID, counts, Modbus addresses, wiring notes |
| `docs/wiring/WIRING.md`, `wiring-diagrams.pdf` | Wiring for every scale bridge and zone node variant: connection tables (Markdown) and diagrams (PDF) |
| `docs/ROADMAP.md` | Stages and task checklists; **start here to find the next task** |
| `dashboard/index.html` | Plant-mimic dashboard prototype (simulated data, single file) |
| `docs/floor-plans/upper-floor-plan.svg`, `lower-floor-plan.svg` | **Source of truth for the factory layout.** Positions of troughs, rollers, weigh points, chutes, fermentation, drier. The dashboard mimic must follow these |
| `docs/floor-plans/*-sketch.jpeg`, `reference-layout.png` | Original hand sketches and a reference layout from another factory |

External references (not in the repo):

- Phase 1 design v2 (Google Doc): https://docs.google.com/document/d/1KLxF2yoFhDue6SnKkZAusFmIuznqhwaiQOr9CH756Lc/edit
  (written before the move away from AWS; its AWS sections are superseded by `docs/ARCHITECTURE.md`)
- Plain-language guide: https://claude.ai/code/artifact/f6946dd1-5cec-46ff-b8f6-d05f32ccc828
- Wiring diagrams (editable source of `docs/wiring/`): https://claude.ai/code/artifact/714747cb-eab3-4c8a-b86b-068dc5d96788
- Published dashboard prototype: https://claude.ai/artifact/NJVgmLPS9VQH474M5jQQQm
- Floor-plan design canvas (editable): https://claude.ai/artifact/J8sbscfiDbDhuBfoNX9MH5. The SVGs in `docs/floor-plans/` are exported from it; re-export when it changes

## Open items

- Avery scale model(s) and RS-232 output format: not yet captured (Roadmap stage 2).
- Rolling stage durations, building and trough dimensions, daily leaf volume.
- Whether outlet and exhaust are separate probe points on this drier.
- Modbus addresses in `docs/DEVICES.md` are a proposed scheme, to be confirmed at install.
