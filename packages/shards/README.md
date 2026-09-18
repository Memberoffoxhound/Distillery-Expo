# packages/shards

**v1 scope:** Pack ingested segments into training shards (frame windows, labels, teacher soft-targets placeholders).

**M0:** stub only — demo emits shard progress metrics.

**Expo (M2 UX):** The Shard pane binds to existing bus events with `stage=shard`
(`progress` / `metric` / `stage` / optional `decision`) — same contract as Ingest/Train.
Dedicated pack jobs / richer contracts are Craig’s follow-on; the pane stays honest when idle.
