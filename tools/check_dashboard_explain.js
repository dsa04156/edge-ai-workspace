#!/usr/bin/env node
const assert = require('assert');
const { explainDeviceRules, explainKpi, issueExplanation, renderTelemetryChart } = require('../edge-orch/state-aggregator/app/static/dashboard.js');

function ruleIds(device) {
  return explainDeviceRules(device).map((rule) => rule.id);
}

const baseDevice = {
  name: 'mock-device',
  status: 'healthy',
  overall_status: 'healthy',
  telemetry_enabled: true,
  telemetry_fresh: true,
  device_status_fresh: true,
  mapper_running: true,
  node_ready: true,
  service_connected: true,
};

const cases = [
  {
    name: 'healthy + telemetry_fresh=true + device_status_fresh=false',
    device: { ...baseDevice, device_status_fresh: false },
    expected: ['Sensor OK'],
  },
  {
    name: 'degraded + telemetry_fresh=false',
    device: { ...baseDevice, status: 'degraded', overall_status: 'degraded', telemetry_fresh: false },
    expected: ['Sensor Stale'],
  },
  {
    name: 'mapper_running=false',
    device: { ...baseDevice, mapper_running: false },
    expected: ['Mapper'],
  },
  {
    name: 'node_ready=false',
    device: { ...baseDevice, node_ready: false },
    expected: ['Node'],
  },
  {
    name: 'severity=critical',
    device: { ...baseDevice, status: 'degraded', overall_status: 'degraded', severity: 'critical' },
    expected: ['Severity'],
  },
  {
    name: 'service_connected=false',
    device: { ...baseDevice, service_connected: false },
    expected: ['Service'],
  },
];

for (const item of cases) {
  const actual = ruleIds(item.device);
  for (const expected of item.expected) {
    assert(actual.includes(expected), `${item.name}: missing ${expected}; got ${actual.join(', ')}`);
  }
}

const kpi = explainKpi('device_telemetry_ratio', { device_telemetry_ratio: 0.75 });
assert(kpi.text.includes('센서 데이터 적재가 설정된 device 비율'));
assert.strictEqual(kpi.value, 0.75);

const issueMessages = issueExplanation({ kind: 'device', device: { ...baseDevice, telemetry_fresh: false } });
assert(issueMessages.join('\n').includes('센서 데이터가 stale'));

const chart = renderTelemetryChart([
  { timestamp: '2026-06-22T07:00:00Z', property: 'temperature', value: '24.2' },
  { timestamp: '2026-06-22T07:01:00Z', property: 'temperature', value: '24.8' },
  { timestamp: '2026-06-22T07:02:00Z', property: 'temperature', value: '25.1' },
  { timestamp: '2026-06-22T07:00:00Z', property: 'humidity', value: '45.0' },
  { timestamp: '2026-06-22T07:01:00Z', property: 'humidity', value: '46.5' },
  { timestamp: '2026-06-22T07:02:00Z', property: 'humidity', value: '47.0' },
]);
assert(chart.includes('telemetry-summary-strip'), 'chart should expose summary stats above the plot');
assert(chart.includes('chart-gridline'), 'chart should render gridlines for scanability');
assert(chart.includes('chart-tick'), 'chart should render y-axis tick labels');
assert(chart.includes('chart-area'), 'chart should render an area layer under each line');
assert(chart.includes('chart-latest-marker'), 'chart should highlight the latest value per series');
assert(chart.includes('Latest'), 'chart summary should label the latest value');

console.log(`PASS dashboard explain rules: ${cases.length} mock cases`);
