// Shared time-window navigation and drawing for live monitoring and replay.
export const markerRadius = span => span >= 30 * 60 * 1000 ? 0 : 1.2;

export class ChartViewport {
  constructor() { this.session = undefined; this.selection = undefined; this.manualEnd = null; }
  update({session, selection, first, latest}) {
    if (session !== this.session || selection !== this.selection) this.manualEnd = null;
    this.session = session;
    this.selection = selection;
    this.first = Number.isFinite(first) ? first : latest;
    this.latest = latest;
    this.span = selection === 'all' ? Math.max(1000, latest - this.first) : Number(selection) * 1000;
    this.minEnd = Math.min(latest, this.first + this.span);
    if (this.manualEnd !== null) this.panTo(this.manualEnd);
  }
  get end() { return this.manualEnd ?? this.latest; }
  get start() { return this.end - this.span; }
  get canPan() { return this.latest - this.minEnd > 1; }
  get following() { return this.manualEnd === null; }
  panTo(end) {
    const clamped = Math.max(this.minEnd, Math.min(this.latest, end));
    this.manualEnd = clamped >= this.latest - 1 ? null : clamped;
  }
  drag(anchor, pixels, width) {
    if (width > 0) this.panTo(anchor - pixels / width * this.span);
  }
  follow() { this.manualEnd = null; }
}

function lowerBound(rows, time, limit) {
  let lo=0, hi=limit;
  while (lo<hi) {
    const mid=Math.floor((lo+hi)/2);
    if (rows[mid].time_ms<time) lo=mid+1; else hi=mid;
  }
  return lo;
}

export function visibleSlice(rows, limit, start, end) {
  const lo=lowerBound(rows,start,limit);
  let hi=lowerBound(rows,end,limit);
  while (hi<limit && rows[hi].time_ms<=end) hi++;
  return {lo,hi,rows:rows.slice(lo,hi)};
}

