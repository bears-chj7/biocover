const footerNote=document.querySelector('footer span');if(footerNote)footerNote.textContent='화면을 닫아도 측정은 계속됩니다. 종료하려면 정지 버튼을 누르세요.';
const sensors=[['ds18','토양 온도','DS18B20','°C','#318873',2],['temperature','공기 온도','DHT22','°C','#617bc4',1],['humidity','상대습도','DHT22','%','#498bad',1],['mq1','메탄 · 유입','MQ-4 #1','raw','#b47c43',0],['mq2','메탄 · 유출','MQ-4 #2','raw','#9168b7',0],
  ['mq3','메탄 · 유출 #3','MQ-4 #3','raw','#c26962',0],
  ['mq4','메탄 · 유출 #4','MQ-4 #4','raw','#3e8b9b',0],['soil','토양수분','CH4','raw','#7c9460',0]];
const $=id=>document.getElementById(id);let current=null,busy=false,connected=false,lastFileKey='';
const format=(v,n=1)=>v===null||v===undefined?'—':Number(v).toFixed(n);
const localTime=t=>new Date(t).toLocaleTimeString('ko-KR',{hour12:false});
let history=null,plot=null;
import('/static/chart.mjs').then(({ChartPanels})=>{
  plot=new ChartPanels(sensors,{followLabel:'최신 구간'});drawAll();
});
for(const [value,label] of [['3600','최근 1시간'],['7200','최근 2시간'],['all','전체']]) {
  if (![...$('window').options].some(option=>option.value===value)) $('window').add(new Option(label,value));
}
const historyNote=document.createElement('p');historyNote.id='history-note';
$('window').closest('.section-title').querySelector('div').append(historyNote);
import('/static/history.mjs').then(({LiveHistory})=>{
  history=new LiveHistory(after=>api('/api/history?after='+after+'&limit=5000'),()=>{historyNote.textContent=history.message;drawAll();});
  if(current){history.ingest(current);history.fill();drawAll();}
});
const names={idle:'대기',running:'측정 중',paused:'일시정지',stopped:'종료 · 저장됨',error:'확인 필요'};
for(const [k,label,model,unit,color,n] of sensors){const card=document.createElement('article');card.className='sensor-card';card.style.setProperty('--c',color);card.innerHTML=`<div class="sensor-title"><span>${label}</span><span>${model}</span></div><div class="value"><span id="value-${k}">—</span> <small>${unit}</small></div><div class="detail" id="detail-${k}">측정 대기</div><div class="stats"><span>세션 평균<b id="mean-${k}">—</b></span><span>최솟값<b id="min-${k}">—</b></span><span>최댓값<b id="max-${k}">—</b></span></div>`;$('cards').append(card);}
// Build each panel here so updated assets also replace cached server templates.
const charts=document.querySelector('.charts');charts.replaceChildren();
for(const [key,label,model,unit,color] of sensors){const panel=document.createElement('article');panel.className='chart-panel';panel.innerHTML=`<div class="chart-heading"><h3>${label} <small>${unit==='raw'?'ADC raw · 보정 전':unit}</small></h3><div class="legend"><span style="--c:${color}">${model}</span></div></div><canvas id="chart-${key}" aria-label="${label} 시계열"></canvas>`;charts.append(panel);}
async function api(path,method='GET'){const response=await fetch(path,{method,cache:'no-store',...(method==='POST'?{headers:{'Content-Type':'application/json'},body:'{}'}:{})});const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
function error(message){$('error').textContent=message;$('error').hidden=!message;}
function render(s){current=s;if(history){history.ingest(s);history.fill();}$('state').textContent=names[s.state]||s.state;$('samples').textContent=`${s.count.toLocaleString()}회 측정`;$('session-time').textContent=s.started_at?`시작 ${new Date(s.started_at).toLocaleString('ko-KR')}`:'시작 버튼을 눌러 측정하세요';$('start').disabled=busy||!connected||['running','paused'].includes(s.state);$('pause').disabled=busy||!connected||!['running','paused'].includes(s.state);$('stop').disabled=busy||!connected||!['running','paused'].includes(s.state);$('pause').textContent=s.state==='paused'?'▶ 재개':'Ⅱ 일시정지';$('pulse').classList.toggle('on',s.state==='running'&&connected);
const row=s.rows.at(-1);const seconds=row?Math.max(0,(Date.now()-Date.parse(row.timestamp))/1000):null;$('refresh').textContent=row?`최근 기록 ${localTime(row.timestamp)}`:'갱신 주기 5초';
for(const [k,label,model,unit,color,n] of sensors){const stale=s.state==='running'&&seconds>11;const value=stale?null:row?.[k];$(`value-${k}`).textContent=format(value,n);let detail='측정 대기';if(row){detail=s.state==='paused'?'일시정지 시점의 값':s.state==='stopped'?'마지막 기록':value==null?'새 측정값 없음':unit==='raw'?`${format(row[k+'_v'],3)} V · 보정 전`:`UNO 수신 ${format(row.uno_age_s,1)}초 전`;if(stale)detail='새 기록 수신 지연';}$(`detail-${k}`).textContent=detail;for(const stat of ['mean','min','max'])$(`${stat}-${k}`).textContent=format(s.stats[k]?.[stat],n);}
error(s.error);$('notice').textContent=s.state==='running'?`5초마다 기록 중 · ${s.active_file} · 측정마다 디스크에 기록합니다.`:s.state==='paused'?'일시정지 중에는 그래프·로그·CSV를 추가하지 않습니다. 재개하면 최신값부터 이어갑니다.':s.last_file?`저장 완료 · ${s.last_file}${s.reason?' · '+s.reason:''}`:s.recovered.length?`이전 비정상 종료 CSV ${s.recovered.length}개를 복구했습니다. 저장된 세션에서 확인하세요.`:'시작하면 CSV 기록도 함께 시작됩니다. 일시정지 중에는 기록하지 않습니다.';
const body=$('logs');body.replaceChildren();if(!s.rows.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=sensors.length+2;td.className='empty';td.textContent='아직 측정 기록이 없습니다.';tr.append(td);body.append(tr);}for(const r of s.rows.slice(-120).reverse()){const tr=document.createElement('tr');const ok=r.uno_status==='ok'&&r.adc_status==='ok';const values=[localTime(r.timestamp),...sensors.map(([k,a,b,c,d,n])=>format(r[k],n)),ok?'정상':'결측/오류'];values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(i===sensors.length+1){td.className=ok?'ok':'warn';td.title=(r.errors||[]).join(' / ');}tr.append(td);});body.append(tr);}drawAll();const key=`${s.last_file}|${s.recovered.length}`;if(lastFileKey!==key){lastFileKey=key;loadFiles();}}
async function command(action){if(busy)return;busy=true;if(current)render(current);try{render(await api('/api/'+action,'POST'));}catch(e){error(e.message);}finally{busy=false;if(current){const message=$('error').textContent;render(current);if(message)error(message);}}}
$('start').onclick=()=>command('start');$('pause').onclick=()=>command(current?.state==='paused'?'resume':'pause');$('stop').onclick=()=>command('stop');$('window').onchange=()=>drawAll();$('files-refresh').onclick=()=>loadFiles();
async function loadFiles(){try{const files=await api('/api/files');$('files').replaceChildren();if(!files.length){const p=document.createElement('p');p.className='empty';p.textContent='종료한 측정 세션이 여기에 표시됩니다.';$('files').append(p);}for(const file of files){const a=document.createElement('a');a.className='file';a.href='/download/'+encodeURIComponent(file.name);a.textContent='↓ '+file.name;const span=document.createElement('span');span.textContent=`${(file.bytes/1024).toFixed(1)} KB${file.name.includes('recovered')?' · 비정상 종료 복구':''}`;a.append(span);$('files').append(a);}}catch(e){$('files').textContent='저장 목록을 불러오지 못했습니다.';}}
function drawAll(){
  if(!plot)return;
  const rows=history?.rows||current?.rows||[];
  const latest=current?.state==='running'?Date.now():current?.rows.at(-1)?Date.parse(current.rows.at(-1).timestamp):Date.now();
  plot.update({rows,session:current?.started_at,selection:$('window').value,latest});
}
window.addEventListener('resize',drawAll);
async function poll(){try{await api('/api/heartbeat','POST');const s=await api('/api/state');connected=true;$('connection').textContent='● 로컬 서버 연결됨';render(s);}catch(e){connected=false;$('connection').textContent='○ 서버 연결 끊김';if(current)render(current);error('서버 연결이 끊겼습니다. 마지막 화면이며, 새 측정값이 아닙니다.');}finally{setTimeout(poll,2000);}}
poll();loadFiles();
