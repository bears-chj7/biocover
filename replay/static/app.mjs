import {Player} from './player.mjs';

const sensors = [
  ['ds18','토양 온도','DS18B20','°C','#318873',2],
  ['temperature','공기 온도','DHT22','°C','#617bc4',1],
  ['humidity','상대습도','DHT22','%','#498bad',1],
  ['mq1','메탄 · 유입','MQ-4 #1','raw','#b47c43',0],
  ['mq2','메탄 · 유출','MQ-4 #2','raw','#9168b7',0],
  ['soil','토양수분','CH4','raw','#7c9460',0],
];
const $ = id => document.getElementById(id);
const player = new Player();
const format = (v,n=1) => Number.isFinite(v) ? v.toFixed(n) : '—';
const localTime = t => new Date(t).toLocaleTimeString('ko-KR',{hour12:false});
const duration = ms => {
  const seconds = Math.floor(ms / 1000);
  const h = Math.floor(seconds / 3600);
  return `${h ? h + ':' : ''}${String(Math.floor(seconds / 60) % 60).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`;
};
const names = {idle:'파일 선택 대기',ready:'재생 준비',running:'재생 중',paused:'일시정지',stopped:'정지',ended:'재생 완료'};
let busy = false;
let lastCursor = -1;
let lastRender = -Infinity;
let scrubbing = false, resumeAfterScrub = false;
// Upgrade cached templates without restarting either server.
if ($('progress').tagName !== 'INPUT') {
  const slider = document.createElement('input');
  slider.id = 'progress'; slider.type = 'range'; slider.min = '0'; slider.max = '1';
  slider.step = '0.001'; slider.value = '0'; slider.setAttribute('aria-label','재생 타임라인');
  $('progress').replaceWith(slider);
}
for (const [value,label] of [['3600','최근 1시간'],['7200','최근 2시간'],['all','전체']]) {
  if (![...$('window').options].some(option => option.value === value)) $('window').add(new Option(label,value));
}

for (const [key,label,model,unit,color] of sensors) {
  const card = document.createElement('article');
  card.className = 'sensor-card';
  card.style.setProperty('--c',color);
  card.innerHTML = `<div class="sensor-title"><span>${label}</span><span>${model}</span></div><div class="value"><span id="value-${key}">—</span> <small>${unit}</small></div><div class="detail" id="detail-${key}">재생 대기</div><div class="stats"><span>재생 구간 평균<b id="mean-${key}">—</b></span><span>최솟값<b id="min-${key}">—</b></span><span>최댓값<b id="max-${key}">—</b></span></div>`;
  $('cards').append(card);
  const panel = document.createElement('article');
  panel.className = 'chart-panel';
  panel.innerHTML = `<div class="chart-heading"><h3>${label} <small>${unit === 'raw' ? 'ADC raw · 보정 전' : unit}</small></h3><div class="legend"><span style="--c:${color}">${model}</span></div></div><canvas id="chart-${key}" aria-label="${label} 시계열"></canvas>`;
  $('charts').append(panel);
}

function error(message='') {
  $('error').textContent = message;
  $('error').hidden = !message;
}

