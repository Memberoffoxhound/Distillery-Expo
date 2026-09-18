# packages/teacher (`distillery_teacher`)

Cinque/supercombo soft-label producer for distillation.

**Design lock:** No Chestnut in v1. Teacher GPU = AMD Radeon RX 7090 XT when available.
**Happy path:** live comma master **`big_driving_supercombo`** cached under `artifacts/teachers/`.

## Entrypoint

```python
from distillery_teacher import run_teach_pipeline

batches = await run_teach_pipeline(job_id, emit, prefer="auto", tick=0.0)
```

## Honesty rules

- Prefer verified live cache under `artifacts/teachers/` (Craig pull / teach ensure).
- Detects AMD/ROCm/7090 XT via sysfs + optional `rocm-smi`.
- Fixture soft labels are **last-resort** only: always `live=false` /
  `source=fixture` / not licensed — never the default happy path.
- Force fixture (CI only): `DISTILLERY_TEACHER_FIXTURE=1`,
  `prefer="fixture"`, or explicit `force_fixture=True`.
  `DISTILLERY_INGEST_FIXTURE` does **not** force teacher fixture.
- Never claims `live=true` unless `DISTILLERY_TEACHER_LIVE=1` **and** a
  checkpoint is configured (reserved for real weights).

Artifacts land under `artifacts/soft_labels/`.

## Teacher artifact consume (big only)

Craig fetch/cache writes `artifacts/teachers/big_driving_supercombo.onnx` + `.sha256`.
Graig `consume_big_teacher_for_teach` verifies checksum before soft-labels.

- Missing / checksum fail / explicit CI flag → labeled fixture (`ok=False`,
  `live=false` / not licensed)
- **Never** `driving_supercombo` fallback. No Chestnut.
