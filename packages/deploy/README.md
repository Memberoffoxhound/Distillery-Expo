# packages/deploy

Gated SSH flash of the mici drop-in student model.

## Contract

- **Filename on device:** always `driving_supercombo.onnx` (comma/openpilot modeld layout)
- **Default remote path:** `/data/openpilot/selfdrive/modeld/models/driving_supercombo.onnx`
  - Override with `MICI_MODEL_PATH` (Highland / custom openpilot trees)
- **Gates:** `eval_passed` **and** explicit Confirm — never auto-write
- **Honesty:** `device_write=true` only after successful `scp`; missing SSH → skip with `live=false`

## Env (same pattern as ingest)

| Var | Purpose |
|-----|---------|
| `MICI_SSH_HOST` | mici SSH host (required for live flash) |
| `MICI_SSH_USER` | SSH user (default `comma`) |
| `MICI_SSH_KEY` | optional private key path |
| `MICI_MODEL_PATH` | full remote dest path (default Highland openpilot path above) |

Aliases: `COMMA_SSH_HOST` / `COMMA_SSH_USER` / `COMMA_SSH_KEY` / `COMMA_MODEL_PATH`.

## Local artifact resolution

1. Pipeline-returned `onnx_path` if present
2. `artifacts/export/driving_supercombo.onnx`
3. Fallback: `artifacts/export/student_modelV2_io.onnx` (copied/renamed to `driving_supercombo.onnx` for the push)

## API

`POST /jobs/{id}/flash/confirm` → 403 unless `eval_passed`; then runs `run_flash_pipeline` / `push_supercombo_ssh`.
