from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import time
import zlib


def _seed(stage: str, workflow_id: str) -> random.Random:
    digest = hashlib.sha256(f"{workflow_id}:{stage}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def run_capture(workflow_id: str) -> dict:
    rng = _seed("capture", workflow_id)
    frame = bytes(rng.randrange(0, 256) for _ in range(64 * 64))
    checksum = hashlib.sha256(frame).hexdigest()
    mean_pixel = sum(frame) / len(frame)
    return {
        "frame_bytes": len(frame),
        "checksum": checksum,
        "mean_pixel": round(mean_pixel, 3),
    }


def run_preprocess(workflow_id: str) -> dict:
    rng = _seed("preprocess", workflow_id)
    samples = [rng.randrange(0, 256) for _ in range(2048)]
    mean_value = statistics.fmean(samples)
    normalized = [round((value - mean_value) / 255.0, 6) for value in samples[:256]]
    payload = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(payload, level=6)
    return {
        "sample_count": len(samples),
        "mean_value": round(mean_value, 3),
        "compressed_bytes": len(compressed),
    }


def run_inference(workflow_id: str) -> dict:
    base = hashlib.sha256(workflow_id.encode("utf-8")).digest()
    value = base
    for _ in range(75000):
        value = hashlib.sha256(value).digest()
    raw_scores = [byte / 255.0 for byte in value[:4]]
    scale = sum(math.exp(item) for item in raw_scores)
    probs = [round(math.exp(item) / scale, 6) for item in raw_scores]
    predicted = max(range(len(probs)), key=lambda idx: probs[idx])
    return {
        "class_probabilities": probs,
        "predicted_class": predicted,
        "confidence": probs[predicted],
    }


def run_postprocess(workflow_id: str) -> dict:
    inference = run_inference(workflow_id)
    confidence = inference["confidence"]
    label = "object_detected" if confidence >= 0.28 else "uncertain"
    risk_band = "low" if confidence >= 0.4 else "medium"
    return {
        "label": label,
        "confidence": confidence,
        "risk_band": risk_band,
    }


def run_result_delivery(workflow_id: str) -> dict:
    postprocess = run_postprocess(workflow_id)
    delivery_blob = json.dumps(
        {
            "workflow_id": workflow_id,
            "label": postprocess["label"],
            "confidence": postprocess["confidence"],
        },
        sort_keys=True,
    ).encode("utf-8")
    signature = hashlib.sha256(delivery_blob).hexdigest()[:16]
    return {
        "delivery_status": "sent",
        "signature": signature,
        "payload_bytes": len(delivery_blob),
    }


STAGE_FUNCS = {
    "capture": run_capture,
    "preprocess": run_preprocess,
    "inference": run_inference,
    "postprocess": run_postprocess,
    "result_delivery": run_result_delivery,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vision pipeline stage runner")
    parser.add_argument("--stage", required=True, choices=sorted(STAGE_FUNCS))
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workflow_id = os.getenv("WORKFLOW_ID", "wf-local-demo")
    stage_id = os.getenv("STAGE_ID", args.stage)
    stage_type = os.getenv("STAGE_TYPE", args.stage)
    target_node = os.getenv("TARGET_NODE", "unknown")

    started = time.perf_counter()
    result = STAGE_FUNCS[args.stage](workflow_id)
    if args.sleep_seconds > 0:
        time.sleep(args.sleep_seconds)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    print(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "stage_id": stage_id,
                "stage_type": stage_type,
                "target_node": target_node,
                "elapsed_ms": elapsed_ms,
                "result": result,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
