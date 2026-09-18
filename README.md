# Distillery Expo

**One-stop tinygrad distill control room** for comma mici routes → Cinque/supercombo teacher (7090 XT) → lighter stock-modelV2-I/O student (mici/QCOM) → export / eval / gated flash.

> **M1** = real mici ingest thin slice (Connect + SSH + fixture) onto the typed event bus.
> **M2 UX** = Expo Shard pane (calm idle + truthful pack progress on `stage=shard` events). Flash stays gated.
> M0 demo pipeline still available. No teacher/train/flash work yet — flash stays gated.

## Hardware (v1)

| Role | Device |
|------|--------|
| Routes / cams | **mici** (comma Connect + local/SSH) |
| Teacher GPU | **AMD Radeon RX 7090 XT** |
| Student target | **mici / QCOM** (stock modelV2 I/O compatible) |

**Design locks:** No Chestnut in v1 · Student stays stock-modelV2 I/O · Flash always gated · Expo GUI is primary; `dex` is the engine CLI.

Dongle default: `3e2de7ed673817c2` (see `configs/default.yaml`).

## Quickstart — live demo UI

Two terminals from the repo root:

### Terminal 1 — API

```bash
cd /path/to/Distillery-Expo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2 — Web

```bash
cd /path/to/Distillery-Expo/apps/web
npm install
npm run dev
```

Open **http://localhost:5173**.

**M1 simple-user path:** Ingest pane lists mici routes (`GET /routes`) → **Ingest fixture** / **Pull mici route** (`POST /jobs/ingest`) → cams show road/wide/driver samples with route/dongle meta over `WS /ws/jobs/{id}`. Job rail shows elapsed time + weight as stages move. Flash confirm stays gated.

**M0:** **Run demo** still runs the full staged pipeline (flash gated).

### Ingest thin slice (M1)

```bash
# List routes (fixture when no Connect/SSH creds)
curl -s 'http://127.0.0.1:8000/routes?source=auto' | python -m json.tool

# Start ingest job — events on existing WS channel
curl -s -X POST http://127.0.0.1:8000/jobs/ingest   -H 'Content-Type: application/json'   -d '{"source":"fixture"}' | python -m json.tool
# → connect Expo / WS to /ws/jobs/{id}  (same channel as demo)
```

### CLI

```bash
source .venv/bin/activate
dex routes                 # list mici routes (API or --local)
dex ingest --source fixture
dex demo                   # full staged demo (M0)
dex stages
```

Env for live device paths:

| Var | Purpose |
|-----|---------|
| `COMMA_JWT` / `CONNECT_JWT` | comma Connect auth |
| `MICI_SSH_HOST` | mici SSH host |
| `MICI_SSH_KEY` | optional SSH key |
| `DISTILLERY_INGEST_FIXTURE=1` | force offline fixture |

## Layout

```
Distillery-Expo/
├── apps/
│   ├── api/          # FastAPI jobs + WebSocket event stream
│   ├── cli/          # dex entrypoint
│   └── web/          # Vite + React + TS mission-control GUI
├── packages/
│   ├── events/       # typed event schema (shared)
│   ├── ingest/       # M1 mici Connect/SSH/fixture → event bus
│   ├── shards|teacher|student|export|eval|deploy/  # stubs
├── configs/default.yaml
└── docs/ARCHITECTURE.md
```

## M1 includes / stubbed next

| Included now | Stubbed for later |
|--------------|-------------------|
| Event schema + bus | Shard packing jobs (Craig) |
| **mici ingest** (Connect / SSH / fixture) | Teacher on 7090 XT |
| `GET /routes` + `POST /jobs/ingest` + WS | Student train (tinygrad) |
| Demo job with staged events | Real export / ONNX / QCOM |
| FastAPI + WS streaming | Eval harness + real flash |
| Rich dark Expo GUI + **Shard pane UX** | |
| `dex routes` / `dex ingest` / `dex demo` | |
| Gated flash UI confirm (unchanged) | |

See `docs/ARCHITECTURE.md` for M1 ingest notes.

## License

Private — Memberoffoxhound.
