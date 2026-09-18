# packages/shards

**M2:** Pack ingested route/cam samples into training shard descriptors (frame windows, labels, teacher soft-target placeholders) and emit `stage=shard` DistilleryEvents onto the shared bus.

## API

| Method | Path | Body | Notes |
|--------|------|------|-------|
| `POST` | `/jobs/shard` | `{ route_id?, source? }` | Streams on existing `/ws/jobs/{id}` |

## Sample meta (Jony bind)

```json
{
  "cam": "other",
  "label": "shard_000 · 120f",
  "placeholder": true,
  "meta": {
    "shard_id": "shard_000",
    "route_id": "…",
    "frame_count": 120,
    "size_bytes": 17280000,
    "status": "ready",
    "fixture": true
  }
}
```

Also emits `progress`, `metric` (`shards_written`), `stage` running→done, `decision`, `log` — same shapes the Expo Shard pane already binds.

## Fixture

When Connect/SSH/ingest artifacts are unavailable, packing uses the ingest fixture route and labels `meta.fixture` / `meta.label=fixture`.

## CLI (secondary)

```
dex shards --source fixture
dex pack --route ID --local
```

Expo works via HTTP/WS alone.
