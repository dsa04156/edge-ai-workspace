"""Recorded benchmark evidence, distinct from live metrics and official KPI certification."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from .design_registry import StrictModel


class BenchmarkRecord(StrictModel):
    test_id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$')
    timestamp: datetime
    git_commit: str = Field(pattern=r'^[0-9a-f]{40}$')
    image_digest: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    model_name: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    runtime: str = Field(min_length=1, max_length=128)
    node: str = Field(min_length=1, max_length=253)
    environment: Literal['physical_testbed', 'simulator', 'replay', 'substitute_hardware']
    input_digest: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    workload: str = Field(min_length=1, max_length=256)
    policy_version: str = Field(min_length=1, max_length=128)
    resource_configuration: dict[str, float | str] = Field(max_length=32)
    raw_latency_ms: list[float] = Field(min_length=2, max_length=10000)
    duration_seconds: float = Field(gt=0)
    completed_requests: int = Field(ge=0)
    error_count: int = Field(ge=0)
    load_time_ms: float | None = Field(default=None, ge=0)
    ttft_ms: float | None = Field(default=None, ge=0)
    tokens_per_second: float | None = Field(default=None, ge=0)
    power_watts: float | None = Field(default=None, ge=0)
    measurement_boundary: str = Field(min_length=1, max_length=256)
    evidence: str = Field(min_length=1, max_length=512)


def summarize(record):
    samples = sorted(record['raw_latency_ms'])
    return {**record, 'latency_ms': sum(samples)/len(samples),
            'p95_latency_ms': samples[max(0, math.ceil(len(samples)*.95)-1)],
            'throughput_per_second': record['completed_requests']/record['duration_seconds'],
            'sample_count': len(samples), 'state': 'RECORDED', 'official_kpi': False}


def compare(before, after):
    # Hardware/resources may differ, but measured workload, software and boundary must match.
    keys = ['git_commit','image_digest','model_name','model_version','runtime','environment','input_digest',
            'workload','policy_version','measurement_boundary','duration_seconds','sample_count']
    mismatches = [k for k in keys if before.get(k) != after.get(k)]
    if before['test_id'] == after['test_id']: mismatches.append('same_test')
    if before['error_count'] or after['error_count']: mismatches.append('errors_present')
    if before['p95_latency_ms'] <= 0: mismatches.append('nonpositive_baseline')
    return {'before_test_id': before['test_id'], 'after_test_id': after['test_id'],
            'status': 'NOT_COMPARABLE' if mismatches else 'COMPARABLE', 'mismatches': mismatches,
            'p95_improvement_percent': None if mismatches else (before['p95_latency_ms']-after['p95_latency_ms'])/before['p95_latency_ms']*100,
            'before': before, 'after': after, 'official_kpi': False,
            'scope': 'recorded matching benchmark conditions, not proof of a live offloading operation'}


class BenchmarkStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS benchmarks(test_id TEXT PRIMARY KEY,payload TEXT NOT NULL,digest TEXT NOT NULL)')

    def connect(self):return sqlite3.connect(self.path,timeout=10)

    def save(self, record):
        if record.timestamp.tzinfo is None or any(v<0 or not math.isfinite(v) for v in record.raw_latency_ms):
            raise HTTPException(422,'Timezone and finite nonnegative raw latency measurements required')
        if len(record.raw_latency_ms) != record.completed_requests:
            raise HTTPException(422,'Raw latency sample count must equal completed requests')
        payload=record.model_dump_json();digest=hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT digest FROM benchmarks WHERE test_id=?',(record.test_id,)).fetchone()
            if row and row[0]!=digest:raise HTTPException(409,'Test identity is immutable')
            if not row:db.execute('INSERT INTO benchmarks VALUES(?,?,?)',(record.test_id,payload,digest))
        return self.get(record.test_id)

    def get(self,test_id):
        with self.connect() as db:row=db.execute('SELECT payload,digest FROM benchmarks WHERE test_id=?',(test_id,)).fetchone()
        if not row:raise HTTPException(404,'Benchmark not found')
        return {**summarize(json.loads(row[0])),'record_digest':row[1]}

    def list(self):
        with self.connect() as db:rows=db.execute('SELECT payload,digest FROM benchmarks ORDER BY rowid DESC LIMIT 100').fetchall()
        return [{**summarize(json.loads(r[0])),'record_digest':r[1]} for r in rows]


def create_benchmark_router(store,token):
    router=APIRouter()
    @router.get('/api/benchmarks')
    async def listing():return {'items':store.list(),'mode':'recorded_evidence','official_kpi':False}
    @router.get('/api/benchmarks/compare')
    async def comparison(before:str,after:str):return compare(store.get(before),store.get(after))
    @router.post('/api/benchmarks')
    async def record(body:BenchmarkRecord,authorization:str|None=Header(default=None)):
        if not token:raise HTTPException(503,'Benchmark writes disabled')
        if not authorization or not hmac.compare_digest(authorization,'Bearer '+token):raise HTTPException(401,'Management token required')
        return store.save(body)
    return router
