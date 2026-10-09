// Commands are sent only by submitting this form. Editing an angle never sends it.
(() => {
  const form = document.getElementById('motor-form');
  if (!form) return;
  const $ = id => document.getElementById(id);
  let busy=false, state=null;
  function render() {
    const connected=state?.connected;
    $('motor-angle').textContent=Number.isInteger(state?.angle)?`${state.angle}°`:
      state?.reported_at?'설정 안 됨':'확인 전';
    $('motor-status').textContent=!connected?'USB 연결 안 됨':state.pending?'UNO 응답 대기':
      state.error|| (state.supported?'UNO 연결됨':'모터 상태 응답 대기');
    $('motor-connect').disabled=busy||connected;
    $('motor-check').disabled=busy||!connected||state?.pending;
    $('motor-send').disabled=busy||!connected||!state?.supported||state?.pending;
    $('motor-target').disabled=busy;
  }
  async function call(path, body) {
    const response=await fetch(path,{cache:'no-store',...(body===undefined?{}:
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const value=await response.json();
    if (!response.ok) throw Error(value.error||`HTTP ${response.status}`);
    return value;
  }
  async function command(path, body={}) {
    if (busy) return;
    busy=true; $('motor-message').textContent='UNO 응답을 확인하고 있습니다.'; render();
    try {
      state=await call(path,body);
      $('motor-message').textContent=path==='/api/motor'?`UNO가 ${state.angle}° 설정을 확인했습니다.`:
        path.endsWith('/connect')?'USB 연결 중입니다. 센서 기록은 시작하지 않습니다.':'설정 각도를 확인했습니다.';
    } catch(error) { $('motor-message').textContent=error.message; }
    finally {busy=false;render();}
  }
  $('motor-connect').onclick=()=>command('/api/motor/connect');
  $('motor-check').onclick=()=>command('/api/motor/status');
  form.onsubmit=event=>{
    event.preventDefault();
    const text=$('motor-target').value.trim(), angle=Number(text);
    if (!text||!Number.isInteger(angle)||angle<0||angle>180) {
      $('motor-message').textContent='0~180 사이의 정수를 입력하세요.';return;
    }
    command('/api/motor',{angle});
  };
  async function poll() {
    if (!busy) try { state=await call('/api/motor');render(); }
    catch(error) { state=null;render();$('motor-message').textContent=error.message; }
    setTimeout(poll,2000);
  }
  render();poll();
})();
