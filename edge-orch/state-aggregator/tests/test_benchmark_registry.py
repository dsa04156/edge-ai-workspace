from datetime import datetime,timezone
import pytest
from fastapi import HTTPException
from app.benchmark_registry import BenchmarkRecord,BenchmarkStore,compare


def record(**kwargs):
    return BenchmarkRecord(test_id=kwargs.pop('test_id','test-1'),timestamp=datetime.now(timezone.utc),
        git_commit='a'*40,image_digest='sha256:'+'b'*64,model_name='baseline',model_version='1',
        runtime='runtime-1',node='edge-node',environment='physical_testbed',input_digest='sha256:'+'c'*64,
        workload='2 requests fixed input',policy_version='1',resource_configuration={'cpu':1},
        raw_latency_ms=kwargs.pop('raw_latency_ms',[100,200]),duration_seconds=1,completed_requests=2,
        error_count=0,measurement_boundary='request start to response end',evidence='test artifact',**kwargs)


def test_actual_samples_define_statistics_and_persist(tmp_path):
    store=BenchmarkStore(tmp_path/'db');one=store.save(record())
    assert one['p95_latency_ms']==200
    assert one['latency_ms']==150
    assert one['official_kpi'] is False
    assert BenchmarkStore(tmp_path/'db').get('test-1')==one
    two=store.save(record(test_id='test-2',raw_latency_ms=[50,100]))
    assert compare(one,two)['p95_improvement_percent']==50
    two['input_digest']='different'
    result=compare(one,two)
    assert result['status']=='NOT_COMPARABLE'
    assert result['p95_improvement_percent'] is None


def test_invalid_raw_metrics_and_changed_test_identity_rejected(tmp_path):
    store=BenchmarkStore(tmp_path/'db')
    with pytest.raises(HTTPException):store.save(record(raw_latency_ms=[-1,3]))
    first=record();store.save(first);assert store.save(first)['test_id']=='test-1'
    with pytest.raises(HTTPException) as exc:store.save(record(raw_latency_ms=[1,2]))
    assert exc.value.status_code==409
