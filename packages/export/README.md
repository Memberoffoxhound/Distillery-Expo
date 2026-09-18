# packages/export (`distillery_export`)

Export trained student to a deployable ONNX artifact with **stock modelV2 I/O**.

## Entrypoint

```python
from distillery_export import run_export_pipeline

result = await run_export_pipeline(job_id, emit, tick=0.0)
# result["onnx_path"], result["sidecar_path"], result["io"]
```

- Prefers real ONNX via the optional `onnx` package.
- Otherwise writes a minimal `.onnx` protobuf stub **plus**
  `student_modelV2_io.onnx.json` sidecar documenting I/O shapes.
- Output: `artifacts/export/student_modelV2_io.onnx`
