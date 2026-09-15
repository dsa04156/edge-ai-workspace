"""Stable request/response boundary; resident lifecycle stays in its existing owner."""
from . import model_runtime, resident


def request_body(target, body, request_id):
    if target["spec"].get("modelRuntime"):
        return model_runtime.request_body(target["spec"], body, request_id)
    if target.get("resident"):
        return resident.request_body(target["spec"], body, request_id)
    return body


def validate_result(target, request_id, result):
    if target["spec"].get("modelRuntime"):
        model_runtime.validate_result(target, request_id, result)
    elif target.get("resident"):
        resident.validate_result(target, request_id, result)


def validate_health(target, health):
    return not target["spec"].get("modelRuntime") or model_runtime.validate_health(target, health)
