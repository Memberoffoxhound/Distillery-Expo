# packages/eval (`distillery_eval`)

Offline scorecard — student vs teacher agreement, route replay metrics, flash gate.

**Bar:** No teenagers with driver’s permits. Emit **real** numbers. Never greenwash
a stub to `eval_passed=true`. Fixture/offline → `live=false`; `eval_passed=false`
unless thresholds are actually met on those numbers. Honest fail > pretty fake pass.

## Entrypoint

```python
from distillery_eval import run_eval_pipeline

result = await run_eval_pipeline(job_id, emit, tick=0.0)
# result["eval_passed"]  # bool — Craig gates flash on this
# result["live"], result["source"], result["metrics"], result["gates"]
```

Also emits metric `eval_passed` (1.0/0.0) and a decision with pass/fail chosen.
Writes `artifacts/eval/scorecard.json`.
