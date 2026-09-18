# Distillery Expo

**One-stop tinygrad distill control room** for comma mici routes → Cinque/supercombo teacher (7090 XT) → lighter stock-modelV2-I/O student (mici/QCOM) → export / eval / gated flash.

> M0 = demo skeleton. No real training/GPU code yet. The pipeline emits realistic staged events so the mission-control GUI feels alive.

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

Open **http://localhost:5173** → click **Run demo** (or it auto-starts). Watch the job rail, Thinking timeline, cams placeholders, and staged events stream over WebSocket.

### CLI

```bash
source .venv/bin/activate
dex demo      # start demo job via API
dex stages    # list pipeline stages
```

## Layout

```
Distillery-Expo/
├── apps/
│   ├── api/          # FastAPI jobs + WebSocket event stream
│   ├── cli/          # dex entrypoint
│   └── web/          # Vite + React + TS mission-control GUI
├── packages/
│   ├── events/       # typed event schema (shared)
│   ├── ingest|shards|teacher|student|export|eval|deploy/  # stubs
├── configs/default.yaml
└── docs/ARCHITECTURE.md
```

## M0 includes / stubbed next

| Included now | Stubbed for later |
|--------------|-------------------|
| Event schema + bus | Real route ingest from mici |
| Demo job with staged events | Shard packing |
| FastAPI + WS streaming | Teacher on 7090 XT |
| Rich dark Expo GUI | Student train (tinygrad) |
| `dex demo` / `dex stages` | Real export / ONNX / QCOM |
| Gated flash UI confirm | Eval harness + real flash |

## License

Private — Memberoffoxhound.
