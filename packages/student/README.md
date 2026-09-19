# packages/student (`distillery_student`)

Distill a lighter student with **stock modelV2 I/O** (mici/QCOM target).

**Design lock:** I/O compatible with stock modelV2 — no Chestnut student.

## Entrypoint

```python
from distillery_student import run_train_pipeline, check_train_readiness

result = await run_train_pipeline(job_id, emit, tick=0.0)
# result["final_loss"], result["checkpoint"], result["io_contract"]

ready = check_train_readiness()  # gaps if live teacher cache missing
```

Happy path consumes live soft-labels from a verified
`big_driving_supercombo` teacher. Fixture / synthetic soft-labels are
last-resort CI only (`DISTILLERY_STUDENT_FIXTURE=1` /
`DISTILLERY_ALLOW_TOY_TRAIN=1`) — always `live=false` / not licensed.
`DISTILLERY_INGEST_FIXTURE` does **not** force the student fixture path.

Train/teach compute uses **PyTorch** when installed (`pip install 'distillery-expo[torch]'`; CPU wheels OK). Pure-Python fallback when torch is missing. `/health` device chip uses Craig's `probe_train_device()` (cuda/rocm/mps/cpu).
Writes `artifacts/student/student_checkpoint.json`.
