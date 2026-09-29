const views = ['live','replay'];
const scrollPositions = {live:0,replay:0};
let active = 'live';
const frame = name => document.getElementById('frame-'+name);

function select(name, focus=false) {
  if (!views.includes(name)) name='live';
  if (name!==active) scrollPositions[active]=window.scrollY;
  active=name;
  for (const view of views) {
    const selected=view===name;
    const tab=document.getElementById('tab-'+view);
    tab.setAttribute('aria-selected',String(selected));
    tab.tabIndex=selected?0:-1;
    document.getElementById('panel-'+view).hidden=!selected;
  }
  const target=frame(name);
  if (!target.hasAttribute('src')) target.src=target.dataset.src;
  history.replaceState(null,'','#'+name);
  if (focus) document.getElementById('tab-'+name).focus();
  requestAnimationFrame(()=>{
    target.contentWindow?.postMessage({type:'biocover-view-visible'},location.origin);
    window.scrollTo(0,scrollPositions[name]);
  });
}

for (const [index,name] of views.entries()) {
  const tab=document.getElementById('tab-'+name);
  tab.onclick=()=>select(name);
  tab.onkeydown=event=>{
    let next;
    if (event.key==='ArrowRight') next=views[(index+1)%views.length];
    if (event.key==='ArrowLeft') next=views[(index+views.length-1)%views.length];
    if (event.key==='Home') next=views[0];
    if (event.key==='End') next=views.at(-1);
    if (next) { event.preventDefault();select(next,true); }
  };
}

window.addEventListener('message',event=>{
  if (event.origin!==location.origin || event.data?.type!=='biocover-frame-height') return;
  const target=views.map(frame).find(element=>element.contentWindow===event.source);
  const height=Number(event.data.height);
  if (target && Number.isFinite(height) && height>=100 && height<=30000) {
    const next=Math.ceil(height)+'px';
    if (target.style.height!==next) target.style.height=next;
  }
});
window.addEventListener('hashchange',()=>select(location.hash.slice(1)));
select(location.hash.slice(1));
