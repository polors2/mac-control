'use strict';

let statsRequest = false, statsData = null;
let statsTimer, statsGeneration=0, fanChanging=false, fanData=null, fanControl=false, fanConfirmedAt=0;
let fanControllerInfo={}, targetDirty=false;
const viewerId=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
const finite = value => typeof value === 'number' && Number.isFinite(value);
const rate = value => {
  if (!finite(value)) return '—';
  if (value >= 1e9) return `${(value/1e9).toFixed(1)} GB/s`;
  if (value >= 1e6) return `${(value/1e6).toFixed(1)} MB/s`;
  if (value >= 1e3) return `${(value/1e3).toFixed(1)} KB/s`;
  return `${Math.round(value)} B/s`;
};

function historyChart(id, history, series, maximum=100, isNetwork=false) {
  const chart=$(`#${id}`);
  const end=history.length ? history[history.length-1].time:Date.now()/1000;
  const begin=end-120;
  const x=time=>5+Math.max(0,Math.min(1,(time-begin)/120))*280;
  const y=value=>96-Math.max(0,Math.min(1,value/maximum))*82;
  const topLabel=isNetwork ? rate(maximum):'100%';
  let content=`<defs>${series.map(line=>`<linearGradient id="${id}-${line.key}-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${line.color}" stop-opacity=".19"/><stop offset="100%" stop-color="${line.color}" stop-opacity=".01"/></linearGradient>`).join('')}</defs>`;
  for (const height of [14,55,96]) content+=`<path d="M0 ${height}H288" stroke="#e5e9de" stroke-width=".7" ${height===96 ? '':'stroke-dasharray="3 4"'}/>`;
  content+=`<text x="319" y="17" text-anchor="end" fill="#9ba58f" font-size="7" font-family="sans-serif">${topLabel}</text><text x="319" y="98" text-anchor="end" fill="#9ba58f" font-size="7" font-family="sans-serif">0</text>`;
  for (const line of series) {
    let groups=[], group=[], lastTime=null;
    for (const point of history) {
      const value=point[line.key];
      if (!finite(value) || (lastTime!==null && point.time-lastTime>3)) {
        if(group.length) groups.push(group); group=[];
      }
      if (finite(value) && point.time>=begin) group.push([x(point.time),y(value)]);
      lastTime=point.time;
    }
    if(group.length) groups.push(group);
    for (const points of groups) {
      if (points.length<2) continue;
      const path=points.map((point,index)=>`${index ? 'L':'M'}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(' ');
      content+=`<path d="${path} L${points[points.length-1][0].toFixed(2)},96 L${points[0][0].toFixed(2)},96 Z" fill="url(#${id}-${line.key}-fill)"/><path d="${path}" fill="none" stroke="${line.color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`;
    }
    const last=history[history.length-1];
    if (last && finite(last[line.key])) content+=`<circle cx="${x(last.time).toFixed(2)}" cy="${y(last[line.key]).toFixed(2)}" r="2.5" fill="${line.color}" stroke="#fcfdf7" stroke-width="1.2"/>`;
  }
  chart.innerHTML=content;
}

function renderStats(data) {
  const history=data?.history || [], last=history[history.length-1];
  const live=!!data?.running && !data?.error;
  $('#stats-status').classList.toggle('is-live',live);
  $('#stats-status span').textContent=!authenticated ? 'Sign in to see statistics':data?.error ? 'Reconnecting to statistics':live ? 'Live · 2s':history.length ? 'Waiting for your Mac':'Collecting samples…';
  $('.stats-section').classList.toggle('stats-stale',!live);
  $('#cpu-stat-value').textContent=finite(last?.cpu) ? Math.round(last.cpu):'—';
  $('#cpu-stat-detail').textContent=finite(last?.cpu) ? 'Total CPU utilization':history.length>1 ? 'CPU metrics unavailable':'Collecting a sample…';
  for(const [prefix,key,vendor] of [['gpu','intelGpu','Intel'],['amd','amdGpu','AMD']]) {
    const info=last?.[`${key}Info`], value=last?.[key], sleeping=info?.state==='sleeping';
    $(`#${prefix}-stat-value`).textContent=finite(value) ? Math.round(value):'—';
    $(`#${prefix}-stat-name`).textContent=info?.name || (vendor==='Intel' ? 'INTEGRATED':'DISCRETE');
    $(`#${prefix}-stat-name`).title=info?.name || `${vendor} GPU`;
    $(`#${prefix}-stat-detail`).textContent=sleeping ? 'Sleeping · powered down' : finite(value) ? 'Active · GPU utilization' : info ? 'Utilization not reported' : history.length ? `${vendor} GPU not detected`:`Reading ${vendor} graphics…`;
    $(`#${prefix}-stat-detail`).title=sleeping ? 'macOS has powered down this GPU to save energy. Its utilization is zero while powered off.' : 'Live utilization reported by the macOS graphics driver.';
    $(`#${prefix}-stat-value`).closest('.stat-card').classList.toggle('gpu-sleeping',sleeping);
  }
  for(const [element,key,label,gpuKey] of [['cpu','cpuTemperature','CPU temperature',null],['gpu','intelTemperature','Intel GPU','intelGpuInfo'],['amd','amdTemperature','AMD GPU','amdGpuInfo']]) {
    const sensor=last?.[key], sleeping=gpuKey && last?.[gpuKey]?.state==='sleeping';
    const output=$(`#${element}-temperature`);
    output.textContent=finite(sensor?.celsius) ? `${Math.round(sensor.celsius)}°C`:sleeping ? 'Sleeping':'—°C';
    output.classList.toggle('temperature-word',!finite(sensor?.celsius) && !!sleeping);
    $(`#${element}-temperature-label`).textContent=sensor?.label ? sensor.label+(sleeping ? ' · sleeping':'') : sleeping ? 'Powered down by macOS':label;
    output.title=finite(sensor?.celsius) ? `${sensor.celsius.toFixed(1)}°C · ${sensor.label}`:sleeping ? 'Temperature unavailable while the GPU is powered down':'Temperature sensor unavailable';
  }
  if(!last || last.time>=fanConfirmedAt) renderFans(last,data?.fanControl,data?.fanController);
  else renderFans(fanData,data?.fanControl,fanControllerInfo);
  $('#download-stat-value').textContent=rate(last?.download);
  $('#upload-stat-value').textContent=rate(last?.upload);
  $('#network-stat-detail').textContent=last?.interfaces?.length ? last.interfaces.join(' + '):'Bytes per second';
  const values=history.flatMap(point=>[point.download,point.upload]).filter(finite);
  const peak=Math.max(1000,...values);
  const exponent=10**Math.floor(Math.log10(peak));
  const maximum=Math.ceil(peak/exponent)*exponent;
  historyChart('cpu-chart',history,[{key:'cpu',color:'#8ca767'}]);
  historyChart('gpu-chart',history,[{key:'intelGpu',color:'#a79abd'}]);
  historyChart('amd-chart',history,[{key:'amdGpu',color:'#c49b79'}]);
  historyChart('network-chart',history,[{key:'download',color:'#7da69b'},{key:'upload',color:'#c7a173'}],maximum,true);
  $('#cpu-chart').setAttribute('aria-label',`CPU utilization over the last two minutes. Current: ${finite(last?.cpu) ? last.cpu+' percent':'unavailable'}.`);
  $('#gpu-chart').setAttribute('aria-label',`Intel GPU utilization over the last two minutes. Current: ${finite(last?.intelGpu) ? last.intelGpu+' percent':'unavailable'}.`);
  $('#amd-chart').setAttribute('aria-label',`AMD GPU utilization over the last two minutes. Current: ${finite(last?.amdGpu) ? last.amdGpu+' percent':'unavailable'}. ${last?.amdGpuInfo?.state==='sleeping' ? 'GPU powered down by macOS.':''}`);
  $('#network-chart').setAttribute('aria-label',`Network traffic over the last two minutes. Download ${rate(last?.download)}, upload ${rate(last?.upload)}.`);
}

function fanMode() {
  return ['target','constant'].includes(fanControllerInfo.controllerMode) ? fanControllerInfo.controllerMode:fanData?.fanMode;
}
const fanDrafts=new Map();
let queuedFanRequest=null;
function renderConstantFans(fans,supported) {
  const container=$('#constant-fans');
  if(container.dataset.ids!==fans.map(fan=>fan.id).join(',')) {
    container.replaceChildren();container.dataset.ids=fans.map(fan=>fan.id).join(',');
    for(const fan of fans) {
      const row=document.createElement('div');row.className='constant-fan-row';
      const heading=document.createElement('div');heading.className='constant-fan-heading';
      const label=document.createElement('label');label.htmlFor=`fan-speed-${fan.id}`;label.textContent=fan.name;
      const output=document.createElement('output');output.id=`fan-speed-value-${fan.id}`;output.htmlFor=label.htmlFor;
      heading.append(label,output);
      const slider=document.createElement('input');slider.type='range';slider.step='1';slider.id=label.htmlFor;slider.setAttribute('aria-label',`${fan.name} constant RPM`);
      slider.addEventListener('input',()=>{fanDrafts.set(fan.id,Number(slider.value));updateFanSlider(fan.id);});
      slider.addEventListener('change',()=>applyFanMode('constant'));
      const limits=document.createElement('div');limits.className='constant-fan-limits';limits.id=`fan-limits-${fan.id}`;
      row.append(heading,slider,limits);container.append(row);
    }
  }
  for(const fan of fans) {
    const slider=$(`#fan-speed-${fan.id}`);
    const bounded=finite(fan.minimum) && finite(fan.maximum) && fan.minimum>=500 && fan.maximum>=fan.minimum && fan.maximum<16384;
    slider.disabled=!authenticated || !supported || !bounded;
    if(!bounded) {$(`#fan-limits-${fan.id}`).textContent='Firmware limits unavailable';continue;}
    slider.min=Math.ceil(fan.minimum);slider.max=Math.floor(fan.maximum);
    if(!fanDrafts.has(fan.id) && document.activeElement!==slider) slider.value=Math.max(Number(slider.min),Math.min(Number(slider.max),fan.target || fan.rpm || fan.minimum));
    if(fanDrafts.has(fan.id)) slider.value=fanDrafts.get(fan.id);
    $(`#fan-limits-${fan.id}`).textContent=`${Number(slider.min).toLocaleString()} – ${Number(slider.max).toLocaleString()} RPM`;
    updateFanSlider(fan.id);
  }
}
function updateFanSlider(id) {
  const slider=$(`#fan-speed-${id}`), value=Number(slider.value);
  $(`#fan-speed-value-${id}`).textContent=`${value.toLocaleString()} RPM`;
  slider.style.setProperty('--fill',`${100*(value-Number(slider.min))/(Number(slider.max)-Number(slider.min) || 1)}%`);
  slider.setAttribute('aria-valuetext',`${value.toLocaleString()} RPM`);
}
function renderFans(data, installed, controller=fanControllerInfo) {
  fanData=data; fanControl=!!installed;fanControllerInfo=controller || {};
  const mode=fanMode(), fans=data?.fans || [];
  const targetSupported=!!installed && fanControllerInfo.version>=2;
  const constantSupported=!!installed && fanControllerInfo.version>=3;
  for(const name of ['auto','constant','target','max']) {
    $(`#fan-${name}`).setAttribute('aria-pressed',String(mode===name));
    $(`#fan-${name}`).disabled=!authenticated || !installed || !fans.length || (name==='target' && !targetSupported) || (name==='constant' && !constantSupported);
  }
  $('#target-form').hidden=mode!=='target';
  $('#target-curve-preview').hidden=mode!=='target';
  $('#constant-controls').hidden=mode!=='constant';
  $('#cpu-target-input').disabled=!authenticated || !targetSupported;
  $('#fan-setup').hidden=constantSupported;
  $('#fan-setup').textContent=installed ? 'Update helper for Constant mode ↗':'Enable fan control ↗';
  if(!targetDirty && document.activeElement!==$('#cpu-target-input') && finite(fanControllerInfo.targetTemperature)) $('#cpu-target-input').value=fanControllerInfo.targetTemperature;
  updateCurveLabel();renderConstantFans(fans,constantSupported);
  $('.fan-section').classList.toggle('changing',fanChanging);
  const ramping=fans.some(fan=>finite(fan.rpm) && finite(fan.maximum) && fan.rpm<fan.maximum-200);
  $('#fan-mode-description').textContent=mode==='target' ? `CPU target ${fanControllerInfo.targetTemperature}°C · ${fanControllerInfo.safetyOverride ? 'maximum cooling':'adaptive fan curve'}` : mode==='constant' ? 'Fixed RPM for each fan · release a slider to save.' : mode==='auto' ? 'Apple is managing fan speed.' : mode==='max' ? ramping ? 'Maximum selected · fans are ramping up.':'All fans at their firmware maximum.' : mode==='custom' ? 'A custom fan override is active.' : 'Apple manages fan speed by default.';
  if(fanControllerInfo.controllerError) $('#fan-mode-description').textContent=fanControllerInfo.controllerError;
  const readings=$('#fan-readings');readings.replaceChildren();
  if(!fans.length) {readings.textContent=data ? 'Fan readings unavailable':'Reading fan speeds…';return;}
  for(const fan of fans) {
    const reading=document.createElement('div');reading.className='fan-reading';
    const name=document.createElement('span');name.textContent=fan.name;
    const rpm=document.createElement('strong');rpm.textContent=finite(fan.rpm) ? `${Math.round(fan.rpm).toLocaleString()} RPM`:'— RPM';
    const max=document.createElement('small');max.textContent=finite(fan.maximum) ? `/ ${Math.round(fan.maximum).toLocaleString()} max`:'';
    reading.append(name,rpm,max);readings.append(reading);
  }
}
function updateCurveLabel() {
  const goal=Number($('#cpu-target-input').value);
  if(Number.isFinite(goal) && goal>=50 && goal<=85) $('#target-curve-label').textContent=`Base curve: ${goal-15}°C → ${goal}°C → max at ${Math.min(goal+6,90)}°C. Adapts to load.`;
}
$('#cpu-target-input').addEventListener('input',()=>{targetDirty=true;$('#cpu-target-input').removeAttribute('aria-invalid');updateCurveLabel();});
$('#cpu-target-input').addEventListener('blur',()=>{if(targetDirty && fanMode()==='target') applyFanMode('target');});
$('#cpu-target-input').addEventListener('keydown',event=>{if(event.key==='Enter') {event.preventDefault();event.target.blur();}});
async function applyFanMode(mode) {
  let request={mode};
  if(mode==='target') {
    const field=$('#cpu-target-input'), goal=Number(field.value);
    if(!field.value.trim() || !Number.isFinite(goal) || goal<50 || goal>85) {field.setAttribute('aria-invalid','true');toast('Choose a CPU temperature from 50 to 85°C.',true);return;}
    request.temperature=goal;
  } else if(mode==='constant') {
    const fans=fanData?.fans || [];
    if(!fans.length || fans.some(fan=>!finite(fan.minimum) || !finite(fan.maximum))) {toast('Fan limits are unavailable. Try again after the next reading.',true);return;}
    request.speeds=fans.map(fan=>Math.round(Math.max(Math.ceil(fan.minimum),Math.min(Math.floor(fan.maximum),fanDrafts.get(fan.id) ?? fan.target ?? fan.rpm ?? fan.minimum))));
  }
  if(fanChanging) {queuedFanRequest=request;return;}
  await sendFanRequest(request);
}
async function sendFanRequest(request) {
  fanChanging=true;renderFans(fanData,fanControl);
  try {
    const result=await api('/api/fans',request);
    fanConfirmedAt=result.time || 0;
    if(request.mode!=='target' || Number($('#cpu-target-input').value)===request.temperature) targetDirty=false;
    if(request.mode==='constant') for(const [index,fan] of (result.fans || []).entries()) {
      if(fanDrafts.get(fan.id)===request.speeds[index]) fanDrafts.delete(fan.id);
    }
    renderFans(result,true,result);
    toast(request.mode==='target' ? `CPU cooling target set to ${request.temperature}°C.`:request.mode==='constant' ? 'Constant fan speeds saved.':request.mode==='auto' ? 'Apple is managing the fans.':'All fans set to their firmware maximum.');
  } catch(error) {toast(error.message,true);}
  finally {
    fanChanging=false;renderFans(fanData,fanControl);
    const next=queuedFanRequest;queuedFanRequest=null;
    if(next) await sendFanRequest(next);
  }
}
for(const mode of ['auto','constant','target','max']) $(`#fan-${mode}`).addEventListener('click',()=>applyFanMode(mode));
$('#target-form').addEventListener('submit',event=>{event.preventDefault();$('#cpu-target-input').blur();});
$('#fan-setup').addEventListener('click',async()=>{
  try {
    const info=await api('/api/connection');$('#fan-installer-path').textContent=info.fanInstaller;
    $('#fan-help-title').textContent=fanControl ? 'Update the fan helper.':'Enable fan control.';
    $('#fan-help-intro').textContent=fanControl ? 'Run the installer once more to add independent Constant RPM controls. macOS needs administrator approval to replace the helper.':'Install the administrator helper once to enable Constant, Max, and CPU Target fan modes.';
    $('#fan-help-dialog').showModal();
  } catch(error) {toast(error.message,true);}
});

function leaveViewer() {
  fetch('/api/stats/leave',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({viewer:viewerId}),keepalive:true}).catch(()=>{});
}
function pauseStats() {
  clearTimeout(statsTimer); statsGeneration++; leaveViewer();
  $('#stats-status').classList.remove('is-live');
  $('#stats-status span').textContent=authenticated ? 'Paused while away':'Sign in to see statistics';
  $('.stats-section').classList.add('stats-stale');
}
function scheduleStats(delay=2000) {
  clearTimeout(statsTimer);
  if(authenticated && !document.hidden && !statsRequest) statsTimer=setTimeout(refreshStats,delay);
}
async function refreshStats() {
  if(!authenticated || document.hidden || statsRequest) return;
  statsRequest=true;
  const generation=statsGeneration;
  try {
    const result=await api(`/api/stats?viewer=${viewerId}`);
    if(generation!==statsGeneration || document.hidden || !authenticated) {leaveViewer();return;}
    statsData=result; renderStats(statsData);
  } catch(error) {
    renderStats({...statsData,running:false,error:error.message});
    if(error.status===401) {authenticated=false;setOnline(false);showLogin();}
  } finally {statsRequest=false;scheduleStats();}
}
renderStats(null);
scheduleStats(0);
document.addEventListener('dashboard:resume',()=>scheduleStats(0));
document.addEventListener('dashboard:pause',pauseStats);
document.addEventListener('visibilitychange',()=>document.hidden ? pauseStats():scheduleStats(0));
window.addEventListener('pagehide',pauseStats);
window.addEventListener('pageshow',()=>scheduleStats(0));
