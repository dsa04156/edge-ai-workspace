/* Read-only presentation policies shared by the dashboard and its tests. */
(function(root){
'use strict';
function catalogUrl(href){const u=new URL(href);['service','workloads','view'].forEach(k=>u.searchParams.delete(k));u.hash='services';return u;}
function pageItems(items,page=0,size=25){const pages=Math.max(1,Math.ceil(items.length/size)),index=Math.max(0,Math.min(pages-1,Number(page)||0));return {items:items.slice(index*size,(index+1)*size),page:index,pages,total:items.length};}
function validNodeSample(node,current,now=Date.now()){const age=now-Date.parse(node?.collected_at);return Boolean(current&&age>=-5000&&age<=60000&&node?.node_health!=='unavailable'&&node?.raw_metrics?.up!==0);}
function groupEvents(events){const groups=new Map();for(const e of events){const key=JSON.stringify([e.service_id,e.type,e.state,[...(e.reasons||[])].sort(),e.node]);if(!groups.has(key))groups.set(key,{...e,count:1});else groups.get(key).count++;}return [...groups.values()];}
function filterSources(sources,{health='all',node='',current=true}={}){return sources.filter(s=>(!node||s.functions.some(f=>f.device.node_name===node))&&(health==='all'||(health==='unknown'?!current:current&&(health==='attention'?s.functions.some(f=>f.device.overall_status!=='available'):s.functions.every(f=>f.device.overall_status==='available')))));}
const api={catalogUrl,pageItems,validNodeSample,groupEvents,filterSources};root.NexusUX=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window==='undefined'?globalThis:window);
