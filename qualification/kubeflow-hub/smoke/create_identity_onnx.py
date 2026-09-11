#!/usr/bin/env python3
"""Generate a minimal valid ONNX identity model for registry qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import onnx
from onnx import TensorProto, helper


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 4])
    output_info = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 4])
    node = helper.make_node("Identity", inputs=["input"], outputs=["output"])
    graph = helper.make_graph([node], "edge-ai-registry-smoke", [input_info], [output_info])
    model = helper.make_model(
        graph,
        producer_name="edge-ai-kubeflow-hub-qualification",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    onnx.checker.check_model(model)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, args.output)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(json.dumps({"path": str(args.output), "sha256": digest, "bytes": args.output.stat().st_size}))


if __name__ == "__main__":
    main()
