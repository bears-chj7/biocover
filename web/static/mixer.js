(() => {
  const panel=document.getElementById('mixer-panel');
  if (!panel) return;
  const $=id=>document.getElementById(id);
  const fields=['window_s','spread_delta','rise_delta','rise_pct','sigma','confirmations','cooldown_s','dwell_s'];
  let state=null,busy=false,initialized=false,dirty=false;
  const names={off:'꺼짐',warming:'기준 수집',watching:'감시 중',moving:'각도 전송',holding:'위치 대기',cooldown:'재구동 대기',error:'중단 · 확인 필요'};
  const n=value=>Number.isFinite(value)?value.toFixed(1):'—';
  function fill(settings) {
    for(const key of fields) $('mix-'+key).value=settings[key];
    $('mix-angles').value=settings.angles.join(', ');dirty=false;initialized=true;
  }
  function render() {
    $('mixer-state').textContent=names[state?.phase]||'연결 확인 중';
    $('mixer-status').textContent=(state?.message||'')+(state?.phase==='cooldown'?` · ${Math.ceil(state.cooldown_remaining_s)}초 남음`:'');
    $('mixer-enable').disabled=busy||!state||state.enabled||dirty;
    // Off remains available during motion; it cancels subsequent commands.
    $('mixer-disable').disabled=busy||!state?.enabled;
    $('mixer-save').disabled=busy||!state||state.enabled;
    for(const key of [...fields,'angles']) $('mix-'+key).disabled=busy||state?.enabled;
    const m=state?.metrics||{};
    $('mixer-metrics').textContent=`최근 판단값 · 평균 ${n(m.mean)} / 기준 ${n(m.baseline_mean)} / 감지선 ${n(m.mean_limit)} raw · 격차 ${n(m.spread)} / 기준 ${n(m.baseline_spread)} / 감지선 ${n(m.spread_limit)} raw · 연속 ${m.confirmations||0}회`;
    $('mixer-events').replaceChildren();
    const labels={enabled:'자동 교반 켬',disabled:'자동 교반 끔',trigger:'이상 변화 감지',command:'각도 전송',confirmed:'UNO 확인',completed:'교반 완료',error:'중단'};
    for(const e of (state?.events||[]).slice(-8).reverse()) {
      const li=document.createElement('li');
      li.textContent=`${new Date(e.timestamp).toLocaleTimeString('ko-KR',{hour12:false})} · ${labels[e.kind]||e.kind}${e.angle===undefined?'':` · ${e.angle}°`}${e.message?' · '+e.message:''}`;
      $('mixer-events').append(li);
    }
  }
  async function api(path,body) {
    const response=await fetch(path,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;
  }
  async function command(action,body={}) {
    if(busy)return;busy=true;render();
    try {state=await api('/api/mixer/'+action,body);if(action==='settings')fill(state.settings);$('mixer-message').textContent=action==='settings'?'설정을 저장했습니다.':state.message;}
    catch(e){$('mixer-message').textContent=e.message;}
    finally{busy=false;render();}
  }
  $('mixer-settings').oninput=()=>{dirty=true;$('mixer-message').textContent='변경한 설정을 저장한 뒤 자동 교반을 켜세요.';render();};
  $('mixer-settings').onsubmit=e=>{
    e.preventDefault();const settings={};
    for(const key of fields) {const value=$('mix-'+key).value;if(!value.trim())return;settings[key]=Number(value);}
    const parts=$('mix-angles').value.split(',').map(s=>s.trim());
    if(!parts.every(s=>/^\d+$/.test(s))){$('mixer-message').textContent='각도를 쉼표로 구분하세요. 예: 0, 180, 0';return;}
    settings.angles=parts.map(Number);command('settings',settings);
  };
  $('mixer-enable').onclick=()=>command('enable');
  $('mixer-disable').onclick=()=>command('disable');
  async function poll() {
    if(!busy)try{state=await api('/api/mixer');if(!initialized)fill(state.settings);render();}
    catch(e){state=null;render();$('mixer-message').textContent=e.message;}
    setTimeout(poll,1000);
  }
  render();poll();
})();
