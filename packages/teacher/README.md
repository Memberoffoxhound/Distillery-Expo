# packages/teacher (`distillery_teacher`)

Cinque/supercombo soft-label producer for distillation.

**Design lock:** No Chestnut in v1. Teacher GPU = AMD Radeon RX 7090 XT when available.

## Entrypoint

```python
from distillery_teacher import run_teach_pipeline

batches = await run_teach_pipeline(job_id, emit, prefer="auto", tick=0.0)
```

## Honesty rules

- Detects AMD/ROCm/7090 XT via sysfs + optional `rocm-smi`.
- If GPU / live Cinque checkpoint missing → **fixture** soft labels with
  `live=false` and `source=fixture` in sample meta + artifact JSON.
- Never claims `live=true` unless `DISTILLERY_TEACHER_LIVE=1` **and** a
  checkpoint is configured (reserved for real weights).
- Force fixture: `DISTILLERY_TEACHER_FIXTURE=1` or `prefer="fixture"`.

Artifacts land under `artifacts/soft_labels/`.
