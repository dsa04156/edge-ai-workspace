"""Immutable service design revisions. Saving a definition never deploys workloads."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class StagePlan(StrictModel):
    stage_id: str = Field(min_length=1, max_length=128)
    model_id: str | None = Field(default=None, max_length=128)
    resource_profile: str | None = Field(default=None, max_length=256)
    preferred_node: str | None = Field(default=None, max_length=253)
    allowed_nodes: list[str] = Field(default_factory=list, max_length=100)
    cpu_request: float | None = Field(default=None, ge=0)
    memory_request_mib: float | None = Field(default=None, ge=0)
    architecture: str | None = Field(default=None, max_length=32)
    accelerator: str | None = Field(default=None, max_length=64)
    local_data_dependency: bool = False


class DesignRevision(StrictModel):
    service_id: str = Field(pattern=r'^[a-z0-9][a-z0-9.-]{0,62}$')
    version: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')
    design: dict[str, Any]
    stages: list[StagePlan] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def bounded_graph(self):
        if len(json.dumps(self.design, allow_nan=False).encode()) > 256_000:
            raise ValueError('design exceeds 256 KB')
        nodes, edges = self.design.get('nodes'), self.design.get('edges')
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100 or not isinstance(edges, list) or len(edges) > 500:
            raise ValueError('design requires 1..100 nodes and at most 500 edges')
        ids = [n.get('id') for n in nodes if isinstance(n, dict)]
        if len(ids) != len(nodes) or any(not isinstance(i, str) or not i or len(i) > 128 for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('unique stage IDs required')
        if any(n.get('type') not in ('sensor', 'preprocess', 'inference', 'fusion', 'output') or not isinstance(n.get('config'), dict) for n in nodes):
            raise ValueError('unsupported design node')
        if any(not isinstance(e, dict) or e.get('from') not in ids or e.get('to') not in ids for e in edges):
            raise ValueError('edge references missing node')
        plans = [s.stage_id for s in self.stages]
        if len(plans) != len(set(plans)) or any(i not in ids for i in plans):
            raise ValueError('stage plan identity mismatch')
        # This is an authoring contract, never a raw Kubernetes manifest or credential container.
        forbidden = {'token', 'password', 'secret', 'authorization', 'hostpath', 'command', 'manifest'}
        def inspect(value):
            if isinstance(value, dict):
                if any(str(k).lower() in forbidden for k in value):
                    raise ValueError('credentials and runtime mutation fields are not design data')
                for v in value.values(): inspect(v)
            elif isinstance(value, list):
                for v in value: inspect(v)
        inspect(self.design)
        return self


class DesignStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS designs(service_id TEXT, version TEXT, digest TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(service_id, version))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, revision):
        payload = revision.model_dump_json()
        digest = hashlib.sha256(json.dumps(revision.model_dump(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest FROM designs WHERE service_id=? AND version=?', (revision.service_id, revision.version)).fetchone()
            if row and row[0] != digest:
                raise HTTPException(409, 'Version is immutable; use a new service version')
            if not row:
                db.execute('INSERT INTO designs VALUES(?,?,?,?,?)', (revision.service_id, revision.version, digest, payload, datetime.now(timezone.utc).isoformat()))
        return self.get(revision.service_id, revision.version)

    def get(self, service_id, version):
        with self.connect() as db:
            row = db.execute('SELECT payload,digest,created_at FROM designs WHERE service_id=? AND version=?', (service_id, version)).fetchone()
        if not row: raise HTTPException(404, 'Design version not found')
        return {**json.loads(row[0]), 'digest': row[1], 'created_at': row[2], 'state': 'Configured',
                'deployment_state': 'NOT_APPLIED', 'source': 'platform SQLite design registry'}

    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT service_id,version,digest,created_at FROM designs ORDER BY created_at DESC LIMIT 200').fetchall()
        return [{'service_id': r[0], 'version': r[1], 'digest': r[2], 'created_at': r[3], 'state': 'Configured'} for r in rows]


def validate_revision(revision, devices, resources, models):
    nodes = {n['id']: n for n in revision.design['nodes']}
    edges = revision.design['edges']
    checks = []
    def check(code, status, stage=None):
        checks.append({'code': code, 'status': status, 'stage_id': stage})
    visiting, visited = set(), set()
    dependencies = {i: [] for i in nodes}
    for e in edges: dependencies[e['to']].append(e['from'])
    def visit(i):
        if i in visiting: return False
        if i in visited: return True
        visiting.add(i)
        if not all(visit(j) for j in dependencies[i]): return False
        visiting.remove(i); visited.add(i)
        return True
    check('dag_acyclic', 'READY' if all(visit(i) for i in nodes) else 'BLOCKED')
    by_device = {d['name']: d for d in devices or []}
    by_resource = {r['node']: r for r in resources or []}
    plans = {s.stage_id: s for s in revision.stages}
    output_types = {}
    latest_origins = []
    for sid, node in nodes.items():
        kind, config = node['type'], node['config']
        if kind == 'sensor':
            d = by_device.get(config.get('deviceName'), {})
            reading = next((r for r in d.get('latest_readings', []) if r.get('resource_name') == config.get('resourceName')), {})
            vt = str(reading.get('value_type', '')).lower()
            output_types[sid] = 'number' if vt.startswith(('int','uint','float')) else 'boolean' if vt == 'bool' else 'unknown'
            if reading.get('timestamp'):
                try:
                    latest_origins.append(datetime.fromisoformat(reading['timestamp'].replace('Z','+00:00')).timestamp())
                except (ValueError, TypeError):
                    check('invalid_timestamp', 'BLOCKED', sid)
        elif kind == 'preprocess':
            output_types[sid] = 'feature_vector' if config.get('operation') in ('vibration_features','window_features') else 'number'
        elif kind == 'inference':
            output_types[sid] = 'boolean' if config.get('algorithm') == 'threshold-rule-v1' else 'number'
        elif kind == 'fusion':
            output_types[sid] = 'number'
        else:
            output_types[sid] = 'any'
    if len(latest_origins) > 1:
        check('latest_origin_alignment_2000ms', 'READY' if (max(latest_origins)-min(latest_origins))*1000 <= 2000 else 'BLOCKED')
    for edge in edges:
        target = nodes[edge['to']]
        plan = plans.get(edge['to'])
        expected = 'any' if target['type'] in ('output','sensor') else 'number'
        if target['type'] == 'inference' and plan and plan.model_id in models:
            expected = models[plan.model_id]['input_contract']
        actual = output_types[edge['from']]
        if expected != 'any' and actual != expected:
            check('input_type_unobserved' if actual == 'unknown' else 'incompatible_data_type', 'BLOCKED', edge['to'])
    for sid, node in nodes.items():
        config = node['config']
        if node['type'] == 'sensor':
            d = by_device.get(config.get('deviceName'))
            check('device_observed', 'READY' if d else 'BLOCKED', sid)
            if d:
                reading = next((r for r in d.get('latest_readings', []) if r.get('resource_name') == config.get('resourceName')), None)
                check('resource_observed', 'READY' if reading else 'BLOCKED', sid)
                check('input_fresh', 'READY' if d.get('telemetry_freshness') == 'fresh' else 'BLOCKED', sid)
            # The latest Reading cannot prove an entire input window or alignment.
            check('sample_window_and_alignment_require_live_preflight', 'WARNING', sid)
        elif not dependencies[sid]:
            check('stage_input_missing', 'BLOCKED', sid)
        plan = plans.get(sid)
        if node['type'] == 'inference':
            check('model_contract_selected', 'READY' if plan and plan.model_id in models else 'BLOCKED', sid)
        if plan and plan.preferred_node:
            r = by_resource.get(plan.preferred_node)
            check('node_schedulable', 'READY' if r and r.get('schedulable') else 'BLOCKED', sid)
            if plan.allowed_nodes and plan.preferred_node not in plan.allowed_nodes:
                check('allowed_nodes_mismatch', 'BLOCKED', sid)
            if r:
                if plan.architecture and r.get('architecture') != plan.architecture:
                    check('architecture_mismatch', 'BLOCKED', sid)
                if plan.accelerator and r.get('accelerator') != plan.accelerator:
                    check('accelerator_mismatch', 'BLOCKED', sid)
                if plan.cpu_request is not None and (r.get('cpuAvailable') is None or r['cpuAvailable'] < plan.cpu_request):
                    check('insufficient_cpu', 'BLOCKED', sid)
                if plan.memory_request_mib is not None and (r.get('memoryAvailableGB') is None or r['memoryAvailableGB'] * 1e9 < plan.memory_request_mib * 1024**2):
                    check('insufficient_memory', 'BLOCKED', sid)
            if plan.local_data_dependency:
                upstream, pending = set(), list(dependencies[sid])
                while pending:
                    x = pending.pop()
                    if x in upstream: continue
                    upstream.add(x); pending.extend(dependencies[x])
                for x in upstream:
                    if nodes[x]['type'] == 'sensor':
                        d = by_device.get(nodes[x]['config'].get('deviceName'))
                        if not d or d.get('node_name') != plan.preferred_node:
                            check('local_data_requirement_mismatch', 'BLOCKED', sid)
        elif node['type'] != 'sensor':
            check('placement_not_selected', 'WARNING', sid)
    check('deployment_adapter_not_connected', 'BLOCKED')
    check('storage_and_model_runtime_readiness_not_verified', 'WARNING')
    return {'status': 'BLOCKED' if any(c['status'] == 'BLOCKED' for c in checks) else 'WARNING' if any(c['status'] == 'WARNING' for c in checks) else 'READY',
            'checks': checks, 'deployment_enabled': False, 'mode': 'plan_preview',
            'stages': [s.model_dump() for s in revision.stages], 'generated_at': datetime.now(timezone.utc).isoformat()}


def model_contracts(catalog):
    items = []
    for service in catalog.services:
        for kind in ('vibration', 'temperature'):
            algorithm = getattr(service.design_contract, f'{kind}_algorithm')
            items.append({'id': algorithm, 'name': algorithm, 'version': service.augmentation_qualification.source_model_version,
                          'model_type': 'statistical_baseline', 'backend': 'online-baseline',
                          'input_contract': 'feature_vector', 'output_contract': 'number',
                          'image': None, 'digest': None, 'supported_architecture': [], 'supported_accelerator': [],
                          'minimum_resource': None, 'recommended_resource': None, 'maximum_resource': None,
                          'model_load_time_ms': None, 'benchmark_history': [], 'state': 'Configured',
                          'source': catalog.source, 'service_id': service.service_id})
    return {item['id']: item for item in items}


def create_design_router(store, catalog, token, devices_reader, resources_reader):
    router = APIRouter()
    models = model_contracts(catalog)

    @router.get('/api/model-contracts')
    async def model_list():
        return {'items': list(models.values()), 'source': catalog.source, 'mode': 'configured_contracts'}

    @router.get('/api/service-designs')
    async def list_designs():
        return {'items': store.list(), 'write_enabled': bool(token), 'deployment_enabled': False}

    @router.get('/api/service-designs/{service_id}/{version}')
    async def get_design(service_id: str, version: str):
        return store.get(service_id, version)

    @router.post('/api/service-designs')
    async def save_design(revision: DesignRevision, authorization: str | None = Header(default=None)):
        if not token: raise HTTPException(503, 'Service design writes are disabled: management token is not configured')
        if not authorization or not hmac.compare_digest(authorization, 'Bearer ' + token):
            raise HTTPException(401, 'Management token required')
        return store.save(revision)

    @router.post('/api/service-designs/validate')
    async def validate_design(revision: DesignRevision):
        from .operations import plain
        errors = []
        try: devices = plain(await devices_reader())
        except Exception: devices = None; errors.append('device_observation_unavailable')
        try:
            resources = await resources_reader()
            resources = [r.model_dump(mode='json', by_alias=True) if isinstance(r, BaseModel) else r for r in resources]
        except Exception: resources = None; errors.append('resource_observation_unavailable')
        result = validate_revision(revision, devices, resources, models)
        result['observation_errors'] = errors
        return result

    return router
