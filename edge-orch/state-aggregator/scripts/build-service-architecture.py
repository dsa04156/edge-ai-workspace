#!/usr/bin/env python3
"""Export only diagram fields for the static, explicitly labelled Git preview."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
catalog = json.loads((ROOT / 'app/config/service_catalog.json').read_text())
workload = (ROOT.parent / 'sensor-anomaly-demo/k8s/workload.yaml').read_text()
source = re.search(r'name: SERVICE_DEVICE_ID\s+value: ([\w-]+)', workload)
services = []
for item in catalog['services']:
    descriptor = {key: item[key] for key in (
        'service_id', 'display_name', 'description', 'workload', 'input_contract',
        'graph', 'design_contract',
    ) if key in item}
    # No endpoints, credentials, control APIs, or qualification claims in the asset.
    service = {'service_id': item['service_id'], 'descriptor': descriptor}
    if item.get('runtime_offloading', {}).get('target_workload'):
        descriptor['runtime_offloading'] = {'target_workload': item['runtime_offloading']['target_workload']}
    if item['service_id'] == 'sensor-anomaly-demo' and source:
        service['physical_source'] = source.group(1)
    services.append(service)
output = ROOT / 'app/static/nexus/service-architecture.json'
output.write_text(json.dumps({
    'version': catalog['version'],
    'definition_source': 'app/config/service_catalog.json',
    'services': services,
}, ensure_ascii=False, indent=2) + '\n')
print(f'{output.relative_to(ROOT)}: {len(services)} service contracts')
