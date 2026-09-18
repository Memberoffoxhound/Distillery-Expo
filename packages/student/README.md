# packages/student (`distillery_student`)

Distill a lighter student with **stock modelV2 I/O** (mici/QCOM target).

**Design lock:** I/O compatible with stock modelV2 — no Chestnut student.

## Entrypoint

```python
from distillery_student import run_train_pipeline

result = await run_train_pipeline(job_id, emit, tick=0.0)
# result["final_loss"], result["checkpoint"], result["io_contract"]
```

Consumes `artifacts/soft_labels/` when present (else synthetic fixture).
Uses **pure Python** by default; optional `tinygrad` if installed.
Writes `artifacts/student/student_checkpoint.json`.
