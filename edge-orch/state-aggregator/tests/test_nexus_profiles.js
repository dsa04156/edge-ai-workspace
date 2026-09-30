const test = require('node:test');
const assert = require('node:assert/strict');
const {observationHTML} = require('../app/static/nexus/profiles.js');
function fixture(observedAt) {
  return {observedAt, maxAgeSeconds:60, devices:[{id:'<img src=x onerror=alert(1)>',profileRef:{name:'shared'}}], profiles:[{metadata:{name:'shared'},spec:{hardware:{architecture:'arm64'}}}],states:[{metadata:{deviceId:'<img src=x onerror=alert(1)>'},status:{phase:'Ready',reservation:{available:{cpuCores:2,memoryBytes:4*1024**3}},utilization:{observedAt,cpuRatio:0.1,memoryRatio:null}}}]};
}
test('observation escapes source values and preserves unreported metrics',()=>{
  const now=Date.now();const html=observationHTML(fixture(new Date(now).toISOString()),now);
  assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));
  assert.ok(html.includes('10% / 미수집'));assert.ok(html.includes('4 GiB'));
});
test('stale/future readings never display usage',()=>{
  const now=Date.now();
  for(const delta of [-61000,1000]){
    const html=observationHTML(fixture(new Date(now+delta).toISOString()),now);
    assert.ok(html.includes('오래된 관측'));assert.ok(!html.includes('10%'));
  }
});
test('empty and source failure are different',()=>{
  assert.match(observationHTML({devices:[]}),/노드가 없습니다/);
  assert.match(observationHTML({observationError:'unavailable'}),/판단할 수 없습니다/);
});
