import gzip, hashlib, io, json, subprocess, tarfile, urllib.request
from pathlib import Path

REG = 'http://192.168.0.56:5000'
ROOT = Path(__file__).resolve().parents[4]
JOBS = {'runtime-operator': {
 'base': 'sha256:e7af71fa425422d5d7576c9dc0e1903d0cd6f50225fc181438474ae55c481670',
 'prefix': 'edge-orch/runtime-operator/runtime_operator/', 'dest': 'opt/runtime/runtime_operator/',
 'files': ['api.py', 'contract.py', 'journal.py', 'common_ai.py'],
 'hashes': ['79afbf679f90b54e3d72968d8b7bf2af44d953753fb1f9cf139344f1df8c6d52',
 'dfaff873fb2e52d43cecc2ace1cdf3066ab7632735dede9d4e1ef539a601cf79',
 '228d6c8cc4448fbbbdd062219ed779324917e94d03f43b449ae73d427dfb6689']}}

def request(path, data=None, method=None, headers=None):
    return urllib.request.urlopen(urllib.request.Request(path if path.startswith('http') else REG + path,
        data=data, method=method, headers=headers or {}), timeout=30)

def digest(data): return 'sha256:' + hashlib.sha256(data).hexdigest()

def upload(repo, data):
    d = digest(data)
    with request('/v2/' + repo + '/blobs/uploads/', b'', 'POST') as r: location = r.headers['Location']
    location += ('&' if '?' in location else '?') + 'digest=' + d
    with request(location, data, 'PUT', {'Content-Type': 'application/octet-stream'}) as r: assert r.status == 201
    return d

results = {}
for repo, job in JOBS.items():
    for name, expected in zip(job['files'], job['hashes']):
        original = subprocess.check_output(['git', 'show', 'd6f40257:' + job['prefix'] + name], cwd=ROOT)
        assert hashlib.sha256(original).hexdigest() == expected, name
    with request('/v2/' + repo + '/manifests/' + job['base'], headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json'}) as r:
        raw = r.read()
    assert digest(raw) == job['base']
    manifest = json.loads(raw)
    with request('/v2/' + repo + '/blobs/' + manifest['config']['digest']) as r: config = json.load(r)
    buffer = io.BytesIO()
    hashes = {}
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name in job['files']:
            content = (ROOT / (job['prefix'] + name)).read_bytes()
            item = tarfile.TarInfo(job['dest'] + name)
            item.size, item.mode = len(content), 0o644
            archive.addfile(item, io.BytesIO(content))
            hashes[name] = hashlib.sha256(content).hexdigest()
    layer_raw = buffer.getvalue()
    layer = gzip.compress(layer_raw, mtime=0)
    layer_digest = upload(repo, layer)
    config['rootfs']['diff_ids'].append(digest(layer_raw))
    config.setdefault('history', []).append({'created_by': 'Common AI envelope and existing journal integration'})
    config_raw = json.dumps(config, separators=(',', ':')).encode()
    manifest['config'].update(digest=upload(repo, config_raw), size=len(config_raw))
    manifest['layers'].append({'mediaType': manifest['layers'][-1]['mediaType'], 'size': len(layer), 'digest': layer_digest})
    encoded = json.dumps(manifest, separators=(',', ':')).encode()
    image_digest = digest(encoded)
    with request('/v2/' + repo + '/manifests/edgex-common-ai-20260914-v1', encoded, 'PUT', {'Content-Type': manifest['mediaType']}) as r:
        assert r.headers['Docker-Content-Digest'] == image_digest
    results[repo] = {'baseImage': '192.168.0.56:5000/' + repo + '@' + job['base'], 'image': '192.168.0.56:5000/' + repo + '@' + image_digest, 'files': hashes}
Path(__file__).with_name('rebuilt-image.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results, indent=2))
