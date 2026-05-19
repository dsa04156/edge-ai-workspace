#!/usr/bin/env node
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const designer = require(path.join('..', 'edge-orch', 'workflow-designer', 'workflow-designer.js'));
const html = fs.readFileSync(path.join(__dirname, '..', 'edge-orch', 'workflow-designer', 'index.html'), 'utf8');

const {
  EXAMPLE_WORKFLOWS,
  COMPUTE_NODES,
  PLATFORM_ENDPOINTS,
  INPUT_DEVICES,
  buildExecutionPlan,
  validateWorkflowPlan,
  applyStagePlacement,
  buildWorkflowDagModel,
  buildPlacementModel,
  buildTransportModel,
  rectanglesOverlap,
  selectStageForPlacement,
  assignSelectedStageToNode,
} = designer;

assert(EXAMPLE_WORKFLOWS['factory-anomaly-detection'], 'factory anomaly example must be exported');
assert(EXAMPLE_WORKFLOWS['environment-monitoring'], 'environment monitoring example must be exported');
assert(EXAMPLE_WORKFLOWS['actuator-command-monitoring'], 'actuator command monitoring example must be exported');
assert(COMPUTE_NODES.some((node) => node.kind === 'compute'), 'compute nodes must be separated from endpoints');
assert(PLATFORM_ENDPOINTS.some((endpoint) => endpoint.name === 'MQTT Broker'), 'MQTT Broker endpoint must exist');
assert(PLATFORM_ENDPOINTS.some((endpoint) => endpoint.name === 'InfluxDB'), 'InfluxDB endpoint must exist');
assert(PLATFORM_ENDPOINTS.some((endpoint) => endpoint.name === 'State Aggregator'), 'State Aggregator endpoint must exist');
assert(PLATFORM_ENDPOINTS.some((endpoint) => endpoint.name === 'Dashboard'), 'Dashboard endpoint must exist');
assert(INPUT_DEVICES.some((device) => device.name === 'vib-device-01'), 'input devices must be modeled separately');

const factory = JSON.parse(JSON.stringify(EXAMPLE_WORKFLOWS['factory-anomaly-detection']));
assert(Array.isArray(factory.edges) && factory.edges.some((edge) => edge.data === 'feature-vector' && edge.from === 'preprocess' && edge.to === 'inference'), 'factory workflow must include explicit data edges');
assert(Array.isArray(factory.placements) && factory.placements.some((item) => item.stage === 'inference'), 'factory workflow must include placements');
assert(Array.isArray(factory.endpoints) && factory.endpoints.includes('Dashboard'), 'factory workflow must include endpoints');
assert(Array.isArray(factory.transports) && factory.transports.some((item) => item.consumer === 'Dashboard'), 'factory workflow must include endpoint transports');

let plan = buildExecutionPlan(factory);
assert.strictEqual(plan.serviceName, 'factory-anomaly-detection');
assert.strictEqual(plan.mode, 'dry-run');
assert(Array.isArray(plan.stages) && plan.stages.some((stage) => stage.stage === 'inference'), 'plan must include logical stages');
assert(Array.isArray(plan.edges) && plan.edges.some((edge) => edge.data === 'feature-vector'), 'plan must include data edges');
assert(Array.isArray(plan.placements) && plan.placements.some((placement) => placement.stage === 'inference' && placement.targetNode), 'plan must include stage placements');
assert(Array.isArray(plan.transports) && plan.transports.some((transport) => transport.endpoint === 'MQTT Broker'), 'plan must include endpoint transports');

let validation = validateWorkflowPlan(factory, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'PASS'), 'valid factory example should include PASS');
assert(!validation.results.some((item) => item.level === 'FAIL'), 'valid factory example should not include FAIL');

const moved = applyStagePlacement(factory, 'inference', 'etri-dev0002-raspi5');
assert.strictEqual(moved.placements.find((item) => item.stage === 'inference').targetNode, 'etri-dev0002-raspi5');
validation = validateWorkflowPlan(moved, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'WARN' && item.message.includes('Raspberry Pi')), 'heavy inference on Raspberry Pi should warn');

const missingTarget = JSON.parse(JSON.stringify(factory));
missingTarget.placements = missingTarget.placements.filter((item) => item.stage !== 'collect');
validation = validateWorkflowPlan(missingTarget, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'FAIL' && item.message.includes('target node')), 'missing placement should fail');

const unknownEdge = JSON.parse(JSON.stringify(factory));
unknownEdge.edges.push({ from: 'preprocess', to: 'missing-stage', data: 'bad-data', transport: 'http' });
validation = validateWorkflowPlan(unknownEdge, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'FAIL' && item.message.includes('producer/consumer')), 'unknown edge consumer should fail');

