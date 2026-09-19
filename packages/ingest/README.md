# packages/ingest

**M1 thin slice:** Pull mici routes via **comma Connect** and/or **local SSH**, resolve dongle from env / `.cache` (GUI Save), list segments, and emit `stage=ingest` progress + cam `sample` events onto the shared Distillery event bus.

## Sources (priority)

| Prefer | When |
|--------|------|
| `public` | `COMMA_JWT` set — shared/public Connect drives (no dongle required) |
| `connect` | `COMMA_JWT` + saved dongle (My Connect); `scope=public` also lists shared/public |

| `ssh` | `MICI_SSH_HOST` (+ optional `MICI_SSH_KEY`, `MICI_SSH_USER`) |
| `fixture` | No creds, or `DISTILLERY_INGEST_FIXTURE=1` |

Picker contract for Expo UI: `docs/routes-picker-contract.json` (Public routes | My Connect | SSH/ADB).
Demo/fixture dongle `3e2de7ed673817c2` is hard-banned as a live query target / cache default.

Fixture routes are **truthful-shaped** (Connect-like `route_id`, segments, per-cam hevc metadata) and labeled `meta.fixture` / `meta.label=fixture` with `placeholder=true` on samples.

Dongle: empty until `POST /dongle` / `DISTILLERY_DONGLE_ID` / `.cache/dongle_id`, or auto-hydrate when ADB/SSH reads `/data/params/d/DongleId` (never overwrites a saved id; never invents a demo id). Stale demo id `3e2de7ed673817c2` in env/cache is cleared and never auto-queried. Fixture sample may still use that labeled id.

## Event contract

Ingest jobs emit existing `DistilleryEvent` kinds only:

- `stage` — `name=ingest`, `status=running|done|failed`
- `progress` — `fraction` 0–1 + detail
- `decision` — route source choice
- `metric` — `segments_found`, `route_hours`
- `sample` — one+ per cam (`road` / `wide` / `driver`) with `uri`, `meta` (fps, size, route_id, source, fixture flag)
- `log` — human-readable

## Python API

```python
from distillery_ingest import load_ingest_config, run_ingest_pipeline
from distillery_ingest.resolve import list_routes

cfg = load_ingest_config()
src, routes = list_routes(cfg, prefer="auto")
# async: await run_ingest_pipeline(job_id, emit, route_id=..., prefer="auto")
```

## Layout

```
distillery_ingest/
  config.py      # YAML + env
  models.py      # RouteInfo / SegmentInfo / CamSample
  resolve.py     # Connect → SSH → fixture
  pipeline.py    # emit DistilleryEvents
  sources/       # connect.py, public.py, ssh.py, fixture.py
fixtures/sample_route.json
```


## Discovery (Expo picker)

| Endpoint | Purpose |
|----------|---------|
| `GET /discover` | Combined: ADB devices + Connect + SSH + fixture |
| `GET /discover/devices` | `adb devices -l` → id, model, transport, suggested_host |
| `GET /discover/connect` | Connect JWT status (masked; no secrets) |
| `POST /discover/connect` | `{ "jwt": "...", "persist": true }` → env + `.cache/connect_jwt` |
| `GET /discover/ssh` | SSH status (host/user/port/identity path; no key bytes) |
| `POST /discover/ssh` | `{ "host", "user", "port", "identity_path?", "persist" }` → env + `.cache/ssh_config.json` |
| `POST /discover/ssh/test` | Short SSH probe `{ ok, error }` (~5s timeout) |
| `GET /routes?source=public\|connect\|ssh\|fixture&device=&ssh_host=` | List routes (public = shared Connect; connect = My Connect) |

Fixture remains the offline fallback and is labeled `meta.label=fixture`.