async function api(path, options={}) {
  const response = await fetch(path, {cache:'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || `HTTP ${response.status}`);
  return data;
}

function controls() {
  const active = ['running','paused'].includes(player.state);
  $('start').disabled = busy || !player.recording || active;
  $('start').textContent = ['ended','stopped'].includes(player.state) ? '↻ 처음부터 재생' : '▶ 재생';
  $('pause').disabled = busy || player.state !== 'running';
  $('resume').disabled = busy || player.state !== 'paused';
  $('stop').disabled = busy || !(active || player.state === 'ended');
  $('load-file').disabled = busy || !$('file-select').value;
  $('file-select').disabled = busy;
  $('upload').disabled = busy;
  $('files-refresh').disabled = busy;
  for (const button of $('files').querySelectorAll('button')) button.disabled = busy;
  $('slower').disabled = player.speed <= 1;
  $('faster').disabled = player.speed >= 50;
  $('progress').disabled = busy || !player.recording || !player.duration;
}

function render(force=false) {
  controls();
  $('state').textContent = busy ? '파일 불러오는 중' : names[player.state];
  $('pulse').classList.toggle('on',player.state === 'running');
  $('samples').textContent = `${player.cursor.toLocaleString()} / ${(player.recording?.count || 0).toLocaleString()}행`;
  $('elapsed').textContent = `${duration(player.position)} / ${duration(player.duration || 0)}`;
  $('progress').value = player.duration ? player.position / player.duration : player.state === 'ended' ? 1 : 0;
  $('progress').setAttribute('aria-valuetext', `${duration(player.position)} / ${duration(player.duration || 0)}`);
  $('refresh').textContent = player.timestamp === null ? '원본 시각 기준' : `재생 시각 ${localTime(player.timestamp)} · ${player.speed}배속`;
  $('session-time').textContent = player.recording ? new Date(player.recording.started_at).toLocaleString('ko-KR') + ' 시작 기록' : 'CSV를 선택하세요';
  if (player.recording) {
    const note = {ready:'재생을 누르면 첫 기록부터 시작합니다.',running:'CSV의 원래 기록 간격을 배속에 맞춰 재생합니다.',paused:'현재 시점에서 멈췄습니다. 재개하면 이어집니다.',stopped:'처음 위치로 돌아왔습니다. 재생하면 다시 시작합니다.',ended:'마지막 기록까지 재생했습니다. 처음부터 다시 재생할 수 있습니다.'};
    $('notice').textContent = `${player.recording.name} · ${note[player.state]}`;
  }
  if (force || lastCursor !== player.cursor) {
    const row = player.latest;
    for (const [key,label,model,unit,color,n] of sensors) {
      $(`value-${key}`).textContent = format(row?.[key],n);
      $(`detail-${key}`).textContent = !row ? '재생 대기' : row[key] === null ? '이 기록은 결측값' : unit === 'raw' ? `${format(row[key+'_v'],3)} V · 보정 전` : `기록 시각 ${localTime(row.timestamp)}`;
      for (const stat of ['mean','min','max']) $(`${stat}-${key}`).textContent = format(player.stats[key][stat],n);
    }
    renderLogs();
    lastCursor = player.cursor;
  }
  drawAll();
}

function renderLogs() {
  const body = $('logs');
  body.replaceChildren();
  if (!player.cursor) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 8; td.className = 'empty'; td.textContent = '아직 재생한 기록이 없습니다.';
    tr.append(td); body.append(tr);
  }
  const fragment = document.createDocumentFragment();
  for (const row of player.recent().reverse()) {
    const tr = document.createElement('tr');
    const valid = sensors.every(([key]) => Number.isFinite(row[key]));
    const statusOK = ['uno_status','adc_status'].every(key => !row[key] || row[key] === 'ok');
    const ok = valid && statusOK && !row.errors.length;
    const values = [localTime(row.timestamp),...sensors.map(([key,a,b,c,d,n])=>format(row[key],n)),ok?'정상':'결측/오류'];
    values.forEach((value,index) => {
      const td = document.createElement('td'); td.textContent = value;
      if (index === 0) td.title = new Date(row.timestamp).toLocaleString('ko-KR');
      if (index === 7) { td.className = ok ? 'ok' : 'warn'; td.title = row.errors.join(' / '); }
      tr.append(td);
    });
    fragment.append(tr);
  }
  body.append(fragment);
}

async function loadRecording(path, options={}) {
  if (busy) return;
  player.pause(); // A failed selection leaves the old session paused, ready to resume.
  busy = true; error(); render();
  try {
    const recording = await api(path,options);
    player.load(recording);
    lastCursor = -1;
    for (const button of $('files').querySelectorAll('button')) button.classList.toggle('selected',button.dataset.name === recording.name);
  } catch (e) { error(`CSV를 불러오지 못했습니다: ${e.message}`); }
  finally { busy = false; $('upload').value = ''; render(true); }
}

function chooseSaved(name) {
  $('file-select').value = name;
  return loadRecording('/api/recording/' + encodeURIComponent(name));
}

async function loadFiles() {
  try {
    const files = await api('/api/files');
    const selected = $('file-select').value;
    $('file-select').replaceChildren(new Option(files.length?'파일을 선택하세요':'완료된 CSV가 없습니다',''));
    $('files').replaceChildren();
    for (const file of files) {
      $('file-select').append(new Option(file.name,file.name));
      const button = document.createElement('button');
      button.className = 'file'; button.dataset.name = file.name; button.textContent = file.name;
      button.classList.toggle('selected',file.name === player.recording?.name);
      const span = document.createElement('span'); span.textContent = `${(file.bytes/1024).toFixed(1)} KB · 불러오기`;
      button.append(span); button.onclick = () => chooseSaved(file.name); $('files').append(button);
    }
    if (files.some(file => file.name === selected)) $('file-select').value = selected;
    if (!files.length) $('files').textContent = '완료된 CSV가 없습니다. 이 기기에서 파일을 선택할 수도 있습니다.';
    controls();
  } catch (e) { error(`파일 목록을 불러오지 못했습니다: ${e.message}`); }
}

$('file-select').onchange = controls;
$('load-file').onclick = () => chooseSaved($('file-select').value);
$('files-refresh').onclick = () => loadFiles();
$('upload').onchange = () => {
  const file = $('upload').files[0];
  if (!file) return;
  if (file.size > 20*1024*1024) { error('CSV는 20 MiB 이하만 지원합니다.'); $('upload').value = ''; return; }
  const body = new FormData(); body.append('file',file);
  loadRecording('/api/upload',{method:'POST',body});
};
for (const [id,method] of [['start','replay'],['pause','pause'],['resume','resume'],['stop','stop']]) {
  $(id).onclick = () => { player[method](); render(true); };
}
function setSpeed(value) {
  try { player.setSpeed(value); error(); }
  catch (e) { error(e.message); }
  $('speed').value = player.speed;
  render();
}
$('speed').onchange = () => setSpeed($('speed').value);
$('speed').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); setSpeed($('speed').value); } };
$('slower').onclick = () => setSpeed(Math.max(1,player.speed-1));
$('faster').onclick = () => setSpeed(Math.min(50,player.speed+1));
$('window').onchange = () => drawAll();
$('progress').oninput = () => {
  player.seek(Number($('progress').value) * player.duration);
  render(true);
};
$('progress').onpointerdown = () => {
  scrubbing = true;
  resumeAfterScrub = player.state === 'running';
  player.pause();
};
function finishScrub() {
  if (!scrubbing) return;
  scrubbing = false;
  if (resumeAfterScrub) player.resume();
  render(true);
}
window.addEventListener('pointerup',finishScrub);
window.addEventListener('pointercancel',finishScrub);
$('progress').onblur = finishScrub;

