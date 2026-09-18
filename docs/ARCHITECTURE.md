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
   (M1 real)  (stub)    (stub)    (stub)       (stubs)
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

Dongle resolved from `configs/default.yaml` (`3e2de7ed673817c2`) or `DISTILLERY_DONGLE_ID`.

### API (simple-user path)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/dongle` | Resolved dongle + cam list + cred availability |
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
- `packages/shards|teacher|student|export|eval|deploy` — stub READMEs defining v1 scope

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
