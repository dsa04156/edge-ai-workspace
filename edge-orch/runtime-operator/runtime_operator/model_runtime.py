"""Bounded JSON-tensor subset of Open Inference Protocol V2, independent of models."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TensorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    datatype: Literal["FP32", "FP64", "INT32", "INT64"]
    shape: list[int] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded(self):
        if any(d <= 0 for d in self.shape) or math.prod(self.shape) > 262144:
            raise ValueError("fixed_bounded_tensor_required")
        return self


class ModelRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    protocol: Literal["inference-v2-json"] = "inference-v2-json"
    modelName: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    modelVersion: str = Field(pattern=r"^[a-f0-9]{64}$")
    inputKind: Literal["image", "sensor-window", "tensor"] = "tensor"
    inputs: list[TensorSpec] = Field(min_length=1, max_length=16)
    outputs: list[TensorSpec] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_names(self):
        for values in (self.inputs, self.outputs):
            if len({t.name for t in values}) != len(values):
                raise ValueError("duplicate_tensor_name")
        return self


def tensors(values, specs):
    if not isinstance(values, list) or len(values) != len(specs):
        raise ValueError("tensor_count_mismatch")
    expected = {s["name"]: s for s in specs}
    seen = set()
    for tensor in values:
        if not isinstance(tensor, dict) or set(tensor) != {"name", "datatype", "shape", "data"}:
            raise ValueError("bounded_json_tensor_required")
        name = tensor["name"]
        if not isinstance(name, str) or name in seen or name not in expected:
            raise ValueError("tensor_name_mismatch")
        seen.add(name)
        spec = expected[name]
        if (tensor["datatype"] != spec["datatype"] or tensor["shape"] != spec["shape"]
                or any(type(d) is not int for d in tensor["shape"])):
            raise ValueError("tensor_schema_mismatch")
        data = tensor["data"]
        if not isinstance(data, list) or len(data) != math.prod(spec["shape"]):
            raise ValueError("tensor_size_mismatch")
        bits = 32 if spec["datatype"] == "INT32" else 64
        for value in data:
            if spec["datatype"].startswith("INT"):
                if type(value) is not int or not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                    raise ValueError("integer_tensor_required")
            else:
                limit = 3.4028234663852886e38 if spec["datatype"] == "FP32" else 1.7976931348623157e308
                if type(value) not in (int, float) or not -limit <= value <= limit:
                    raise ValueError("finite_numeric_tensor_required")


def request_body(spec, body, request_id):
    contract = spec["modelRuntime"]
    if set(body) - {"id", "inputs"} or body.get("id", request_id) != request_id:
        raise ValueError("inference_request_identity_mismatch")
    tensors(body.get("inputs"), contract["inputs"])
    return {"id": request_id, "inputs": body["inputs"]}


def validate_result(target, request_id, result):
    contract = target["spec"]["modelRuntime"]
    if (not isinstance(result, dict) or result.get("id") != request_id
            or result.get("model_name") != contract["modelName"]
            or result.get("model_version") != contract["modelVersion"]):
        raise ValueError("model_response_identity_mismatch")
    tensors(result.get("outputs"), contract["outputs"])


def validate_health(target, health):
    contract = target["spec"]["modelRuntime"]
    return (health.get("model_name") == contract["modelName"]
            and health.get("model_version") == contract["modelVersion"]
            and health.get("inputs") == contract["inputs"] and health.get("outputs") == contract["outputs"])
