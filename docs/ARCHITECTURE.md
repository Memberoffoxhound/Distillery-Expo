# Distillery Expo — Architecture (M1)

## Vision

A **tinygrad distill control room**: pull mici routes (comma Connect + local/SSH), run Cinque/supercombo as teacher on a **7090 XT**, distill into a lighter **stock-modelV2-I/O** student for mici/QCOM, then export → eval → **gated** flash.

Expo GUI is the primary surface. `dex` is the engine CLI. The API is the shared runtime.

## Design locks (v1)

1. **No Chestnut** — teacher path is Cinque/supercombo on 7090 XT only.
2. **Student stock modelV2 I/O compatible** — tensors, cams, and controls match stock modelV2 contracts so the student drops onto mici/QCOM without I/O surgery.
3. **Flash always gated** — never auto-flash; UI + API require explicit confirm. M1 does not weaken this.
4. **Expo GUI is primary; dex is engine** — operators live in the web mission control; CLI drives headless / scripting.

## System diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Expo Web (Vite/React)                    │
│  Job rail · Ingest · Cams · Shard · Teacher · Train ·       │
│  Thinking · Logs · Eval · Flash (gated)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + WebSocket /ws/jobs/{id}
┌──────────────────────────▼──────────────────────────────────┐
│                     FastAPI (apps/api)                       │
│  GET /routes · POST /jobs/ingest · POST /jobs/demo · WS      │
└──────────────────────────┬──────────────────────────────────┘
                           │ typed events (same bus)
┌──────────────────────────▼──────────────────────────────────┐
│              packages/events  (decision|metric|…)            │
└─────────────────────────────────────────────────────────────┘
         │         │         │         │         │
    ingest★   shards    teacher   student   export/eval/deploy
   (M1 real)  (M2 real)  (stub)    (stub)       (stubs)
```

## M1 — mici ingest thin slice

**Goal:** A simple user can list routes and start an ingest job; the bus emits ingest stage progress and ≥1 `sample` per cam (road / wide / driver) with metadata the Expo cams pane can bind — without CLI archaeology.

### Source resolution

```
prefer=auto:  Connect (COMMA_JWT) → SSH (MICI_SSH_HOST) → fixture
```

- **Connect** (`packages/ingest/.../sources/connect.py`) — primary structure; maps Connect JSON into `RouteInfo` / `SegmentInfo`.
- **SSH** — lists `/data/media/0/realdata` on mici; maps hevc filenames → road/wide/driver.
- **Fixture** — offline / CI; `packages/ingest/fixtures/sample_route.json` is Connect-shaped and labeled `meta.fixture` / `meta.label=fixture`. Samples keep `placeholder=true`.

Routes picker: `GET /routes?source=public|connect|ssh` (see `docs/routes-picker-contract.json`). Also `GET /routes?source=connect&scope=public` for shared/public Connect browse (JWT → `/v1/me/devices`; never demo dongle). Dongle resolved from `DISTILLERY_DONGLE_ID`, `.cache/dongle_id` (POST `/dongle` Save or ADB/SSH auto-hydrate), or optional YAML — **empty until set** (no demo default). GET `/dongle` may include `suggested_dongle_id` / `discovered_from` from `/data/params/d/DongleId`. Fixture routes may still use labeled sample id `3e2de7ed673817c2`. See `docs/dongle-id-contract.json`.

### API (simple-user path)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/dongle` | Saved dongle (or null) + cam list + cred/ADB availability |
| `POST` | `/dongle` | Body `{dongle_id, persist?}` → env + `.cache/dongle_id` |
| `GET` | `/routes?source=auto` | List routes |
| `GET` | `/routes/{route_id}` | Route detail + segments/cams |
| `POST` | `/jobs/ingest` | Body `{route_id?, source?}` → ingest-only job |
| `WS` | `/ws/jobs/{id}` | **Same** job event channel as demo (no parallel bus) |

Flash confirm endpoints unchanged and unused by ingest-only jobs.

### Event payload shapes (Expo binding)

All events are `DistilleryEvent`:

```json
{
  "id": "uuid",
  "ts": "ISO-8601",
  "job_id": "uuid",
  "kind": "sample|stage|progress|decision|metric|log|warning",
  "stage": "ingest",
  "payload": { }
}
```

**Stage**

```json
{ "name": "ingest", "status": "running|done|failed", "detail": "…" }
```

**Progress**

```json
{ "fraction": 0.45, "detail": "cam:road" }
```

**Sample** (cams pane binds `payload.cam` / `label` / `meta`)

```json
{
  "cam": "road",
  "label": "road · 2024-06-15--14-30-00",
  "placeholder": true,
  "uri": "/data/media/0/realdata/…/fcamera.hevc",
  "meta": {
    "fixture": true,
    "source": "fixture",
    "route_id": "3e2de7ed673817c2|2024-06-15--14-30-00",
    "dongle_id": "3e2de7ed673817c2",
    "segment_id": "…/0",
    "fps": 20,
    "width": 1164,
    "height": 874,
    "codec": "hevc",
    "filename": "fcamera.hevc",
    "label": "fixture"
  }
}
```

