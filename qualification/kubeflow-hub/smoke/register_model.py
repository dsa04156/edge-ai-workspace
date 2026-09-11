#!/usr/bin/env python3
"""Create and verify one Kubeflow Hub model/version/artifact metadata chain."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from model_registry import ModelRegistry


MODEL_NAME = "edge-ai-identity-smoke"
MODEL_VERSION = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--artifact-uri", required=True)
    args = parser.parse_args()

    digest = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    registry = ModelRegistry(
        server_address=args.host,
        port=args.port,
        author="edge-ai-qualification",
        is_secure=False,
    )

    created = registry.get_registered_model(MODEL_NAME) is None
    if created:
        registry.register_model(
            MODEL_NAME,
            args.artifact_uri,
            model_format_name="onnx",
            model_format_version="1",
            version=MODEL_VERSION,
            version_description="Identity ONNX model for metadata persistence testing",
            metadata={
                "edge.architectures": "amd64,arm64",
                "edge.runtimeCandidates": "onnxruntime-cpu",
                "edge.profileRef": "pending",
                "edge.artifactSha256": digest,
                "edge.qualification": True,
            },
        )

    model = registry.get_registered_model(MODEL_NAME)
    version = registry.get_model_version(MODEL_NAME, MODEL_VERSION)
    artifact = registry.get_model_artifact(MODEL_NAME, MODEL_VERSION)
    if model is None or version is None or artifact is None:
        raise RuntimeError("registered model chain was not readable after creation")
    if artifact.uri != args.artifact_uri:
        raise RuntimeError(f"artifact URI mismatch: {artifact.uri!r}")
    if artifact.model_format_name != "onnx":
        raise RuntimeError(f"model format mismatch: {artifact.model_format_name!r}")

    expected_metadata = {
        "edge.architectures": "amd64,arm64",
        "edge.runtimeCandidates": "onnxruntime-cpu",
        "edge.profileRef": "pending",
        "edge.artifactSha256": digest,
        "edge.qualification": True,
    }
    actual_metadata = version.custom_properties or {}
    if actual_metadata != expected_metadata:
        raise RuntimeError(f"version metadata mismatch: {actual_metadata!r}")

    expected_description = "Kubeflow Hub standalone qualification model (CRUD verified)"
    if model.description != expected_description:
        model.description = expected_description
        registry.update(model)
        model = registry.get_registered_model(MODEL_NAME)
    if model is None or model.description != expected_description:
        raise RuntimeError("registered model update was not persisted")

    print(
        json.dumps(
            {
                "created": created,
                "model": {"id": model.id, "name": model.name},
                "version": {"id": version.id, "name": version.name},
                "artifact": {
                    "id": artifact.id,
                    "uri": artifact.uri,
                    "format": artifact.model_format_name,
                    "sha256": digest,
                },
                "metadataVerified": True,
                "updateVerified": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