function drawAll() {
  const windowMs = $('window').value === 'all' ? Math.max(player.position,1000) : Number($('window').value)*1000;
  const rows = player.visible(windowMs);
  for (const sensor of sensors) draw(sensor,rows,windowMs);
}

function draw([key,label,model,unit,color],rows,windowMs) {
  const canvas = $('chart-'+key), box = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1, w = box.width, h = box.height;
  canvas.width = Math.round(w*ratio); canvas.height = Math.round(h*ratio);
  const ctx = canvas.getContext('2d'); ctx.scale(ratio,ratio);
  const left=43, right=w-12, top=12, bottom=h-29;
  const end = player.timestamp ?? Date.now(), start = end-windowMs;
  let lo=Infinity, hi=-Infinity, count=0;
  for (const row of rows) if (Number.isFinite(row[key])) { lo=Math.min(lo,row[key]); hi=Math.max(hi,row[key]); count++; }
  if (!count) { lo=0; hi=1; }
  const pad=Math.max((hi-lo)*.15,unit==='raw'?2:.2); lo-=pad; hi+=pad;
  ctx.font='10px system-ui'; ctx.lineWidth=1;
  for (let i=0;i<4;i++) {
    const y=top+(bottom-top)*i/3;
    ctx.strokeStyle='#edf1ee'; ctx.beginPath(); ctx.moveTo(left,y); ctx.lineTo(right,y); ctx.stroke();
    ctx.fillStyle='#8a9690'; ctx.textAlign='right'; ctx.fillText(format(hi-(hi-lo)*i/3,hi-lo>20?0:1),left-8,y+3);
  }
  const ticks=w<420?3:4;
  for (let i=0;i<ticks;i++) {
    ctx.textAlign=i===0?'left':i===ticks-1?'right':'center';
    ctx.fillText(localTime(start+windowMs*i/(ticks-1)),left+(right-left)*i/(ticks-1),h-6);
  }
  ctx.strokeStyle=color; ctx.fillStyle=color; ctx.lineWidth=2; ctx.beginPath();
  let prior=null;
  for (const row of rows) {
    if (!Number.isFinite(row[key])) { prior=null; continue; }
    const x=left+(row.time_ms-start)/windowMs*(right-left), y=bottom-(row[key]-lo)/(hi-lo)*(bottom-top);
    if (prior===null || row.time_ms-prior>8500) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    prior=row.time_ms;
  }
  ctx.stroke();
  for (const row of rows) {
    if (!Number.isFinite(row[key])) continue;
    const x=left+(row.time_ms-start)/windowMs*(right-left), y=bottom-(row[key]-lo)/(hi-lo)*(bottom-top);
    ctx.beginPath(); ctx.arc(x,y,2.3,0,Math.PI*2); ctx.fill();
  }
  if (!count) { ctx.textAlign='center'; ctx.fillStyle='#9ba69f'; ctx.font='12px system-ui'; ctx.fillText('이 구간에 측정값이 없습니다',(left+right)/2,(top+bottom)/2); }
}

window.addEventListener('resize',drawAll);
function frame(now) {
  const wasRunning = player.state === 'running';
  player.tick(now);
  if (wasRunning && (now-lastRender >= 100 || player.state === 'ended')) { render(); lastRender=now; }
  requestAnimationFrame(frame);
}
render(true); loadFiles(); requestAnimationFrame(frame);
