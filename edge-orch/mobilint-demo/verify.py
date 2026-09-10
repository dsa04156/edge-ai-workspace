"""Bounded real-NPU API verification. Usage: python3 verify.py URL OUTPUT.json."""
import concurrent.futures
import datetime
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def verify(base):
    def request(path, body=None):
        req = urllib.request.Request(base.rstrip('/') + path,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    code, status = request('/models')
    assert code == 200 and len(status['models']) == 2
    assert all(m['ready'] for m in status['models'])
    assert len({m['core'] for m in status['models']}) == 2
    singles = {}
    for name in ('candy', 'mosaic'):
        code, result = request('/infer/' + name, {'seed': 7})
        assert code == 200 and result['results'][0]['finite']
        code, repeated = request('/infer/' + name, {'seed': 7})
        assert code == 200
        assert result['results'][0]['output_sha256'] == repeated['results'][0]['output_sha256']
        singles[name] = result
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        calls = [pool.submit(request, '/infer/' + name, {'seed': 7, 'iterations': 20})
                 for name in ('candy', 'mosaic')]
        clients = [f.result() for f in calls]
    assert all(code == 200 for code, result in clients)
    code, parallel = request('/demo/parallel', {'seed': 7, 'iterations': 50})
    assert code == 200 and parallel['overlap_ms'] > 0
    for result in parallel['results']:
        assert result['output_sha256'] == singles[result['model']]['results'][0]['output_sha256']
    errors = {}
    for path, body, expected in [('/infer/candy', {'iterations': 51}, 400),
                                  ('/infer/candy', {'seed': True}, 400),
                                  ('/infer/candy', {'model_path': '/tmp/x'}, 400),
                                  ('/infer/unknown', {}, 404)]:
        code, result = request(path, body)
        assert code == expected, (code, result)
        errors[str(body)] = code
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        running = pool.submit(request, '/infer/candy', {'iterations': 50})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            _, state = request('/models')
            if any(m['id'] == 'candy' and m['busy'] for m in state['models']):
                break
            time.sleep(0.01)
        else:
            raise AssertionError('could not observe busy worker')
        code, result = request('/infer/candy', {})
        assert code == 409, (code, result)
        errors['busy'] = code
        assert running.result()[0] == 200
    return {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'endpoint': base, 'status': status, 'single': singles,
            'independent_clients': clients, 'parallel': parallel, 'errors': errors,
            'boundary': 'Synthetic fixture, actual SDK inference; overlap is host call timing, not kernel timing.'}


if __name__ == '__main__':
    result = verify(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'overlap_ms': result['parallel']['overlap_ms'],
                      'errors': result['errors']}, ensure_ascii=False))
