from vision_stage_runner.main import (
    run_capture,
    run_inference,
    run_postprocess,
    run_preprocess,
    run_result_delivery,
)


def test_capture_returns_expected_shape():
    result = run_capture("wf-test")
    assert result["frame_bytes"] == 4096
    assert len(result["checksum"]) == 64


def test_preprocess_compresses_payload():
    result = run_preprocess("wf-test")
    assert result["sample_count"] == 2048
    assert result["compressed_bytes"] > 0


def test_inference_and_postprocess_are_stable():
    inference = run_inference("wf-test")
    postprocess = run_postprocess("wf-test")
    delivery = run_result_delivery("wf-test")

    assert len(inference["class_probabilities"]) == 4
    assert 0 <= inference["predicted_class"] <= 3
    assert postprocess["label"] in {"object_detected", "uncertain"}
    assert delivery["delivery_status"] == "sent"
