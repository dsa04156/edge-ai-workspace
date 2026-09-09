/* Reuse approved operational tools without changing their API contracts. */
(function(root){
'use strict';
const E=root.NexusData.escape;
const tools={
 management:{page:'devices',route:'management',title:'장비 연결·관리',description:'발견 후보 검토, 승인된 등록 계약, 첫 Event 확인과 소유 런타임 관리를 기존 절차로 진행합니다.'},
 virtual:{page:'devices',route:'virtual-devices',title:'독립 실행 기능 시험',description:'등록된 가상 디바이스를 시작하고 시험 요청을 보낸 뒤 정지합니다. 실제 실행체·모델 준비·결과와 작업 이력을 함께 확인합니다.'},
 designer:{page:'designer',route:'designer',title:'서비스 설계',description:'실제 입력과 Git 계약으로 초안·검증·실행 계획을 확인합니다. 브라우저 내부 dry-run이며 배포·실행하지 않습니다.'},
 runtime:{page:'resources',route:'operations',title:'서비스 운영·배치 검토',description:'추천 근거, 실행 계획, 실행·복구 이력을 확인합니다. 기존의 제한된 운영 절차와 권한을 유지합니다.'},
 nodes:{page:'resources',route:'nodes',title:'노드·워크로드 상세',description:'KubeEdge 노드, Kubernetes 예약 자원과 Prometheus 측정 자원을 확인합니다.'},
 telemetry:{page:'data',route:'connections',title:'Event·Reading 이력',description:'등록 디바이스의 상세에서 Core Data 저장 이력과 시간 범위를 확인합니다.'},
 service:{page:'services',route:'operations',title:'서비스 운영 상세',description:'등록된 서비스와 기존 서비스 데모의 상세 관측·결과를 확인합니다.'}
};
let selected=null,currentPage=null,callback;
function actions(page){return `<div class="live-workspaces" aria-label="기존 기능 작업 공간">${Object.entries(tools).filter(([id,t])=>t.page===page&&id!=='virtual').map(([id,t])=>`<button class="button" data-workspace="${id}">${E(t.title)} ↗</button>`).join('')}</div>`;}
function render(page){if(page!==currentPage){selected=null;currentPage=page;}if(!selected)return null;const t=tools[selected];return `<section class="tool-workspace"><div class="toolbar"><div><h2>${E(t.title)}</h2><p class="note">${E(t.description)}</p></div><button class="button" data-workspace-close>관측 화면으로 돌아가기</button></div><iframe id="nexus-workspace-frame" title="${E(t.title)}" src="/classic?workspace=1${new URLSearchParams(root.location.search).get('service')?'&service='+encodeURIComponent(new URLSearchParams(root.location.search).get('service')):''}#${t.route}"></iframe></section>`;}
function setup(draw){callback=draw;document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.editService){selected='designer';const u=new URL(root.location.href);u.searchParams.set('service',b.dataset.editService);root.history.replaceState(null,'',u);callback();document.querySelector('#nexus-workspace-frame')?.focus();return;}if(b.dataset.workspace&&tools[b.dataset.workspace]){selected=b.dataset.workspace;callback();document.querySelector('#nexus-workspace-frame')?.focus();}else if(b.hasAttribute('data-workspace-close')){selected=null;callback();}});}
root.NexusWorkspaces={actions,render,setup,open:id=>{if(tools[id]){selected=id;callback();}},isOpen:()=>Boolean(selected),reset:()=>{selected=null;}};
})(window);
