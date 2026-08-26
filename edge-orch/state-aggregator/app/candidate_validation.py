from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import Field, field_validator, model_validator

from .models import SchedulingModel


ValidationStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED"]
ValidationOperator = Literal["equals", "exists", "greater_than", "less_or_equal", "max_age_seconds"]


class ValidationAssertion(SchedulingModel):
    pointer: str
    operator: ValidationOperator
    value: Any = None
    measurement: str | None = None
    reason_code: str
    reason_by_value: dict[str, str] = Field(default_factory=dict)

    @field_validator("pointer")
    @classmethod
    def validate_pointer(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("validation pointers must be JSON Pointers")
        return value

    @model_validator(mode="after")
    def validate_value(self) -> "ValidationAssertion":
        if self.operator in {"greater_than", "less_or_equal", "max_age_seconds"}:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError("numeric validation operators require a numeric value")
        if self.operator == "max_age_seconds" and float(self.value) < 0:
            raise ValueError("max_age_seconds must be non-negative")
        return self


class ValidationCondition(SchedulingModel):
    pointer: str
    equals: Any

    @field_validator("pointer")
    @classmethod
    def validate_pointer(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("validation condition must use a JSON Pointer")
        return value


class ValidationCheck(SchedulingModel):
    name: str
    source: Literal["kubernetes", "http_json"]
    required: bool = True
    enforce_when_observed: bool = False
    path: str | None = None
    query: dict[str, str | int | float | bool] = Field(default_factory=dict)
    expected_http_status: int = Field(default=200, ge=100, le=599)
    assertions: list[ValidationAssertion] = Field(default_factory=list)
    condition: ValidationCondition | None = None
    failure_reason_code: str
    unreachable_reason_code: str = "candidate_endpoint_unreachable"

    @model_validator(mode="after")
    def validate_source(self) -> "ValidationCheck":
        if self.source == "http_json":
            if not self.path or not self.path.startswith("/") or "://" in self.path:
                raise ValueError("HTTP validation checks require a relative path")
        elif self.path is not None or self.assertions or self.condition is not None:
            raise ValueError("Kubernetes validation checks cannot contain HTTP fields")
        return self


class ValidationStabilization(SchedulingModel):
    timeout_seconds: float = Field(gt=0, le=600)
    request_timeout_seconds: float = Field(gt=0, le=30)
    poll_interval_seconds: float = Field(gt=0, le=60)
    minimum_stable_seconds: float = Field(ge=0, le=600)
    required_consecutive_successes: int = Field(ge=1, le=1000)


class ValidationComparisonContract(SchedulingModel):
    path: str
    input_state_pointer: str = "/inputState"
    model_state_pointer: str = "/modelState"
    latency_pointer: str = "/performance/processingLatencyP95Ms"
    result_observed_at_pointer: str = "/latest/observedAt"

    @field_validator(
        "path",
        "input_state_pointer",
        "model_state_pointer",
        "latency_pointer",
        "result_observed_at_pointer",
    )
    @classmethod
    def validate_relative_value(cls, value: str) -> str:
        if not value.startswith("/") or "://" in value:
            raise ValueError("comparison values must be relative paths or JSON Pointers")
        return value


class CandidateValidationContract(SchedulingModel):
    service_id: str
    contract_version: str
    candidate_port_name: str
    stabilization: ValidationStabilization
    checks: list[ValidationCheck] = Field(min_length=1)
    pre_activation_checks: list[ValidationCheck] = Field(default_factory=list)
    comparison: ValidationComparisonContract | None = None

    @model_validator(mode="after")
    def validate_checks(self) -> "CandidateValidationContract":
        for checks in (self.checks, self.pre_activation_checks):
            if not checks:
                continue
            names = [check.name for check in checks]
            if len(names) != len(set(names)) or "pod_ready" not in names:
                raise ValueError("validation checks must be unique and include pod_ready")
        return self

    def for_phase(
        self,
        phase: Literal["pre_activation", "active"],
    ) -> "CandidateValidationContract":
        if phase == "active":
            return self.model_copy(deep=True)
        if not self.pre_activation_checks:
            raise ValueError("pre-activation validation checks are not configured")
        contract = self.model_copy(deep=True)
        contract.checks = [item.model_copy(deep=True) for item in self.pre_activation_checks]
        return contract


class CandidateValidationContractCatalog(SchedulingModel):
    api_version: Literal["edge-ai.io/v1alpha1"]
    kind: Literal["CandidateValidationContractCatalog"]
    contracts: list[CandidateValidationContract]


class ValidationContractCatalog:
    def __init__(
        self,
        contracts: dict[str, CandidateValidationContract],
        errors: dict[str, str] | None = None,
    ) -> None:
        self.contracts = contracts
        self.errors = errors or {}

    @classmethod
    def load(cls, path: Path) -> "ValidationContractCatalog":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls({}, {"*": "candidate_validation_contract_unsupported"})
        if not isinstance(payload, dict) or not isinstance(payload.get("contracts"), list):
            return cls({}, {"*": "candidate_validation_contract_unsupported"})
        contracts: dict[str, CandidateValidationContract] = {}
        errors: dict[str, str] = {}
        for raw in payload["contracts"]:
            service_id = raw.get("serviceId") if isinstance(raw, dict) else None
            try:
                contract = CandidateValidationContract.model_validate(raw)
            except Exception:
                errors[str(service_id or "*")] = "candidate_validation_contract_unsupported"
                continue
            if contract.service_id in contracts:
                errors[contract.service_id] = "candidate_validation_contract_unsupported"
                contracts.pop(contract.service_id, None)
                continue
            contracts[contract.service_id] = contract
        try:
            CandidateValidationContractCatalog.model_validate(
                {
                    **payload,
                    "contracts": [
                        item.model_dump(by_alias=True) for item in contracts.values()
                    ],
                }
            )
        except Exception:
            return cls({}, {"*": "candidate_validation_contract_unsupported"})
        return cls(contracts, errors)

    def resolve(
        self,
        service_id: str,
    ) -> tuple[CandidateValidationContract | None, str | None]:
        if service_id in self.errors or "*" in self.errors:
            return None, "candidate_validation_contract_unsupported"
        contract = self.contracts.get(service_id)
        if contract is None:
            return None, "candidate_validation_contract_unsupported"
        return contract, None


class CandidateValidationCheckResult(SchedulingModel):
    name: str
    status: ValidationStatus
    required: bool
    evaluated: bool = True
    reason_codes: list[str] = Field(default_factory=list)
    observed_at: datetime
    measurements: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class CandidateValidationWorkloadObservation(SchedulingModel):
    node: str | None = None
    pod: str | None = None
    reachable: bool = False
    input_state: str | None = None
    model_state: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    result_observed_at: datetime | None = None
    frames_processed: int | None = Field(default=None, ge=0)
    observed_at: datetime


class CandidateValidationResult(SchedulingModel):
    status: ValidationStatus
    reason_codes: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    stable_since: datetime | None = None
    consecutive_successes: int = Field(default=0, ge=0)
    required_consecutive_successes: int = Field(ge=1)
    minimum_stable_seconds: float = Field(ge=0)
    checks: list[CandidateValidationCheckResult] = Field(default_factory=list)
    source: CandidateValidationWorkloadObservation | None = None
    candidate: CandidateValidationWorkloadObservation | None = None
    observed_at: datetime


ValidationObserver = Callable[[CandidateValidationResult], Awaitable[None] | None]


class CandidateValidationEngine:
    def __init__(
        self,
        kube: Any,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.kube = kube
        self.transport = transport
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or asyncio.sleep

    async def validate(
        self,
        *,
        contract: CandidateValidationContract,
        candidate_namespace: str,
        candidate_name: str,
        candidate_node: str,
        candidate_port: int,
        plan_id: str,
        source_namespace: str,
        source_selector: dict[str, str],
        source_node: str | None,
        observer: ValidationObserver | None = None,
        candidate_base_url: str | None = None,
        minimum_frames_processed_exclusive: int | None = None,
        frames_processed_pointer: str = "/counters/framesProcessed",
    ) -> CandidateValidationResult:
        started_at = _utc(self.now())
        result = CandidateValidationResult(
            status="RUNNING",
            started_at=started_at,
            required_consecutive_successes=(
                contract.stabilization.required_consecutive_successes
            ),
            minimum_stable_seconds=contract.stabilization.minimum_stable_seconds,
            observed_at=started_at,
        )
        deadline = self.monotonic() + contract.stabilization.timeout_seconds
        stable_monotonic: float | None = None
        last_gating_reasons: list[str] = []
        async with httpx.AsyncClient(
            timeout=contract.stabilization.request_timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        ) as client:
            while True:
                observed_at = _utc(self.now())
                checks, candidate, terminal = await self._observe_candidate(
                    contract=contract,
                    client=client,
                    namespace=candidate_namespace,
                    name=candidate_name,
                    expected_node=candidate_node,
                    port=candidate_port,
                    plan_id=plan_id,
                    observed_at=observed_at,
                    base_url_override=candidate_base_url,
                    minimum_frames_processed_exclusive=minimum_frames_processed_exclusive,
                    frames_processed_pointer=frames_processed_pointer,
                )
                source = await self._observe_source(
                    contract=contract,
                    client=client,
                    namespace=source_namespace,
                    selector=source_selector,
                    expected_node=source_node,
                    port=candidate_port,
                    observed_at=observed_at,
                )
                gating_failures = [
                    check
                    for check in checks
                    if (
                        check.required and check.status != "SUCCEEDED"
                    ) or (
                        not check.required
                        and check.evaluated
                        and check.status == "FAILED"
                        and _check_contract(contract, check.name).enforce_when_observed
                    )
                ]
                if not gating_failures:
                    result.consecutive_successes += 1
                    if stable_monotonic is None:
                        stable_monotonic = self.monotonic()
                        result.stable_since = observed_at
                else:
                    result.consecutive_successes = 0
                    result.stable_since = None
                    stable_monotonic = None
                    last_gating_reasons = _unique(
                        [reason for check in gating_failures for reason in check.reason_codes]
                    )
                result.checks = checks
                result.candidate = candidate
                result.source = source
                result.observed_at = observed_at

                stable_duration = (
                    self.monotonic() - stable_monotonic
                    if stable_monotonic is not None
                    else 0.0
                )
                if (
                    not gating_failures
                    and result.consecutive_successes
                    >= contract.stabilization.required_consecutive_successes
                    and stable_duration >= contract.stabilization.minimum_stable_seconds
                ):
                    result.status = "SUCCEEDED"
                    result.reason_codes = ["candidate_validation_succeeded"]
                    result.completed_at = observed_at
                    await _notify(observer, result)
                    return result
                if terminal:
                    result.status = "FAILED"
                    result.reason_codes = ["candidate_validation_contract_unsupported"]
                    result.completed_at = observed_at
                    await _notify(observer, result)
                    return result
                if self.monotonic() >= deadline:
                    result.status = "FAILED"
                    result.reason_codes = _unique(
                        ["candidate_validation_timeout", *last_gating_reasons]
                    )
                    result.completed_at = observed_at
                    await _notify(observer, result)
                    return result
                await _notify(observer, result)
                await self.sleep(contract.stabilization.poll_interval_seconds)

    async def _observe_candidate(
        self,
        *,
        contract: CandidateValidationContract,
        client: httpx.AsyncClient,
        namespace: str,
        name: str,
        expected_node: str,
        port: int,
        plan_id: str,
        observed_at: datetime,
        base_url_override: str | None,
        minimum_frames_processed_exclusive: int | None,
        frames_processed_pointer: str,
    ) -> tuple[
        list[CandidateValidationCheckResult],
        CandidateValidationWorkloadObservation,
        bool,
    ]:
        try:
            pods = await self.kube.list_deployment_pods(namespace, name)
        except Exception:
            pods = []
        pod = next(
            (
                item
                for item in pods
                if _pod_ready(item)
                and _pod_node(item) == expected_node
                and _pod_plan_matches(item, plan_id)
            ),
            None,
        )
        pod_name = _pod_name(pod)
        pod_ip = _pod_ip(pod)
        observation = CandidateValidationWorkloadObservation(
            node=_pod_node(pod) or expected_node,
            pod=pod_name,
            reachable=False,
            observed_at=observed_at,
        )
        pod_check = CandidateValidationCheckResult(
            name="pod_ready",
            status="SUCCEEDED" if pod is not None and pod_ip else "BLOCKED",
            required=True,
            evaluated=True,
            reason_codes=[] if pod is not None and pod_ip else ["candidate_not_ready"],
            observed_at=observed_at,
            measurements={"pod": pod_name, "podIpObserved": bool(pod_ip)},
        )
        if pod is None or not pod_ip:
            blocked_checks = [
                CandidateValidationCheckResult(
                    name=check.name,
                    status="BLOCKED",
                    required=check.required,
                    evaluated=False,
                    reason_codes=["candidate_not_ready"],
                    observed_at=observed_at,
                )
                for check in contract.checks
                if check.source == "http_json"
            ]
            return [pod_check, *blocked_checks], observation, False

        base_url = base_url_override or _pod_base_url(pod_ip, port)
        checks, cache, terminal = await self._http_checks(
            contract,
            client,
            base_url,
            observed_at,
        )
        status_payload = _cached_payload(cache, "/api/v1/status")
        observation = _workload_observation(
            status_payload,
            node=_pod_node(pod),
            pod=pod_name,
            reachable=any(item.status != "BLOCKED" for item in checks),
            observed_at=observed_at,
            frames_processed_pointer=frames_processed_pointer,
        )
        if minimum_frames_processed_exclusive is not None:
            passed = (
                observation.frames_processed is not None
                and observation.frames_processed > minimum_frames_processed_exclusive
            )
            checks.append(
                CandidateValidationCheckResult(
                    name="processing_counter_increased",
                    status="SUCCEEDED" if passed else "FAILED",
                    required=True,
                    reason_codes=[] if passed else ["candidate_inference_not_observed"],
                    observed_at=observed_at,
                    measurements={
                        "baseline": minimum_frames_processed_exclusive,
                        "framesProcessed": observation.frames_processed,
                    },
                )
            )
        return [pod_check, *checks], observation, terminal

    async def _observe_source(
        self,
        *,
        contract: CandidateValidationContract,
        client: httpx.AsyncClient,
        namespace: str,
        selector: dict[str, str],
        expected_node: str | None,
        port: int,
        observed_at: datetime,
    ) -> CandidateValidationWorkloadObservation | None:
        if contract.comparison is None or not selector:
            return None
        try:
            pods = await self.kube.list_pods(namespace, _label_selector(selector))
        except Exception:
            return CandidateValidationWorkloadObservation(
                node=expected_node,
                reachable=False,
                observed_at=observed_at,
            )
        pod = next(
            (
                item
                for item in pods
                if _pod_ready(item)
                and (expected_node is None or _pod_node(item) == expected_node)
                and _pod_ip(item)
            ),
            None,
        )
        if pod is None:
            return CandidateValidationWorkloadObservation(
                node=expected_node,
                reachable=False,
                observed_at=observed_at,
            )
        try:
            response = await client.get(
                f"{_pod_base_url(_pod_ip(pod), port)}{contract.comparison.path}"
            )
            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    "source comparison returned non-success",
                    request=response.request,
                    response=response,
                )
            if len(response.content) > 262_144:
                raise ValueError("comparison response is too large")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("comparison response must be an object")
        except (httpx.HTTPError, ValueError):
            return CandidateValidationWorkloadObservation(
                node=_pod_node(pod),
                pod=_pod_name(pod),
                reachable=False,
                observed_at=observed_at,
            )
        return _workload_observation(
            payload,
            node=_pod_node(pod),
            pod=_pod_name(pod),
            reachable=True,
            observed_at=observed_at,
            comparison=contract.comparison,
        )

    async def _http_checks(
        self,
        contract: CandidateValidationContract,
        client: httpx.AsyncClient,
        base_url: str,
        observed_at: datetime,
    ) -> tuple[
        list[CandidateValidationCheckResult],
        dict[tuple[str, tuple[tuple[str, str], ...]], Any],
        bool,
    ]:
        cache: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}
        results: list[CandidateValidationCheckResult] = []
        terminal = False
        for check in contract.checks:
            if check.source == "kubernetes":
                continue
            key = _request_key(check)
            payload: Any
            if key not in cache:
                try:
                    response = await client.get(
                        f"{base_url}{check.path}",
                        params=check.query,
                    )
                    if response.status_code != check.expected_http_status:
                        cache[key] = _HttpFailure(
                            check.failure_reason_code,
                            response.status_code,
                        )
                    else:
                        if len(response.content) > 262_144:
                            cache[key] = _InvalidPayload()
                            continue
                        parsed = response.json()
                        cache[key] = parsed if isinstance(parsed, (dict, list)) else _InvalidPayload()
                except httpx.HTTPError:
                    cache[key] = _HttpFailure(check.unreachable_reason_code, None)
                except ValueError:
                    cache[key] = _InvalidPayload()
            payload = cache[key]
            if isinstance(payload, _HttpFailure):
                results.append(
                    CandidateValidationCheckResult(
                        name=check.name,
                        status="BLOCKED" if payload.status_code is None else "FAILED",
                        required=check.required,
                        reason_codes=[payload.reason_code],
                        observed_at=observed_at,
                        measurements={"httpStatus": payload.status_code},
                    )
                )
                continue
            if isinstance(payload, _InvalidPayload):
                terminal = True
                results.append(
                    CandidateValidationCheckResult(
                        name=check.name,
                        status="FAILED",
                        required=check.required,
                        reason_codes=["candidate_validation_contract_unsupported"],
                        observed_at=observed_at,
                    )
                )
                continue
            results.append(_evaluate_check(check, payload, observed_at))
        return results, cache, terminal


class _HttpFailure:
    def __init__(self, reason_code: str, status_code: int | None) -> None:
        self.reason_code = reason_code
        self.status_code = status_code


class _InvalidPayload:
    pass


def _evaluate_check(
    check: ValidationCheck,
    payload: Any,
    observed_at: datetime,
) -> CandidateValidationCheckResult:
    if check.condition is not None:
        actual, present = _json_pointer(payload, check.condition.pointer)
        if not present or actual != check.condition.equals:
            return CandidateValidationCheckResult(
                name=check.name,
                status="BLOCKED",
                required=check.required,
                evaluated=False,
                reason_codes=["candidate_latency_not_observed_optional"],
                observed_at=observed_at,
                measurements={"available": False},
            )
    reasons: list[str] = []
    measurements: dict[str, str | int | float | bool | None] = {}
    for assertion in check.assertions:
        actual, present = _json_pointer(payload, assertion.pointer)
        if assertion.measurement:
            measurements[assertion.measurement] = _measurement(actual if present else None)
        passed = _assertion_passes(assertion, actual, present, observed_at)
        if not passed:
            reasons.append(
                assertion.reason_by_value.get(str(actual), assertion.reason_code)
            )
    return CandidateValidationCheckResult(
        name=check.name,
        status="SUCCEEDED" if not reasons else "FAILED",
        required=check.required,
        evaluated=True,
        reason_codes=_unique(reasons),
        observed_at=observed_at,
        measurements=measurements,
    )


def _assertion_passes(
    assertion: ValidationAssertion,
    actual: Any,
    present: bool,
    observed_at: datetime,
) -> bool:
    if assertion.operator == "exists":
        return present and actual is not None
    if not present:
        return False
    if assertion.operator == "equals":
        return actual == assertion.value
    if assertion.operator == "greater_than":
        return _number_compare(actual, assertion.value, lambda a, b: a > b)
    if assertion.operator == "less_or_equal":
        return _number_compare(actual, assertion.value, lambda a, b: a <= b)
    if assertion.operator == "max_age_seconds":
        timestamp = _parse_datetime(actual)
        if timestamp is None:
            return False
        age = (observed_at - timestamp).total_seconds()
        return -5 <= age <= float(assertion.value)
    return False


def _number_compare(actual: Any, expected: Any, compare: Callable[[float, float], bool]) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        return compare(float(actual), float(expected))
    except (TypeError, ValueError):
        return False


def _json_pointer(payload: Any, pointer: str) -> tuple[Any, bool]:
    current = payload
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return None, False
    return current, True


def _workload_observation(
    payload: Any,
    *,
    node: str | None,
    pod: str | None,
    reachable: bool,
    observed_at: datetime,
    comparison: ValidationComparisonContract | None = None,
    frames_processed_pointer: str = "/counters/framesProcessed",
) -> CandidateValidationWorkloadObservation:
    if not isinstance(payload, dict):
        return CandidateValidationWorkloadObservation(
            node=node,
            pod=pod,
            reachable=reachable,
            observed_at=observed_at,
        )
    contract = comparison or ValidationComparisonContract(path="/api/v1/status")
    input_state, _ = _json_pointer(payload, contract.input_state_pointer)
    model_state, _ = _json_pointer(payload, contract.model_state_pointer)
    latency, latency_present = _json_pointer(payload, contract.latency_pointer)
    result_time, result_present = _json_pointer(
        payload,
        contract.result_observed_at_pointer,
    )
    frames_processed, frames_present = _json_pointer(payload, frames_processed_pointer)
    return CandidateValidationWorkloadObservation(
        node=node,
        pod=pod,
        reachable=reachable,
        input_state=str(input_state) if input_state is not None else None,
        model_state=str(model_state) if model_state is not None else None,
        latency_ms=(
            float(latency)
            if latency_present
            and isinstance(latency, (int, float))
            and not isinstance(latency, bool)
            else None
        ),
        result_observed_at=_parse_datetime(result_time) if result_present else None,
        frames_processed=(
            int(frames_processed)
            if frames_present
            and isinstance(frames_processed, (int, float))
            and not isinstance(frames_processed, bool)
            and frames_processed >= 0
            else None
        ),
        observed_at=observed_at,
    )


def _cached_payload(
    cache: dict[tuple[str, tuple[tuple[str, str], ...]], Any],
    path: str,
) -> Any:
    for (cached_path, _), payload in cache.items():
        if cached_path == path and not isinstance(payload, (_HttpFailure, _InvalidPayload)):
            return payload
    return None


def _request_key(check: ValidationCheck) -> tuple[str, tuple[tuple[str, str], ...]]:
    return (
        check.path or "",
        tuple(sorted((key, str(value)) for key, value in check.query.items())),
    )


def _check_contract(
    contract: CandidateValidationContract,
    name: str,
) -> ValidationCheck:
    return next(check for check in contract.checks if check.name == name)


def _pod_ready(pod: Any) -> bool:
    status = getattr(pod, "status", None)
    return any(
        getattr(condition, "type", None) == "Ready"
        and str(getattr(condition, "status", None)).lower() == "true"
        for condition in getattr(status, "conditions", None) or []
    )


def _pod_node(pod: Any) -> str | None:
    return getattr(getattr(pod, "spec", None), "node_name", None) if pod else None


def _pod_name(pod: Any) -> str | None:
    return getattr(getattr(pod, "metadata", None), "name", None) if pod else None


def _pod_ip(pod: Any) -> str | None:
    return getattr(getattr(pod, "status", None), "pod_ip", None) if pod else None


def _pod_plan_matches(pod: Any, plan_id: str) -> bool:
    labels = getattr(getattr(pod, "metadata", None), "labels", None) or {}
    return labels.get("edge-ai.io/execution-plan-id") == plan_id


def _pod_base_url(pod_ip: str | None, port: int) -> str:
    if not pod_ip:
        raise ValueError("Pod IP is required")
    host = f"[{pod_ip}]" if ":" in pod_ip else pod_ip
    return f"http://{host}:{port}"


def _label_selector(labels: dict[str, str]) -> str:
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _measurement(value: Any) -> str | int | float | bool | None:
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _notify(
    observer: ValidationObserver | None,
    result: CandidateValidationResult,
) -> None:
    if observer is None:
        return
    observed = observer(result.model_copy(deep=True))
    if isinstance(observed, Awaitable):
        await observed
