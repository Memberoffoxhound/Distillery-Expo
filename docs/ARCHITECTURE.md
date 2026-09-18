# Distillery Expo — Architecture (M0)

## Vision

A **tinygrad distill control room**: pull mici routes (comma Connect + local/SSH), run Cinque/supercombo as teacher on a **7090 XT**, distill into a lighter **stock-modelV2-I/O** student for mici/QCOM, then export → eval → **gated** flash.

Expo GUI is the primary surface. `dex` is the engine CLI. The API is the shared runtime.

## Design locks (v1)

1. **No Chestnut** — teacher path is Cinque/supercombo on 7090 XT only.
2. **Student stock modelV2 I/O compatible** — tensors, cams, and controls match stock modelV2 contracts so the student drops onto mici/QCOM without I/O surgery.
3. **Flash always gated** — never auto-flash; UI + API require explicit confirm.
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
│  POST /jobs/demo · GET /jobs/{id} · background demo runner   │
└──────────────────────────┬──────────────────────────────────┘
                           │ typed events
┌──────────────────────────▼──────────────────────────────────┐
│              packages/events  (decision|metric|…)            │
└─────────────────────────────────────────────────────────────┘
         │         │         │         │         │
    ingest    shards    teacher   student   export/eval/deploy
    (stub)    (stub)    (stub)    (stub)       (stubs)
```

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
| **ingest** | Pull routes from mici (dongle `3e2de7ed673817c2`) via Connect/SSH; expose road/wide/driver cams |
| **shard** | Pack frames/segments into training shards |
| **teach** | Cinque/supercombo teacher inference on 7090 XT (no Chestnut) |
| **train** | Distill into stock-modelV2-I/O student (tinygrad) |
| **export** | Export student artifact for QCOM/mici |
| **eval** | Scorecard vs teacher / offline metrics |
| **flash** | Gated deploy to device — confirm required |

M0 runs a **demo background task** that emits realistic staged events (thinking/decision traces, metrics, logs, cam placeholders). No GPU/training code.

## Packages

- `packages/events` — shared schema (API + future workers)
- `packages/ingest|shards|teacher|student|export|eval|deploy` — stub READMEs defining v1 scope

## Apps

- **api** — FastAPI job store + WebSocket fanout
- **cli** — `dex demo`, `dex stages`
- **web** — dark multi-pane mission control; WebSocket-connected Thinking timeline

## Config

`configs/default.yaml` — dongle_id, teacher/student placeholders, flash_gated, ports.

## Non-goals (M0)

- Real AMD ROCm / tinygrad training loops
- Real comma Connect auth / route download
- Real QCOM flash tooling
- Chestnut or any non-Cinque teacher path
