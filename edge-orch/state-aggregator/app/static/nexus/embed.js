/* Same-origin presentation only; all existing operation permissions are retained. */
if(new URLSearchParams(location.search).get('workspace')==='1' && window.self!==window.top){
 document.documentElement.classList.add('nexus-embedded');
}
