#!/usr/bin/env node
const assert = require('assert');
const { buildComposerPayload, composerAssetOptions, defaultComposerAssetKeys } = require('../edge-orch/state-aggregator/app/static/dashboard.js');

const payload = buildComposerPayload({
  objective: 'Sense HAT 상태 분석',
  agent_role: 'device_troubleshooter',
  context_sources: ['/state/dashboard', '/state/devices', '/state/dashboard'],
  target_assets: [
    { type: 'device', id: 'env-sensehat-humidity-01', label: 'Sense HAT humidity' },
    { type: 'invalid', id: 'bad-tool', label: 'bad' },
  ],
  allowed_readonly_tools: ['state_api_read', 'kubectl_apply', 'telemetry_history_read'],
  ordered_steps: ['KPI 확인', 'telemetry freshness 확인'],
});

assert.strictEqual(payload.objective, 'Sense HAT 상태 분석');
assert.strictEqual(payload.agent_role, 'device_troubleshooter');
assert.deepStrictEqual(payload.context_sources, ['/state/dashboard', '/state/devices']);
assert.deepStrictEqual(payload.allowed_readonly_tools, ['state_api_read', 'telemetry_history_read']);
assert.strictEqual(payload.target_assets.length, 1);
assert.strictEqual(payload.target_assets[0].id, 'env-sensehat-humidity-01');
assert.deepStrictEqual(payload.ordered_steps, [
  { order: 1, title: 'KPI 확인' },
  { order: 2, title: 'telemetry freshness 확인' },
]);

const options = composerAssetOptions({
  nodes: [
    { hostname: '192.168.0.6:9100', node_health: 'unavailable', node_type: 'edge_light_device' },
    { hostname: 'etri-dev0003-raspi5', node_health: 'healthy', node_type: 'edge_light_device' },
  ],
  devices: [
    { name: 'env-sensehat-humidity-01', overall_status: 'available', node_name: 'etri-dev0003-raspi5', telemetry_fresh: true, mapper_running: true },
    { name: 'env-arduino-temperature-01', overall_status: 'degraded', node_name: 'etri-dev0001-jetorn', telemetry_fresh: false, mapper_running: true },
  ],
  resource_profiles: {
    service_resource_profiles: [
      { namespace: 'default', service: 'state-aggregator', pod_count: 1, container_count: 1, resource_requirements: { missing: { cpu_request_containers: 1 } } },
    ],
  },
  kpis: { telemetry_freshness_ratio: 0.6, sensor_data_freshness_ratio: 0.6, registered_device_count: 10, service_resource_profile_count: 16 },
});

assert(options.some((item) => item.type === 'node' && item.id === 'Unmapped node 1'));
assert(options.some((item) => item.type === 'device' && item.id === 'env-arduino-temperature-01' && item.preferred));
assert(options.some((item) => item.type === 'service' && item.id === 'default/state-aggregator'));
assert(options.some((item) => item.type === 'kpi' && item.id === 'telemetry_freshness_ratio'));
assert(defaultComposerAssetKeys(options).length > 0);

console.log('PASS dashboard composer payload and asset helpers');