const brokenTransport = JSON.parse(JSON.stringify(factory));
brokenTransport.transports = brokenTransport.transports.filter((item) => item.data !== 'mqtt-event');
validation = validateWorkflowPlan(brokenTransport, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'FAIL' && item.message.includes('MQTT Broker')), 'event-publish without MQTT transport should fail');

const noDashboard = JSON.parse(JSON.stringify(factory));
noDashboard.transports = noDashboard.transports.filter((item) => item.consumer !== 'Dashboard');
validation = validateWorkflowPlan(noDashboard, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'WARN' && item.message.includes('dashboard sink')), 'missing dashboard sink should warn');

const noInputs = JSON.parse(JSON.stringify(factory));
noInputs.inputDevices = [];
validation = validateWorkflowPlan(noInputs, COMPUTE_NODES, PLATFORM_ENDPOINTS, INPUT_DEVICES);
assert(validation.results.some((item) => item.level === 'WARN' && item.message.includes('input device')), 'service with no input device should warn');

const dag = buildWorkflowDagModel(factory);
assert(dag.nodes.some((node) => node.id === 'device:vib-device-01' && node.kind === 'device'), 'DAG must include input device node');
assert(dag.nodes.some((node) => node.id === 'stage:inference' && node.type === 'ai-inference'), 'DAG must include logical stage nodes');
assert(dag.nodes.some((node) => node.id === 'endpoint:Dashboard' && node.kind === 'endpoint'), 'DAG must include endpoint nodes');
assert(dag.edges.some((edge) => edge.data === 'feature-vector' && edge.from === 'stage:preprocess' && edge.to === 'stage:inference'), 'DAG edges must label data names');
assert(dag.edges.some((edge) => edge.data === 'mqtt-event' && edge.to === 'endpoint:Dashboard'), 'DAG must show endpoint sink edge');
for (let i = 0; i < dag.nodes.length; i += 1) {
  for (let j = i + 1; j < dag.nodes.length; j += 1) {
    assert(!rectanglesOverlap(dag.nodes[i], dag.nodes[j], 18), `DAG nodes must not overlap: ${dag.nodes[i].id} / ${dag.nodes[j].id}`);
  }
}
assert(dag.nodes.every((node) => node.width >= 190 && node.height >= 88), 'DAG nodes must expose stable dimensions for layout');

const selectedState = { selectedStage: '' };
selectStageForPlacement(selectedState, 'inference');
assert.strictEqual(selectedState.selectedStage, 'inference', 'click selection must remember stage for non-HTML5 drag fallback');
const assignedByClick = assignSelectedStageToNode(factory, selectedState, 'etri-dev0001-jetorn');
assert.strictEqual(assignedByClick.placements.find((item) => item.stage === 'inference').targetNode, 'etri-dev0001-jetorn', 'click node assignment fallback must update placement');
assert.strictEqual(selectedState.selectedStage, '', 'click assignment must clear selected stage');

const placement = buildPlacementModel(factory, COMPUTE_NODES);
assert(placement.rows.some((row) => row.stage === 'inference' && row.targetNode), 'placement model must separate stage assignment from DAG');
assert(placement.nodes.every((node) => node.kind === 'compute'), 'placement nodes must be compute nodes only');

const transport = buildTransportModel(factory, COMPUTE_NODES, PLATFORM_ENDPOINTS);
assert(transport.rows.some((row) => row.data === 'feature-vector' && row.producerStage === 'preprocess' && row.consumerStage === 'inference'), 'transport view must include stage-to-stage data');
assert(transport.rows.some((row) => row.data === 'mqtt-event' && row.consumerEndpoint === 'Dashboard'), 'transport view must include endpoint delivery');
assert(transport.rows.some((row) => row.consumerEndpoint === 'InfluxDB'), 'transport view must include InfluxDB sink when configured');

assert(html.includes('workflow-kpi-grid'), 'designer must use dashboard-like KPI cards');
assert(html.includes('operator-strip'), 'designer must include operator question / read-only / editable guardrail strip');
assert(html.includes('IBM Plex Sans KR'), 'designer must use deliberate dashboard typography instead of default system font');
assert(html.includes('workflow-layout'), 'designer must use dashboard-like main + sticky inspector layout');
assert(html.includes('placement-panel'), 'placement inspector must be a dedicated dashboard side panel');
assert(html.includes('drag-drop-guide'), 'UI must show explicit drag/drop and click fallback guidance');
assert(html.includes('validationMetric'), 'validation KPI card must expose status class hook');
assert(html.includes('body::after'), 'designer must include subtle texture/noise to avoid flat UI');
assert(!html.includes('class="side-stack"'), 'stale side-stack markup must not remain');
assert(html.includes('grid-template-columns:minmax(0,1fr) minmax(380px,430px)'), 'dashboard layout must reserve a fixed inspector rail without overlap');

console.log('PASS workflow designer rules: DAG, placement, transport, endpoints, validation, dashboard ui layout');
