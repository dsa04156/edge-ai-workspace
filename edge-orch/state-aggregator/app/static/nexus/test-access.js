/* Keep the scoped capability out of HTTP requests, history, and persistent storage. */
(() => {
  let token=null;
  function capture(){
    const value=new URLSearchParams(location.hash.slice(1)).get('vd-test');
    if(!value||!/^vdtest\.\d+\.[a-f0-9]{32}\.[a-f0-9]{64}$/.test(value))return false;
    token=value;history.replaceState(null,'','#virtual-devices');return true;
  }
  capture();
  window.addEventListener('hashchange',()=>{
    if(!capture())return;
    document.querySelector('[data-mode="live"]')?.click();
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  window.addEventListener('message',event=>{
    const frame=document.getElementById('nexus-workspace-frame');
    if(!token||event.origin!==location.origin||event.source!==frame?.contentWindow||event.data?.type!=='vd-test-ready')return;
    if(new URL(frame.src).hash!=='#virtual-devices')return;
    event.source.postMessage({type:'vd-test-access',token},location.origin);
  });
})();