export function drawSeries(canvas, {key, color, unit, rows, start, end}) {
  const box=canvas.getBoundingClientRect(), w=box.width, h=box.height;
  if (w<80 || h<60) return; // Hidden tabs get redrawn when shown.
  const ratio=globalThis.devicePixelRatio || 1;
  canvas.width=Math.round(w*ratio); canvas.height=Math.round(h*ratio);
  const ctx=canvas.getContext('2d'); ctx.scale(ratio,ratio);
  const left=43,right=w-12,top=12,bottom=h-29,span=Math.max(1,end-start);
  let lo=Infinity, hi=-Infinity, count=0;
  for (const row of rows) if (Number.isFinite(row[key])) {
    lo=Math.min(lo,row[key]); hi=Math.max(hi,row[key]); count++;
  }
  if (!count) { lo=0; hi=1; }
  const pad=Math.max((hi-lo)*.15,unit==='raw'?2:.2); lo-=pad; hi+=pad;
  ctx.font='10px system-ui'; ctx.lineWidth=1;
  for (let i=0;i<4;i++) {
    const y=top+(bottom-top)*i/3;
    ctx.strokeStyle='#edf1ee'; ctx.beginPath(); ctx.moveTo(left,y); ctx.lineTo(right,y); ctx.stroke();
    ctx.fillStyle='#8a9690'; ctx.textAlign='right';
    ctx.fillText((hi-(hi-lo)*i/3).toFixed(hi-lo>20?0:1),left-8,y+3);
  }
  const ticks=w<420?3:4;
  for (let i=0;i<ticks;i++) {
    ctx.textAlign=i===0?'left':i===ticks-1?'right':'center';
    const time=new Date(start+span*i/(ticks-1)).toLocaleTimeString('ko-KR',{
      hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
    ctx.fillText(time,left+(right-left)*i/(ticks-1),h-6);
  }
  ctx.save(); ctx.beginPath(); ctx.rect(left,top,right-left,bottom-top); ctx.clip();
  ctx.strokeStyle=color; ctx.fillStyle=color; ctx.lineWidth=2; ctx.beginPath();
  let prior=null;
  const point=row=>[left+(row.time_ms-start)/span*(right-left),bottom-(row[key]-lo)/(hi-lo)*(bottom-top)];
  for (const row of rows) {
    if (!Number.isFinite(row[key])) { prior=null; continue; }
    const [x,y]=point(row);
    if (prior===null || row.time_ms-prior>8500) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    prior=row.time_ms;
  }
  ctx.stroke();
  const radius=markerRadius(span);
  if (radius) for (const row of rows) {
    if (!Number.isFinite(row[key])) continue;
    const [x,y]=point(row);
    ctx.beginPath(); ctx.arc(x,y,radius,0,Math.PI*2); ctx.fill();
  }
  ctx.restore();
  if (!count) {
    ctx.textAlign='center'; ctx.fillStyle='#9ba69f'; ctx.font='12px system-ui';
    ctx.fillText('이 구간에 측정값이 없습니다',(left+right)/2,(top+bottom)/2);
  }
}

export class ChartPanels {
  constructor(sensors, {followLabel='최신 구간'}={}) {
    this.sensors=sensors;
    this.followLabel=followLabel;
    this.view=new ChartViewport();
    this.source=null;
    this.rows=[];
    this.limit=0;
    this.validBounds={};
    this.dragging=null;
    this.panels=[];
    const link=document.createElement('link');
    link.rel='stylesheet'; link.href=new URL('./chart.css',import.meta.url); document.head.append(link);
    const navigation=document.createElement('div'); navigation.className='chart-navigation';
    this.status=document.createElement('span'); this.status.id='chart-view-status';
    this.followButton=document.createElement('button'); this.followButton.id='chart-follow';
    this.followButton.textContent=followLabel;
    this.followButton.onclick=()=>this.follow();
    navigation.append(this.status,this.followButton);
    document.getElementById('charts').before(navigation);
    for (const [key,label] of sensors) {
      const canvas=document.getElementById('chart-'+key), panel=canvas.closest('.chart-panel');
      const surface=document.createElement('div'); surface.className='chart-surface';
      canvas.before(surface); surface.append(canvas);
      canvas.tabIndex=0;
      canvas.setAttribute('aria-label',`${label} 시계열. 좌우 드래그 또는 방향키로 시간 이동, End키로 복귀`);
      const edges=['left','right'].map((side,i)=>{
        const edge=document.createElement('span'); edge.className='chart-edge chart-edge-'+side;
        edge.textContent=i===0?'← 이전 데이터':'이후 데이터 →'; edge.hidden=true;
        edge.setAttribute('aria-hidden','true'); surface.append(edge); return edge;
      });
      this.panels.push({key,canvas,panel,edges});
      panel.addEventListener('pointerdown',event=>this.beginDrag(event,panel,canvas));
      panel.addEventListener('pointermove',event=>this.moveDrag(event));
      for (const name of ['pointerup','pointercancel','lostpointercapture']) {
        panel.addEventListener(name,event=>this.endDrag(event));
      }
      canvas.addEventListener('keydown',event=>{
        if (!this.rows.length) return;
        if (event.key==='ArrowLeft') this.view.panTo(this.view.end-this.view.span*.2);
        else if (event.key==='ArrowRight') this.view.panTo(this.view.end+this.view.span*.2);
        else if (event.key==='Home') this.view.panTo(this.view.minEnd);
        else if (event.key==='End') this.view.follow();
        else return;
        event.preventDefault(); this.render();
      });
    }
  }

  update({rows, limit=rows.length, session, selection, latest}) {
    const changed=rows!==this.source;
    if (changed) {
      this.source=rows;
      this.rows=rows.map(row=>({...row,time_ms:row.time_ms ?? Date.parse(row.timestamp)}));
    }
    limit=Math.max(0,Math.min(limit,this.rows.length));
    if (changed || limit!==this.limit) {
      this.validBounds=Object.fromEntries(this.sensors.map(([key])=>[key,{first:Infinity,last:-Infinity}]));
      for (let i=0;i<limit;i++) for (const [key] of this.sensors) {
        if (!Number.isFinite(this.rows[i][key])) continue;
        const bounds=this.validBounds[key];
        bounds.first=Math.min(bounds.first,this.rows[i].time_ms);
        bounds.last=Math.max(bounds.last,this.rows[i].time_ms);
      }
    }
    this.limit=limit;
    this.view.update({session,selection,first:limit?this.rows[0].time_ms:latest,latest});
    this.render();
  }

  follow() { this.view.follow(); this.render(); }

  beginDrag(event,panel,canvas) {
    if (event.button!==0 || !event.isPrimary || !this.view.canPan || this.dragging) return;
    if (event.target.closest('button,a,input,select')) return;
    this.dragging={pointer:event.pointerId,x:event.clientX,end:this.view.end,
      width:canvas.getBoundingClientRect().width-55,panel,moved:false};
    panel.setPointerCapture(event.pointerId);
  }

  moveDrag(event) {
    const drag=this.dragging;
    if (!drag || event.pointerId!==drag.pointer) return;
    const dx=event.clientX-drag.x;
    if (!drag.moved && Math.abs(dx)<4) return;
    drag.moved=true;
    event.preventDefault();
    drag.panel.classList.add('chart-dragging');
    this.view.drag(drag.end,dx,drag.width);
    this.render();
  }

  endDrag(event) {
    const drag=this.dragging;
    if (!drag || event.pointerId!==drag.pointer) return;
    this.dragging=null;
    drag.panel.classList.remove('chart-dragging');
    if (drag.panel.hasPointerCapture(event.pointerId)) drag.panel.releasePointerCapture(event.pointerId);
  }

  render() {
    if (this.view.selection===undefined) return;
    const {start,end,span}=this.view;
    const visible=visibleSlice(this.rows,this.limit,start,end).rows;
    const time=t=>new Date(t).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour12:false,
      hour:'2-digit',minute:'2-digit',second:'2-digit'});
    this.status.textContent=this.limit?`${time(start)} ~ ${time(end)} · ${this.view.following?'좌우로 드래그하여 이동':'과거 구간 보는 중'}`:'기록이 쌓이면 그래프를 좌우로 드래그할 수 있습니다.';
    this.followButton.disabled=this.view.following || !this.limit;
    for (let i=0;i<this.panels.length;i++) {
      const {key,canvas,panel,edges}=this.panels[i];
      const [,,,unit,color]=this.sensors[i];
      const bounds=this.validBounds[key];
      edges[0].hidden=!(bounds?.first<start);
      edges[1].hidden=!(bounds?.last>end);
      panel.dataset.pannable=String(this.view.canPan && this.limit>0);
      // Also make the displayed interval inspectable for browser/accessibility checks.
      canvas.dataset.start=String(start); canvas.dataset.end=String(end);
      canvas.dataset.markerRadius=String(markerRadius(span));
      drawSeries(canvas,{key,color,unit,rows:visible,start,end});
    }
  }
}
