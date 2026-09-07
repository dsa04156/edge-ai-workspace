const {test} = require("node:test");
const assert = require("node:assert/strict");
const {displayState, filterRows, placements, detail} = require("../app/static/virtual-devices.js");
function fixture() {
  const now = new Date().toISOString();
  return {observedAt:now,maxAgeSeconds:30,nodes:[{name:"server"}],
    summary:{physicalNodes:1,definitions:1,observedInstances:0},
    resources:[{id:"vd-demo-001",observedAt:now,executionState:"no_instance",
      connectionState:"configured_unverified",observedInstances:0,instances:[],connections:[],
      definition:{spec:{displayName:"CPU",capabilities:["iris"],model:{},runtimeRef:{namespace:"virtual-device-test"}}}}]};
}
test("registered-only definition stays in list but never in placement",()=>{
  const view=displayState(fixture());
  assert.equal(view.resources.length,1);
  assert.equal(placements(view).get("server").length,0);
  assert.equal(filterRows(view.resources,"vd-demo","").length,1);
  assert.equal(filterRows(view.resources,"","server").length,0);
  assert.match(detail(view.resources[0]),/등록 정의는 유지/);
});
test("failed and expired observations never assert no-instance or zero usage",()=>{
  for (const failed of [true,false]) {
    const snapshot=fixture();
    if(!failed) snapshot.observedAt="2000-01-01T00:00:00Z";
    const view=displayState(snapshot,failed);
    assert.equal(view.summary.observedInstances,null);
    assert.equal(view.resources[0].executionState,"unknown");
    assert.equal(view.resources[0].connectionState,"unknown");
    assert.equal(view.resources.length,1);
    assert.equal(placements(view).size,0);
    assert.match(detail(view.resources[0]),/자원 반환 여부를 확인할 수 없/);
  }
});
test("API outage keeps observed Pod placement but model readiness is unknown",()=>{
  const snapshot=fixture();
  snapshot.resources[0].instances=[{podUid:"uid",node:"server",podReady:true,apiObservedAt:null,
    modelReady:true,usage:{cpuCores:0,memoryBytes:0},resources:[]}];
  const view=displayState(snapshot);
  assert.equal(placements(view).get("server").length,1);
  assert.equal(view.resources[0].instances[0].modelReady,null);
  assert.match(detail(view.resources[0]),/N\/A/);
});
test("untrusted strings are escaped in inspector",()=>{
  const row=fixture().resources[0];
  row.id='<img src=x onerror=alert(1)>';
  assert.ok(!detail(row).includes("<img"));
});
