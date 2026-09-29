// Keep both tab documents alive and report their content height to the shell.
if (new URLSearchParams(location.search).get('embedded')==='1' && window.parent!==window) {
  const header=document.querySelector('header');
  if (header) header.style.display='none';
  let scheduled=false;
  const report=()=>{
    scheduled=false;
    const height=document.body.getBoundingClientRect().height;
    if (height>0) window.parent.postMessage({type:'biocover-frame-height',height},location.origin);
  };
  const schedule=()=>{
    if (!scheduled) { scheduled=true;requestAnimationFrame(report); }
  };
  new ResizeObserver(schedule).observe(document.body);
  window.addEventListener('load',schedule);
  window.addEventListener('message',event=>{
    if (event.source===parent && event.origin===location.origin && event.data?.type==='biocover-view-visible') {
      window.dispatchEvent(new Event('resize'));
      schedule();
    }
  });
  schedule();
}
