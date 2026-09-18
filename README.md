# Distillery Expo

**One-stop tinygrad distill control room** for comma mici routes → Cinque/supercombo teacher (7090 XT) → lighter stock-modelV2-I/O student (mici/QCOM) → export / eval / gated flash.

> **M2** = shards pack on the typed event bus + one-command launcher (`./scripts/bootstrap.sh` / `./scripts/dev-up`).
> Expo Shard / Teacher / Train / Eval / Flash panes bind truthful stage events (demo streams them). Flash stays dual-gated. No `/jobs/teach|train|export|eval` yet — use **Run demo** for the full path.

## Hardware (v1)

| Role | Device |
|------|--------|
| Routes / cams | **mici** (comma Connect + local/SSH) |
| Teacher GPU | **AMD Radeon RX 7090 XT** |
| Student target | **mici / QCOM** (stock modelV2 I/O compatible) |

**Design locks:** No Chestnut in v1 · Student stays stock-modelV2 I/O · Flash always gated · Expo GUI is primary; `dex` is the engine CLI.

Dongle default: `3e2de7ed673817c2` (see `configs/default.yaml`).

## Quickstart — bootstrap (bare machine)

If you do not have Node/Python yet (or want the bare-machine path), run the public one-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/Memberoffoxhound/Distillery-Expo/main/scripts/bootstrap.sh | sh
```

Works on **Fedora** (`dnf`), **macOS** (`brew`), and **Steam Deck / Arch / SteamOS** (`pacman`; unlocks read-only root + initializes the pacman keyring when needed).

**Or** — clone, then run locally (update-aware):

```bash
git clone https://github.com/Memberoffoxhound/Distillery-Expo.git ~/Distillery-Expo
cd ~/Distillery-Expo && ./scripts/bootstrap.sh
```

That prints `[1/7]…[7/7]` progress, installs missing tools (**Fedora/`dnf`**, **Steam Deck / Arch/`pacman`**, **macOS/`brew`**), clones to `~/Distillery-Expo` if needed, installs repo deps, and starts Expo at **http://127.0.0.1:5173**.

**Steam Deck / SteamOS (existing checkout):** `git pull` then re-run `./scripts/bootstrap.sh`. Bootstrap runs `steamos-readonly disable`, then **automatic** `pacman-key --init` / `--populate` (`archlinux`, plus `steamos` / `holo` when those keyrings exist), then installs python/node via pacman. No manual keyring steps in the happy path. Desktop mode + sudo password recommended.

Already cloned? From the repo root:

```bash
./scripts/bootstrap.sh
```

### Day-to-day (toolchain already present)

```bash
./scripts/dev-up
```

Opens **http://127.0.0.1:5173**. Then: **Pull mici route** → **Pack shards**.

| Script | Role |
|--------|------|
| `scripts/bootstrap.sh` | Bare machine: system toolchain + venv/pip/npm + launch Expo |
| `scripts/dev-up` | After python3/node/npm exist: venv + deps + launch. On Fedora/`dnf` or Arch/SteamOS/`pacman` (keyring init/populate before install), auto-installs missing tools instead of only dying |

Both are POSIX sh, Fedora-first + Arch/Steam Deck + macOS, portable (no apt-only / glibc-only hard-coding). Safe to re-run.

### Manual two-terminal (optional)

Two terminals from the repo root:

### Terminal 1 — API

```bash
cd /path/to/Distillery-Expo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
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
dex shards --source fixture
dex demo                   # full staged demo (M0)
dex stages
```

Env for live device paths:

| Var | Purpose |
|-----|---------|
| `COMMA_JWT` / `CONNECT_JWT` | comma Connect auth |
| `MICI_SSH_HOST` | mici SSH host |
| `MICI_SSH_USER` | SSH user (default `comma`) |
| `MICI_SSH_KEY` | optional SSH key |
| `MICI_MODEL_PATH` | remote ONNX path (default `/data/openpilot/selfdrive/modeld/models/driving_supercombo.onnx`) |
| `DISTILLERY_INGEST_FIXTURE=1` | force offline fixture |

## ML train readiness (Phil / Bruce)

Train refuses below **50 hours** of driving data unless `DISTILLERY_ALLOW_TOY_TRAIN=1`
(or `student.allow_toy_train` in config) for fixture CI — still `live=false` / not licensed.
Eval forces `eval_passed=false` with `fail_reason=insufficient_hours` on the same floor
when toy is not allowed.

Craig import paths (no API wiring required):

```python
from distillery_student import (
    probe_train_device,          # /health-friendly sync dict
    check_train_readiness,       # train_all gaps: hours / device / teacher
    estimate_driving_hours,
)
from distillery_teacher import (
    list_comma_master_teachers,  # openpilot master stock/big supercombo
    select_comma_master_teacher,
)
```

`probe_train_device()` → `{device_found, device_ready, device_kind, device_name, tinygrad}`
(`tinygrad` ∈ ok|missing|fixture; not 7090-locked).

`list_comma_master_teachers()` offline → `source=fixture` teachers (no Chestnut).

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
│   ├── shards/       # M2 pack → event bus
│   ├── teacher|student|export|eval|deploy/  # stubs
├── configs/default.yaml
└── docs/ARCHITECTURE.md
```

## Ship path (teach → train → export → eval → gated flash)

Expo primary. One-command: `./scripts/bootstrap.sh` (bare) or `./scripts/dev-up` then use Expo or:

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/jobs/teach` | Soft-labels on bus (`stage=teach`) — Graig teacher or labeled fixture |
| `POST` | `/jobs/train` | `train_loss` / progress (`stage=train`) |
| `POST` | `/jobs/export` | ONNX path in logs/metrics (`stage=export`) |
| `POST` | `/jobs/eval` | Real scorecard metrics; `eval_passed` defaults **false** for fixture |
| `POST` | `/jobs/pipeline` | Sequential teach→…→eval→**gated** flash |
| `POST` | `/jobs/{id}/flash/confirm` | **403** unless `eval_passed`; SSH push `driving_supercombo.onnx`; `device_write` only on real scp |

Flash stays locked until eval clears **and** operator confirms. Fixture/offline paths are labeled `live=false` — no greenwashed pass.

WS: `/ws/jobs/{id}` (same bus as ingest/shard).

## M1 includes / stubbed next

| Included now | Stubbed for later |
|--------------|-------------------|
| Event schema + bus | Teacher on 7090 XT |
| **mici ingest** (Connect / SSH / fixture) | Student train (tinygrad) |
| `GET /routes` + `POST /jobs/ingest` + `POST /jobs/shard` + WS | Student train (tinygrad) |
| Demo job with staged events | Real export / ONNX / QCOM |
| FastAPI + WS streaming | Eval harness + real flash |
| Rich dark Expo GUI + **Shard pane UX** | |
| `dex routes` / `dex ingest` / `dex demo` | |
| Gated flash UI confirm (unchanged) | |
| `./scripts/bootstrap.sh` / `./scripts/dev-up` one-command bring-up | |

See `docs/ARCHITECTURE.md` for M1 ingest notes.

## License

Private — Memberoffoxhound.
