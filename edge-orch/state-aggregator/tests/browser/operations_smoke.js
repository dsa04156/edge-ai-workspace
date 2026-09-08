// Run with playwright-cli run-code against the local read-only live-observation preview.
// The authoring roundtrip requires the isolated preview DB and its public test token.
async (page) => {
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const base='http://127.0.0.1:8776';
  const report=[];
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:900});
    for(const route of ['overview','services','resources','data','history','validation']){
      await page.goto(base+'/#'+route);
      await page.waitForSelector('#nav a[aria-current="page"]');
      if(route==='services')await page.waitForSelector('.ops-stage',{timeout:25000});
      if(route==='history')await page.waitForSelector('.ops-section table',{timeout:25000});
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      if(overflow)throw new Error('page overflow '+width+' '+route);
      report.push({width,route,overflow});
      if(route==='services'){
        await page.locator('.ops-dag').scrollIntoViewIfNeeded();
        await page.screenshot({path:'output/playwright/service-flow-'+width+'.png'});
      }
    }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(base+'/#designer');
  if(!await page.locator('#nexus-workspace-frame').count())await page.locator('[data-workspace="designer"]').first().click();
  const frame=page.frameLocator('#nexus-workspace-frame');
  await frame.locator('#serviceDesignRegistry summary').click();
  await frame.locator('#registryRefresh').click();
  await frame.locator('#registryStages select').first().waitFor({timeout:25000});
  await frame.locator('#registryServiceId').fill('browser-roundtrip');
  const version='ui-'+Date.now();await frame.locator('#registryVersion').fill(version);
  await frame.locator('#registryToken').fill('local-preview-only');
  await frame.locator('#registrySave').click();
  await frame.locator('#registryFeedback').filter({hasText:'서버 저장 확인:'}).waitFor({timeout:10000});
  await frame.locator('#registryValidate').click();
  await frame.locator('#registryFeedback').filter({hasText:'서버 검증: BLOCKED'}).waitFor({timeout:10000});
  if(!await frame.getByRole('button',{name:'배포 미연결'}).isDisabled())throw new Error('blocked deploy enabled');
  await frame.locator('#registryRefresh').click();
  await frame.locator('[data-registry-load="browser-roundtrip"][data-version="'+version+'"]').click();
  await frame.locator('#registryFeedback').filter({hasText:'서버 버전을 편집기에 불러왔습니다'}).waitFor();
  await page.screenshot({path:'output/playwright/designer-registry.png'});
  if(errors.length)throw new Error(JSON.stringify(errors));
  return {report,registryRoundtrip:true,blockedDeployment:true,pageErrors:errors};
}
