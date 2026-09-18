# Teacher artifacts (Craig fetch/cache <-> Graig consume)

Teach consumes **`big_driving_supercombo` only** (no `driving_supercombo` fallback, no Chestnut).

## Layout (Craig PR #22 / `download.artifact_paths`)

```
artifacts/teachers/
  big_driving_supercombo.onnx            # weight file
  big_driving_supercombo.onnx.sha256     # sidecar: bare hex or sha256sum line
  big_driving_supercombo.json            # optional meta
```

## Integrity (Graig `consume.py`)

- SHA-256 verified **before** teach uses a cached file (`verify_cached_big_teacher`).
- Missing / checksum mismatch -> labeled offline fixture (`live=false` / not licensed).
- Never silent fake live. Never `driving_supercombo` fallback.
