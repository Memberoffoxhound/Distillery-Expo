"""Write stock modelV2 / supercombo-I/O ONNX (+ sidecar). Honesty-tagged fixture by default."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODEL_V2_IO: dict[str, Any] = {
    "inputs": {
        "input_imgs": {
            "dtype": "float32",
            "shape": [1, 12, 128, 256],
            "note": "stacked YUV road (2 frames × 6 YUV planes)",
        },
        "big_input_imgs": {
            "dtype": "float32",
            "shape": [1, 12, 128, 256],
            "note": "stacked YUV wide",
        },
        "desire": {"dtype": "float32", "shape": [1, 8], "note": "desire one-hot"},
        "traffic_convention": {"dtype": "float32", "shape": [1, 2], "note": "LHD/RHD"},
        "nav_features": {"dtype": "float32", "shape": [1, 256], "note": "nav embedding"},
        "features_buffer": {
            "dtype": "float32",
            "shape": [1, 99, 512],
            "note": "recurrent feature buffer",
        },
    },
    "outputs": {
        "outputs": {
            "dtype": "float32",
            "shape": [1, 6472],
            "note": "supercombo flat plan/leads/desire/meta",
        },
    },
    "contract": "stock-modelV2",
    "target": "mici/QCOM",
    "compatible_with": "openpilot supercombo / modelV2 I/O",
}


def _onnx_available() -> bool:
    try:
        import onnx  # noqa: F401

        return True
    except ImportError:
        return False


def _student_is_live(student_meta: dict[str, Any] | None) -> bool:
    if not student_meta:
        return False
    meta = student_meta.get("meta") if isinstance(student_meta.get("meta"), dict) else {}
    if student_meta.get("live") is True or meta.get("live") is True:
        return True
    if student_meta.get("soft_labels_live") is True or meta.get("soft_labels_live") is True:
        return True
    src = str(student_meta.get("soft_labels_source") or meta.get("soft_labels_source") or "")
    return src.lower() == "live"


def _write_minimal_onnx_protobuf(path: Path) -> None:
    path.write_bytes(bytes([0x08, 0x07, 0x12, 0x14]) + b"distillery-expo-stub")


def _write_real_onnx_model_v2(path: Path) -> bool:
    try:
        import numpy as np
        import onnx
        from onnx import TensorProto, checker, helper, numpy_helper
    except ImportError:
        return False

    inputs_spec = {n: s["shape"] for n, s in MODEL_V2_IO["inputs"].items()}
    out_shape = list(MODEL_V2_IO["outputs"]["outputs"]["shape"])
    inputs_vi = [
        helper.make_tensor_value_info(n, TensorProto.FLOAT, s) for n, s in inputs_spec.items()
    ]
    y = helper.make_tensor_value_info("outputs", TensorProto.FLOAT, out_shape)

    initializers = []
    nodes = []
    partials: list[str] = []
    initializers.append(
        numpy_helper.from_array(np.array(0.0, dtype=np.float32), name="fixture_zero")
    )
    initializers.append(
        numpy_helper.from_array(np.zeros(out_shape, dtype=np.float32), name="fixture_bias")
    )
    for i, (name, shape) in enumerate(inputs_spec.items()):
        mul_out = f"_z_{i}"
        nodes.append(helper.make_node("Mul", [name, "fixture_zero"], [mul_out]))
        axes_name = f"_axes_{i}"
        initializers.append(
            numpy_helper.from_array(np.arange(len(shape), dtype=np.int64), name=axes_name)
        )
        rs_out = f"_s_{i}"
        nodes.append(helper.make_node("ReduceSum", [mul_out, axes_name], [rs_out], keepdims=0))
        partials.append(rs_out)
    nodes.append(helper.make_node("Sum", partials, ["_contrib"]))
    nodes.append(helper.make_node("Add", ["fixture_bias", "_contrib"], ["outputs"]))

    graph = helper.make_graph(
        nodes, "distillery_student_modelV2_io", inputs_vi, [y], initializer=initializers
    )
    model = helper.make_model(
        graph,
        producer_name="distillery-expo",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    model.doc_string = (
        "fixture stub — stock modelV2 I/O shapes; zero weights; not live / not licensed"
    )
    checker.check_model(model)
    onnx.save(model, str(path))
    return True


def write_onnx_artifact(
    output_dir: Path,
    artifact_name: str = "driving_supercombo.onnx",
    *,
    student_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / artifact_name
    sidecar_path = output_dir / (artifact_name + ".json")
    live = _student_is_live(student_meta)
    artifact_tag = "live" if live else "fixture"
    used = False
    if _onnx_available():
        used = _write_real_onnx_model_v2(onnx_path)
    if not used:
        _write_minimal_onnx_protobuf(onnx_path)
    meta: dict[str, Any] = {
        "artifact": str(onnx_path.name),
        "path": str(onnx_path),
        "format": "onnx" if used else "onnx-stub-protobuf",
        "onnx_package": used,
        "artifact_tag": artifact_tag,
        "tag": artifact_tag,
        "live": live,
        "licensed": False,
        "eval_passed": False,
        "io": MODEL_V2_IO,
        "student": student_meta or {},
        "note": (
            "Real ONNX graph with stock modelV2 I/O (fixture zero weights — not licensed)"
            if used
            else "Minimal protobuf stub — install onnx[+numpy] for full graph; sidecar authoritative"
        ),
    }
    sidecar_path.write_text(json.dumps(meta, indent=2) + "\n")
    return {
        "onnx_path": str(onnx_path),
        "sidecar_path": str(sidecar_path),
        "onnx_package": used,
        "artifact_tag": artifact_tag,
        "live": live,
        "licensed": False,
        "eval_passed": False,
        "io": MODEL_V2_IO,
        "meta": meta,
    }
