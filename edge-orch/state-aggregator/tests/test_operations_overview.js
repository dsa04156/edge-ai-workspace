const test = require("node:test");
const assert = require("node:assert/strict");
const {buildOverviewModel, attentionMarkup} = require("../app/static/operations-overview.js");
const {canonicalDashboardPage} = require("../app/static/navigation.js");
const {connectionCards, filterTwins, serviceMarkup} = require("../app/static/device-twins.js");

function snapshot() {
  return {
    dashboard: {
      devices: [
        {name: "temperature", physical_device_id: "arduino-001", overall_status: "degraded", telemetry_freshness: "stale", connection_state: "connected"},
        {name: "acceleration", physical_device_id: "arduino-001", overall_status: "unavailable", telemetry_freshness: "no_events", connection_state: "disconnected"},
        {name: "humidity", physical_device_id: "sensehat-001", overall_status: "available", telemetry_freshness: "fresh", connection_state: "connected"},
        {name: "unassigned", overall_status: "available", telemetry_freshness: "fresh", connection_state: "connected"},
      ],
      nodes: [{hostname: "server", node_type: "cloud_server", node_health: "unavailable"}, {hostname: "edge", node_type: "edge_device", node_health: "healthy"}],
    },
    twins: {observation_errors: [], twins: [
      {name: "temperature", health: "degraded", service_bindings: [{service_id: "s1", service_name: "서비스 1"}, {service_id: "s2", service_name: "서비스 2"}]},
      {name: "acceleration", health: "unavailable", service_bindings: [{service_id: "s1", service_name: "서비스 1"}]},
    ]},
  };
}

test("overview deduplicates source and impacted services while keeping nodes separate", () => {
  const model = buildOverviewModel(snapshot());
  assert.equal(model.sourceCount, 2);
  assert.equal(model.unknownSourceCount, 1);
  assert.equal(model.attentionCount, 2);
  assert.equal(model.impactCount, 2);
  assert.equal(model.edgeNodes.length, 1);
  assert.equal(model.servers.length, 1);
  assert.equal(model.nodeAttention.length, 1);
});
test("node failure does not turn a fresh connected sensor into an input failure", () => {
  const data = snapshot();
  data.dashboard.devices = [data.dashboard.devices[2]];
  const model = buildOverviewModel(data);
  assert.equal(model.attentionCount, 0);
  assert.equal(model.nodeAttention.length, 1);
});
test("an unassigned attention device outside the twin projection is not assumed unbound", () => {
  const data = snapshot();
  data.dashboard.devices.push({name: "no-source", overall_status: "unavailable"});
  const model = buildOverviewModel(data);
  assert.equal(model.attentionCount, 3);
  assert.equal(model.impactCount, null);
  assert.match(attentionMarkup(model, data), /연결 근거 미확인/);
});
test("EdgeX failure shows unknown counts while retaining node observations", () => {
  const data = snapshot();
  data.dashboard.device_observation_error = "EdgeX unavailable";
  const model = buildOverviewModel(data);
  assert.equal(model.attentionCount, null);
  assert.equal(model.sourceCount, null);
  assert.equal(model.impactCount, null);
  assert.equal(model.nodesKnown, true);
  assert.match(attentionMarkup(model, data), /관측 불가/);
  assert.doesNotMatch(attentionMarkup(model, data), /점검 대상이 없습니다/);
});
test("service observation failure never becomes zero impacted services or unbound", () => {
  const data = snapshot();
  data.twins.observation_errors = ["AI service observation unavailable"];
  const model = buildOverviewModel(data);
  assert.equal(model.attentionCount, 2);
  assert.equal(model.impactCount, null);
  assert.match(serviceMarkup([], {bindingsKnown: false}), /관측 불가/);
  assert.doesNotMatch(serviceMarkup([], {bindingsKnown: false}), /미연결/);
});
test("failed refresh does not treat last successful snapshots as current", () => {
  const data = {...snapshot(), dashboardError: "network", twinsError: "timeout"};
  const model = buildOverviewModel(data);
  assert.equal(model.sourceCount, null);
  assert.equal(model.impactCount, null);
  assert.equal(model.nodesKnown, false);
  assert.ok(data.dashboard.devices.length);
});
test("loading, successful empty inventory and failure have different meanings", () => {
  assert.equal(buildOverviewModel().attentionCount, null);
  const data = {dashboard: {devices: [], nodes: []}, twins: {twins: []}};
  assert.equal(buildOverviewModel(data).attentionCount, 0);
  assert.match(attentionMarkup(buildOverviewModel(data), data), /등록 디바이스 없음/);
  assert.doesNotMatch(attentionMarkup(buildOverviewModel(data), data), /모든.*정상/);
});
test("connections filter by health without altering N:M bindings and escape API strings", () => {
  const twins = snapshot().twins.twins;
  assert.equal(filterTwins(twins, {health: "attention"}).length, 2);
  assert.equal(filterTwins(twins, {health: "ready"}).length, 0);
  const markup = connectionCards([{...twins[0], name: '\"><img src=x onerror=alert(1)>', physical_device_id: "<script>bad</script>"}]);
  assert.match(markup, /서비스 1/);
  assert.match(markup, /서비스 2/);
  assert.doesNotMatch(markup, /<script>|<img/);
  assert.match(markup, /&lt;script&gt;/);
});
test("old bookmarks resolve to active new workspaces", () => {
  assert.equal(canonicalDashboardPage("inventory"), "connections");
  assert.equal(canonicalDashboardPage("device-twins"), "connections");
  assert.equal(canonicalDashboardPage("services"), "operations");
  assert.equal(canonicalDashboardPage("nodes"), "nodes");
  assert.equal(canonicalDashboardPage("bogus"), "overview");
  assert.equal(canonicalDashboardPage("virtual-devices"), "virtual-devices");
});