### CLI helpers (secondary)

```
dex routes [--source auto|connect|ssh|fixture] [--local]
dex ingest [--route ID] [--source …] [--local]
```

Expo path works with HTTP/WS alone; CLI is optional.

## Engine + Expo control room + event bus

### Event bus

All pipeline stages emit **JSON-serializable** typed events (`packages/events`):

| Kind | Purpose |
|------|---------|
| `decision` | Thinking traces — why a stage chose X |
| `metric` | Loss, fps, scores, gauges |
| `warning` | Soft failures / retries |
| `sample` | Cam frames / tensor placeholders |
| `log` | Human-readable stage logs |
| `progress` | 0–1 stage progress |
| `stage` | Stage enter/exit / status |

Events are the single contract between API, CLI, and GUI.

### Stages (pipeline)

```
ingest → shard → teach → train → export → eval → flash
```

| Stage | Role (v1 intent) |
|-------|------------------|
| **ingest** | **M1:** Pull routes from mici (dongle `3e2de7ed673817c2`) via Connect/SSH/fixture; expose road/wide/driver cams |
| **shard** | Pack frames/segments into training shards |
| **teach** | Cinque/supercombo teacher inference on 7090 XT (no Chestnut) |
| **train** | Distill into stock-modelV2-I/O student (tinygrad) |
| **export** | Export student artifact for QCOM/mici |
| **eval** | Scorecard vs teacher / offline metrics |
| **flash** | Gated deploy to device — confirm required |

M0 demo background task still available (`POST /jobs/demo`). M1 adds ingest-only jobs.

## Packages

- `packages/events` — shared schema (API + workers)
- `packages/ingest` — **M1 real package** (Connect / SSH / fixture → bus)
- `packages/shards` — **M2 real package** (pack → bus)
- `packages/teacher|student|export|eval|deploy` — stub READMEs defining v1 scope

## Apps

- **api** — FastAPI job store + WebSocket fanout + routes/ingest
- **cli** — `dex routes`, `dex ingest`, `dex demo`, `dex stages`
- **web** — dark multi-pane mission control; WebSocket-connected Thinking timeline

## Config

`configs/default.yaml` — dongle_id, ingest.force_fixture, teacher/student placeholders, flash_gated, ports.

## Non-goals (M1)

- Teacher / train / export / eval / flash implementation
- Weakening flash gating
- Real AMD ROCm / tinygrad training loops
- Chestnut or any non-Cinque teacher path

## M2 — shards pack + one-command launcher

**Goal:** A simple user runs `./scripts/dev-up`, lands in Expo, pulls a mici route, then packs shards — with truthful `stage=shard` progress on the same WS bus. No CLI required for the Expo path.

### Shard pack

- Package: `packages/shards` (`distillery_shards`)
- Packs ingested route segments into training shard descriptors (frame windows, label + teacher soft-target placeholders)
- Fixture/offline path when no Connect/SSH/ingest artifacts — labeled `meta.fixture` (mirrors ingest)
- API: `POST /jobs/shard` `{ route_id?, source? }` → events on existing `/ws/jobs/{id}`
- CLI (secondary): `dex shards` / `dex pack`

### Event shapes (Expo / Jony)

Stage / progress / metric / decision / log same as M1. Sample meta for shard binding:

| Field | Meaning |
|-------|---------|
| `shard_id` | e.g. `shard_000` |
| `route_id` | parent route |
| `frame_count` | frames in window |
| `size_bytes` | estimated packed size |
| `status` | `ready` / … |
| `fixture` | `true` when offline fixture |

Metric `shards_written` matches the M0 demo so the Shard pane binds without UI changes.

### One-command launcher

`scripts/dev-up` — POSIX `sh`, Fedora-first, portable (`python3` / `node` / `npm` only). Creates `.venv`, installs editable Python + web deps if missing, starts API+web, prints Expo URL + next step (Pull mici route → Pack shards). macOS follow-on: same script; brew notes in comments only.

### Non-goals (M2)

- Teacher / train / export / eval / flash implementation
- Weakening flash gating
- Chestnut / non-Cinque teacher path


## Ship — teach → train → export → eval → gated flash

API wires Graig packages:

```python
from distillery_teacher import run_teach_pipeline
from distillery_student import run_train_pipeline
from distillery_export import run_export_pipeline
from distillery_eval import run_eval_pipeline
```

`apps/api/ml_adapters.py` resolves those entrypoints; temporary fixture fallbacks stay in the API layer only and emit `live=false`.

**Flash gate (Phil/Bruce):** `job.eval_passed` defaults `False`. Confirm requires `eval_passed is True` **and** explicit confirm. Never auto-write to mici. Eval always emits real scorecard numbers; fixture/stub is not licensed to unlock flash.
