#!/usr/bin/env python3
"""Keyword/regex based docs-code consistency rules for the KubeEdge PoC docs.

The rules intentionally avoid LLM/API calls. They are conservative heuristics that
look for policy drift between operator-facing docs and the current state-aggregator
implementation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Callable, Iterable

STATUS_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}

DOC_FILES = [
    "docs/dashboard-information-structure.md",
    "docs/okdong-productivity-kpi.md",
    "docs/kagenti-operator-assistant.md",
    "docs/current-demo-path.md",
    "docs/device-service-binding.md",
    "docs/device-status-policy.md",
    "docs/service-demo-scenario.md",
    "docs/ops/runbook-current-demo.md",
]

CODE_FILES = [
    "edge-orch/state-aggregator/app/service.py",
    "edge-orch/state-aggregator/app/influx.py",
    "edge-orch/state-aggregator/app/static/dashboard.js",
    "edge-device/scripts/generate_devices.py",
    "mappers/script/test_device.py",
]


@dataclass
class Finding:
    rule: str
    status: str
    file: str
    line: int
    evidence: str
    message: str
    recommended_fix: str


@dataclass
class RuleResult:
    name: str
    status: str = "PASS"
    findings: list[Finding] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    recommended_fix: str = ""

    @property
    def matched_files(self) -> list[str]:
        files = {f.file for f in self.findings}
        for ev in self.evidence:
            if ":" in ev:
                files.add(ev.split(":", 1)[0])
        return sorted(files)

    def add_finding(self, finding: Finding) -> None:
        self.findings.append(finding)
        if STATUS_ORDER[finding.status] > STATUS_ORDER[self.status]:
            self.status = finding.status

    def add_evidence(self, file: str, line: int, text: str) -> None:
        self.evidence.append(f"{file}:{line}: {compact(text)}")


@dataclass
class Corpus:
    root: Path
    docs: dict[str, str]
    code: dict[str, str]


def compact(text: str, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def iter_lines(files: dict[str, str]) -> Iterable[tuple[str, int, str]]:
    for file, text in files.items():
        for idx, line in enumerate(text.splitlines(), 1):
            yield file, idx, line


def window_lines(text: str, line_no: int, before: int = 1, after: int = 1) -> str:
    lines = text.splitlines()
    start = max(0, line_no - 1 - before)
    end = min(len(lines), line_no + after)
    return "\n".join(lines[start:end])


def section_context(text: str, line_no: int, before: int = 12, after: int = 2) -> str:
    """Return nearby text plus the closest previous markdown heading.

    This keeps exclusion sections such as "현재 범위에서 제외" visible to scope rules
    without requiring a full markdown parser.
    """
    lines = text.splitlines()
    heading = ""
    for idx in range(max(0, line_no - 1), -1, -1):
        if lines[idx].lstrip().startswith("#"):
            heading = lines[idx]
            break
    return heading + "\n" + window_lines(text, line_no, before, after)


def has_any(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)


def add_code_evidence(result: RuleResult, corpus: Corpus, file: str, pattern: str, flags: int = re.I) -> None:
    text = corpus.code.get(file, "")
    for idx, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line, flags):
            result.add_evidence(file, idx, line)
            return


def make_finding(rule: str, status: str, file: str, line: int, evidence: str, message: str, fix: str) -> Finding:
    return Finding(rule=rule, status=status, file=file, line=line, evidence=compact(evidence), message=message, recommended_fix=fix)


RuleFn = Callable[[Corpus], RuleResult]


def rule_device_telemetry_ratio(corpus: Corpus) -> RuleResult:
    name = "R1 device_telemetry_ratio means telemetry configured ratio"
    fix = "`device_telemetry_ratio`는 telemetry_enabled device 수 / 전체 registered device 수이며 freshness 비율이 아니다. 최신성은 `telemetry_freshness_ratio`로 설명한다."
    result = RuleResult(name=name, recommended_fix=fix)
    bad = re.compile(r"device_telemetry_ratio.*(fresh|freshness|최신|최근|갱신|들어오|살아|live)", re.I)
    good = re.compile(r"device_telemetry_ratio.*(configured|설정|enabled|telemetry-enabled|대상|registered|전체|fresh 비율 아님|freshness 비율이 아니다)|telemetry_freshness_ratio", re.I)
    for file, line_no, line in iter_lines(corpus.docs):
        if "device_telemetry_ratio" not in line:
            continue
        ctx = line
        if bad.search(ctx) and not good.search(ctx):
            result.add_finding(make_finding(name, "FAIL", file, line_no, ctx, "device_telemetry_ratio를 telemetry freshness/live 비율처럼 설명합니다.", fix))
        elif good.search(ctx):
            result.add_evidence(file, line_no, line)
    add_code_evidence(result, corpus, "edge-orch/state-aggregator/app/service.py", r"device_telemetry_ratio|telemetry_devices")
    return result


def rule_telemetry_freshness_ratio(corpus: Corpus) -> RuleResult:
    name = "R2 telemetry freshness must use telemetry_freshness_ratio/fresh_telemetry_device_count"
    fix = "telemetry 최신성은 `fresh_telemetry_device_count`와 `telemetry_freshness_ratio`로 설명한다. `device_telemetry_ratio`와 같은 의미로 섞지 않는다."
    result = RuleResult(name=name, recommended_fix=fix)
    freshness = re.compile(r"(telemetry\s+freshness|fresh\s+telemetry|최신\s*telemetry|telemetry.*최신|실제\s+최신\s+telemetry|최근\s+telemetry)", re.I)
    required = re.compile(r"(telemetry_freshness_ratio|fresh_telemetry_device_count|telemetry_fresh\b)", re.I)
    ratio_confusion = re.compile(
        r"device_telemetry_ratio.{0,120}(fresh|freshness|최신|최근|갱신|들어오|살아|live)"
        r"|(fresh|freshness|최신|최근|갱신|들어오|살아|live).{0,120}device_telemetry_ratio",
        re.I,
    )
    separation = re.compile(r"(분리|별도|아니다|아님|not|configured|설정|enabled|대상|telemetry-enabled)", re.I)

    for file, text in corpus.docs.items():
        doc_has_required = bool(required.search(text))
        for line_no, line in enumerate(text.splitlines(), 1):
            if not freshness.search(line) and "device_telemetry_ratio" not in line:
                continue
            ctx = section_context(text, line_no, 8, 8)
            if ratio_confusion.search(ctx) and not (required.search(ctx) or separation.search(ctx)):
                result.add_finding(make_finding(name, "WARN", file, line_no, ctx, "device_telemetry_ratio와 telemetry freshness를 같은 의미로 설명할 수 있습니다.", fix))
            elif doc_has_required or required.search(ctx):
                result.add_evidence(file, line_no, line)
    add_code_evidence(result, corpus, "edge-orch/state-aggregator/app/service.py", r"fresh_telemetry_device_count|telemetry_freshness_ratio")
    return result


def rule_device_status_freshness(corpus: Corpus) -> RuleResult:
    name = "R3 DeviceStatus freshness is auxiliary, not required for healthy"
    fix = "DeviceStatus freshness는 status-plane 관찰용 보조 신호다. telemetry-enabled device는 InfluxDB latest telemetry가 fresh하면 DeviceStatus가 stale이어도 healthy일 수 있다고 설명한다."
    result = RuleResult(name=name, recommended_fix=fix)
    fail_patterns = [
        re.compile(r"DeviceStatus.*(healthy|정상).*필수", re.I),
        re.compile(r"DeviceStatus.*fresh.*(required|must|필수)", re.I),
        re.compile(r"DeviceStatus snapshot timestamp가 dashboard freshness 기준을 만족한다"),
    ]
    negation = re.compile(r"(필수 조건은? 아니다|필수 조건이 아니다|필수 조건은 아님|아님|보조 신호|stale이어도 healthy|막지 않는다|반드시 .*아님|not required)", re.I)
    good = re.compile(r"(DeviceStatus.*보조 신호|DeviceStatus.*healthy 필수 조건.*아님|DeviceStatus.*stale.*healthy|telemetry.*fresh.*DeviceStatus.*stale)", re.I)
    for file, line_no, line in iter_lines(corpus.docs):
        if "DeviceStatus" not in line:
            continue
        ctx = window_lines(corpus.docs[file], line_no, 1, 1)
        if any(p.search(ctx) for p in fail_patterns) and not negation.search(ctx):
            result.add_finding(make_finding(name, "FAIL", file, line_no, ctx, "DeviceStatus freshness를 healthy 필수 조건처럼 설명합니다.", fix))
        elif good.search(ctx):
            result.add_evidence(file, line_no, line)
    add_code_evidence(result, corpus, "edge-orch/state-aggregator/app/service.py", r"device_status_fresh|telemetry_fresh")
    return result


def rule_operator_focus_count(corpus: Corpus) -> RuleResult:
    name = "R4 operator_focus_count excludes workflow risk"
    fix = "`operator_focus_count`는 degraded/unavailable device 수 + non-healthy node 수로 설명한다. workflow/SLA risk는 현재 데모 범위 count에서 제외한다."
    result = RuleResult(name=name, recommended_fix=fix)
    for file, line_no, line in iter_lines(corpus.docs):
        if "operator_focus_count" not in line:
            continue
        ctx = window_lines(corpus.docs[file], line_no, 2, 2)
        low = ctx.lower()
        if ("workflow" in low or "sla" in low) and not re.search(r"(제외|포함하지|exclude|not include)", ctx, re.I):
            result.add_finding(make_finding(name, "FAIL", file, line_no, ctx, "operator_focus_count가 workflow/SLA risk를 포함하는 것처럼 보입니다.", fix))
        elif re.search(r"degraded/unavailable|non-healthy|비정상 node|workflow risk.*(제외|포함하지)", ctx, re.I):
            result.add_evidence(file, line_no, line)
    add_code_evidence(result, corpus, "edge-orch/state-aggregator/app/service.py", r"operator_focus_count|focus_nodes|focus_devices")
    return result


def rule_actuator_liveness(corpus: Corpus) -> RuleResult:
    name = "R5 act/rpi-act InfluxDB liveness uses health property, not ts"
    fix = "act/rpi-act의 현재 InfluxDB liveness row는 `health` property다. `ts`는 publisher payload에는 포함될 수 있지만 현재 Device manifest의 DB push property가 아니므로 dashboard freshness 기준으로 쓰지 않는다."
    result = RuleResult(name=name, recommended_fix=fix)
    bad = re.compile(r"(act|rpi-act|actuator).{0,120}(InfluxDB|DB|liveness|freshness).{0,120}`?ts`?|`?ts`?.{0,120}(liveness|freshness).{0,120}(act|rpi-act|actuator)", re.I)
    allowed = re.compile(r"(아니|not|현재 .*아니|후보|payload|DB push property가 아니|dashboard freshness 기준.*않)", re.I)
    good = re.compile(r"(act|rpi-act|actuator).{0,120}(health).{0,120}(liveness|InfluxDB|DB|freshness)|health.{0,80}liveness", re.I)
    for file, line_no, line in iter_lines(corpus.docs):
        ctx = window_lines(corpus.docs[file], line_no, 1, 1)
        if bad.search(ctx) and not allowed.search(ctx):
            result.add_finding(make_finding(name, "FAIL", file, line_no, ctx, "act/rpi-act liveness를 ts 기준으로 설명합니다.", fix))
        elif good.search(ctx):
            result.add_evidence(file, line_no, line)
    add_code_evidence(result, corpus, "edge-device/scripts/generate_devices.py", r"health|db_props|pushMethod")
    add_code_evidence(result, corpus, "mappers/script/test_device.py", r"\bts\b")
    return result


def rule_node_ready(corpus: Corpus) -> RuleResult:
    name = "R6 dashboard node_ready is not identical to Kubernetes Ready"
    fix = "dashboard `node_ready`는 Kubernetes Ready condition 자체가 아니라 state-aggregator가 Prometheus/node-exporter 기반 `node_health`를 보고 `unavailable`이 아니라고 판단한 값이라고 설명한다. Kubernetes Ready는 `kubectl get nodes` 기준으로 별도 표현한다."
    result = RuleResult(name=name, recommended_fix=fix)
    for file, line_no, line in iter_lines(corpus.docs):
        if "node_ready" not in line:
            continue
        ctx = window_lines(corpus.docs[file], line_no, 1, 1)
        if re.search(r"node_ready.*(Kubernetes\s*Ready|Ready condition|Ready 값|Ready 여부)", ctx, re.I) and not re.search(r"(구분|아니|not|기반|별도|unavailable)", ctx, re.I):
            result.add_finding(make_finding(name, "WARN", file, line_no, ctx, "dashboard node_ready를 Kubernetes Ready와 같은 값처럼 설명할 수 있습니다.", fix))
        elif re.search(r"node_ready.*(Prometheus|node-exporter|node_health|unavailable|구분|아니)", ctx, re.I):
            result.add_evidence(file, line_no, line)
    add_code_evidence(result, corpus, "edge-orch/state-aggregator/app/service.py", r"node_ready|node_health")
    return result


def rule_influx_timestamp_notes(corpus: Corpus) -> RuleResult:
    name = "R7 InfluxDB timestamp semantics are documented"
    fix = "InfluxDB latest 설명에는 `_start/_stop`은 Flux query window, `_time`은 실제 sample timestamp, `telemetry_fresh`는 device-level latest sample 기준, property별 latest freshness를 보장하지 않는다는 문구를 넣는다."
    result = RuleResult(name=name, recommended_fix=fix)
    required = [
        ("_start/_stop query window", re.compile(r"_start.*_stop.*(window|윈도우|조회 범위|query)", re.I)),
        ("_time sample timestamp", re.compile(r"_time.*(sample|telemetry|timestamp|시각)", re.I)),
        ("device-level latest sample", re.compile(r"(device-level|device별).*latest.*sample|latest sample.*device", re.I)),
        ("not property-level freshness", re.compile(r"property별.*(보장하지|아니|not)|not.*property", re.I)),
    ]
    for file, text in corpus.docs.items():
        missing = [label for label, pat in required if not pat.search(text)]
        if missing:
            result.add_finding(make_finding(name, "WARN", file, 1, ", ".join(missing), "InfluxDB timestamp/freshness 의미 설명이 일부 빠졌습니다.", fix))
        else:
            for idx, line in enumerate(text.splitlines(), 1):
                if "_start" in line or "device-level latest" in line or "property별" in line:
                    result.add_evidence(file, idx, line)
                    break
    add_code_evidence(result, corpus, "edge-orch/state-aggregator/app/influx.py", r"_time|last\(|latest")
    return result


def rule_scope_current_implementation(corpus: Corpus) -> RuleResult:
    name = "R8 workflow/offloading/placement/autonomous agent are not current implementation scope"
    fix = "workflow/offloading/placement/agent autonomous control은 현재 구현 기능이 아니라 제외 범위, archive/legacy, 향후 확장 후보, 또는 read-only/dry-run 설계 도구로만 표현한다."
    result = RuleResult(name=name, recommended_fix=fix)
    risky_terms = re.compile(r"(workflow|offloading|placement|agent-assisted|autonomous|자율 제어|전역 제어|자동 배치|자동 재배치|runtime replanning)", re.I)
    current_claim = re.compile(r"(현재|current|구현|실행|동작|제공|완료|적용한다|사용한다|핵심)", re.I)
    allowed = re.compile(r"(제외|아니다|아니라|아니며|하지 않는다|목표가 아니다|archive|legacy|향후|후보|과거|보관|비교|Guardrail|하면 안 되는|범위에서 제외|호환|흔적|정리 전 이름|현재 이름|Workflow Designer|read-only|dry-run|설계|시각화|plan generation|실제 배포 없음)", re.I)
    for file, line_no, line in iter_lines(corpus.docs):
        if not risky_terms.search(line):
            continue
        ctx = section_context(corpus.docs[file], line_no, 12, 6)
        if current_claim.search(ctx) and not allowed.search(ctx):
            result.add_finding(make_finding(name, "FAIL", file, line_no, ctx, "현재 데모 범위 밖 기능을 현재 구현 기능처럼 설명할 수 있습니다.", fix))
        elif allowed.search(ctx):
            result.add_evidence(file, line_no, line)
    return result


RULES: list[RuleFn] = [
    rule_device_telemetry_ratio,
    rule_telemetry_freshness_ratio,
    rule_device_status_freshness,
    rule_operator_focus_count,
    rule_actuator_liveness,
    rule_node_ready,
    rule_influx_timestamp_notes,
    rule_scope_current_implementation,
]


def load_corpus(root: Path) -> Corpus:
    docs: dict[str, str] = {}
    code: dict[str, str] = {}
    for rel in DOC_FILES:
        path = root / rel
        docs[rel] = path.read_text(encoding="utf-8") if path.exists() else ""
    for rel in CODE_FILES:
        path = root / rel
        code[rel] = path.read_text(encoding="utf-8") if path.exists() else ""
    return Corpus(root=root, docs=docs, code=code)


def run_rules(corpus: Corpus) -> list[RuleResult]:
    return [rule(corpus) for rule in RULES]
