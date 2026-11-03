'use strict';

let statsRequest = false, statsData = null;
let statsTimer, statsGeneration=0, fanChanging=false, fanData=null, fanControl=false, fanConfirmedAt=0;
let fanControllerInfo={}, targetDirty=false;
const viewerId=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
const finite = value => typeof value === 'number' && Number.isFinite(value);
const memorySize = value => finite(value) ? `${(value/2**30).toFixed(1)} GB`:'—';
const rate = value => {
  if (!finite(value)) return '—';
  if (value >= 1e9) return `${(value/1e9).toFixed(1)} GB/s`;
  if (value >= 1e6) return `${(value/1e6).toFixed(1)} MB/s`;
  if (value >= 1e3) return `${(value/1e3).toFixed(1)} KB/s`;
  return `${Math.round(value)} B/s`;
};

function historyChart(id, history, series, maximum=100, isNetwork=false) {
  const chart=$(`#${id}`);
  const width=Math.round(chart.getBoundingClientRect().width || 320), height=Math.round(chart.getBoundingClientRect().height || 114);
  chart.setAttribute('viewBox',`0 0 ${width} ${height}`);
  const baseline=height-(id==='activity-chart' ? 14:8), top=id==='activity-chart' ? 24:18, right=Math.max(44,width-(isNetwork ? 92:56));
  const end=history.length ? history[history.length-1].time:Date.now()/1000;
  const begin=end-120;
  const x=time=>4+Math.max(0,Math.min(1,(time-begin)/120))*(right-4);
  const y=value=>baseline-Math.max(0,Math.min(1,value/maximum))*(baseline-top);
  const topLabel=isNetwork ? rate(maximum):'100%';
  let content=`<defs>${series.map(line=>`<linearGradient id="${id}-${line.key}-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${line.color}" stop-opacity=".19"/><stop offset="100%" stop-color="${line.color}" stop-opacity=".01"/></linearGradient>`).join('')}</defs>`;
  for (const height of [top,(top+baseline)/2,baseline]) content+=`<path d="M4 ${height}H${right}" stroke="#d1dcd0" stroke-width=".7" ${height===baseline ? '':'stroke-dasharray="3 4"'}/>`;
  content+=`<text x="${width-2}" y="20" text-anchor="end" fill="#526358" font-size="14" font-family="sans-serif">${topLabel}</text><text x="${width-2}" y="${baseline+4}" text-anchor="end" fill="#526358" font-size="14" font-family="sans-serif">0</text>`;
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
      content+=`<path d="${path} L${points[points.length-1][0].toFixed(2)},${baseline} L${points[0][0].toFixed(2)},${baseline} Z" fill="url(#${id}-${line.key}-fill)"/><path d="${path}" fill="none" stroke="${line.color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`;
    }
    const last=history[history.length-1];
    if (last && finite(last[line.key])) content+=`<circle cx="${x(last.time).toFixed(2)}" cy="${y(last[line.key]).toFixed(2)}" r="2.5" fill="${line.color}" stroke="#fcfdf7" stroke-width="1.2"/>`;
  }
  chart.innerHTML=content;
  const names={cpu:'CPU',intelGpu:'Intel GPU',amdGpu:'AMD GPU',ram:'RAM used',download:'↓ Download',upload:'↑ Upload'};
  inspectChart(chart,{points:history.filter(point=>point.time>=begin),start:begin,end,left:4,right,top,bottom:baseline,width,x,y,maxDistance:3,
    series:series.map(line=>({...line,name:line.name || names[line.key],format:isNetwork ? rate:value=>`${value.toFixed(1)}%`}))});
}

function renderStats(data) {
  const history=data?.history || [], last=history[history.length-1];
  const live=!!data?.running && !data?.error;
  $('#stats-status').classList.toggle('is-live',live);
  $('#stats-status span').textContent=!authenticated ? 'Sign in to see statistics':data?.error ? 'Reconnecting to statistics':live ? 'Live · 2s':history.length ? 'Waiting for your Mac':'Collecting samples…';
  $('.stats-section').classList.toggle('stats-stale',!live);
  $('#cpu-stat-value').textContent=finite(last?.cpu) ? Math.round(last.cpu):'—';
  $('#cpu-stat-detail').textContent=finite(last?.cpu) ? 'Total CPU utilization':history.length>1 ? 'CPU metrics unavailable':'Collecting a sample…';
  $('#ram-stat-value').textContent=finite(last?.ram) ? Math.round(last.ram):'—';
  const memory=last?.memory;
  const available=finite(memory?.used) && finite(memory?.total) && memory.total>0 && memory.used>=0 && memory.used<=memory.total ? memory.total-memory.used:null;
  $('#ram-free-value').textContent=finite(available) ? (available/2**30).toFixed(1):'—';
  $('#ram-stat-detail').textContent=last?.memory ? `${memorySize(last.memory.used)} / ${memorySize(last.memory.total)} used`:'Memory metrics unavailable';
  $('#ram-stat-value').closest('.stat-card').title=finite(available) ? `${memorySize(available)} free to use · ${$('#ram-stat-detail').textContent} · Includes reclaimable cache` : 'Memory metrics unavailable';
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
  historyChart('ram-chart',history,[{key:'ram',color:'#6e9fb7'}]);
  historyChart('network-chart',history,[{key:'download',color:'#7da69b'},{key:'upload',color:'#c7a173'}],maximum,true);
  $('#cpu-chart').setAttribute('aria-label',`CPU utilization over the last two minutes. Current: ${finite(last?.cpu) ? last.cpu+' percent':'unavailable'}.`);
  $('#gpu-chart').setAttribute('aria-label',`Intel GPU utilization over the last two minutes. Current: ${finite(last?.intelGpu) ? last.intelGpu+' percent':'unavailable'}.`);
  $('#amd-chart').setAttribute('aria-label',`AMD GPU utilization over the last two minutes. Current: ${finite(last?.amdGpu) ? last.amdGpu+' percent':'unavailable'}. ${last?.amdGpuInfo?.state==='sleeping' ? 'GPU powered down by macOS.':''}`);
  $('#network-chart').setAttribute('aria-label',`Network traffic over the last two minutes. Download ${rate(last?.download)}, upload ${rate(last?.upload)}.`);
  $('#ram-chart').setAttribute('aria-label',`RAM utilization over the last two minutes. Current: ${finite(last?.ram) ? last.ram+' percent':'unavailable'}. ${$('#ram-stat-detail').textContent}.`);
  renderActivityDetail(data);
}

const activityViews={
  cpu:{name:'CPU',lines:[{key:'cpu',name:'CPU',color:'#8ca767'}]},
  gpu:{name:'Intel GPU',lines:[{key:'intelGpu',name:'Intel GPU',color:'#a79abd'}]},
  amd:{name:'AMD GPU',lines:[{key:'amdGpu',name:'AMD GPU',color:'#c49b79'}]},
  ram:{name:'RAM',lines:[{key:'ram',name:'Memory utilization',color:'#6e9fb7'}]},
  network:{name:'Network',lines:[{key:'download',name:'↓ Download',color:'#7da69b'},{key:'upload',name:'↑ Upload',color:'#c7a173'}]}
};
let expandedActivity=null, activitySource=null, activityMotion=null;
const reducedActivityMotion=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
function renderActivityDetail(data) {
  if(!expandedActivity || !$('#activity-dialog').open) return;
  const view=activityViews[expandedActivity], history=data?.history || [], last=history.at(-1);
  const power=typeof view.renderDetail==='function';
  $('#activity-dialog').classList.toggle('is-power-detail',power);
  $('#power-detail-windows').hidden=!power || expandedActivity==='power-energy';
  if(power) {view.renderDetail();return;}
  $('#activity-dialog .eyebrow').textContent='SYSTEM ACTIVITY · LAST TWO MINUTES';
  $('#activity-chart').setAttribute('viewBox','0 0 320 114');
  $('#activity-dialog .activity-time span:first-child').textContent='2 min ago';
  const network=expandedActivity==='network', format=network ? rate:value=>finite(value) ? `${value.toFixed(1)}%`:'—';
  $('#activity-title').textContent=view.name;
  $('#activity-detail').textContent=network ? $('#network-stat-detail').textContent:$(`#${expandedActivity}-stat-detail`).textContent;
  const memory=last?.memory, showMemory=expandedActivity==='ram';
  const validMemory=finite(memory?.used) && finite(memory?.total) && memory.total>0 && memory.used>=0 && memory.used<=memory.total;
  const available=validMemory ? memory.total-memory.used:null;
  const availablePercent=validMemory ? 100*available/memory.total:0;
  $('#activity-summary').classList.toggle('has-memory',showMemory);
  $('#memory-available').hidden=!showMemory;
  $('#memory-available-value').textContent=memorySize(available);
  $('#memory-available-total').textContent=validMemory ? `of ${memorySize(memory.total)} installed`:'Waiting for memory data…';
  $('#memory-available-percent').textContent=validMemory ? `${Math.round(availablePercent)}%`:'—';
  $('#memory-available-ring').style.setProperty('--memory-free',`${availablePercent}%`);
  $('#memory-available-ring').classList.toggle('is-unavailable',!validMemory);
  $('#memory-available').setAttribute('aria-label',validMemory ? `${memorySize(available)} free to use out of ${memorySize(memory.total)} installed. Includes reclaimable cache.`:'Available memory is not yet known.');
  const container=$('#activity-values');container.replaceChildren();
  for(const line of view.lines) {
    const samples=history.filter(point=>point.time>=(last?.time || 0)-120).map(point=>point[line.key]).filter(finite);
    const group=document.createElement('div'), title=document.createElement('h3');title.textContent=line.name;group.append(title);
    for(const [label,value] of [['Now',last?.[line.key]],['Average',samples.length ? samples.reduce((sum,v)=>sum+v,0)/samples.length:null],['Peak',samples.length ? Math.max(...samples):null]]) {
      const row=document.createElement('p'), name=document.createElement('span'), output=document.createElement('strong');
      name.textContent=label;output.textContent=format(value);row.append(name,output);group.append(row);
    }
    container.append(group);
  }
  if(expandedActivity==='ram' && last?.memory) {
    const group=document.createElement('div'), title=document.createElement('h3');
    title.textContent='Physical memory';group.append(title);
    for(const [label,value] of [['Used',last.memory.used],['Installed',last.memory.total],['Compressed',last.memory.compressed]]) {
      const row=document.createElement('p'), name=document.createElement('span'), output=document.createElement('strong');
      name.textContent=label;output.textContent=memorySize(value);row.append(name,output);group.append(row);
    }
    container.append(group);
  }
  const values=history.flatMap(point=>view.lines.map(line=>point[line.key])).filter(finite);
  const peak=Math.max(1000,...values), exponent=10**Math.floor(Math.log10(peak));
  historyChart('activity-chart',history,view.lines,network ? Math.ceil(peak/exponent)*exponent:100,network);
  $('#activity-chart').setAttribute('aria-label',`${view.name} over the last two minutes. ${view.lines.map(line=>`${line.name}: ${format(last?.[line.key])}`).join('. ')}`);
  $('#activity-status').textContent=!authenticated ? 'Sign in to see statistics.':data?.error ? 'Reconnecting to statistics.':data?.running ? 'Live · updates every 2 seconds. Gaps indicate missing samples.':'Sampling paused. Gaps indicate missing samples.';
}
// A shared graph flies between its real tile and detail bounds. Keep this in
// the dialog's top layer so it remains above the backdrop in every browser.
function flyActivity(opening, sourceCard, sourceChart) {
  const dialog=$('#activity-dialog'), chart=$('#activity-chart');
  const cardBounds=sourceCard.getBoundingClientRect(), chartBounds=sourceChart.getBoundingClientRect();
  if(reducedActivityMotion() || !chartBounds.width || !chartBounds.height) return Promise.resolve();
  const panelBounds=dialog.getBoundingClientRect(), detailBounds=chart.getBoundingClientRect();
  const flight=document.createElement('div');flight.className='activity-flight';flight.setAttribute('aria-hidden','true');
  const panel=document.createElement('div');panel.className='activity-flight-panel';
  const graph=chart.cloneNode(true);graph.removeAttribute('id');graph.classList.add('activity-flight-chart');
  // Gradient IDs must be unique while both copies are on screen.
  graph.innerHTML=graph.innerHTML.replaceAll('activity-chart-', 'activity-flight-');
  flight.append(panel,graph);dialog.append(flight);
  dialog.classList.add('is-transitioning',opening ? 'is-opening':'is-closing');
  const duration=opening ? 620:460, easing='cubic-bezier(.22,.8,.18,1)';
  const animations=[];
  for(const [element,from,to] of [[panel,cardBounds,panelBounds],[graph,chartBounds,detailBounds]]) {
    Object.assign(element.style,{left:`${to.left}px`,top:`${to.top}px`,width:`${to.width}px`,height:`${to.height}px`});
    const small={transform:`translate(${from.left-to.left}px,${from.top-to.top}px) scale(${from.width/to.width},${from.height/to.height})`};
    const large={transform:'translate(0,0) scale(1,1)'};
    if(element===panel) {small.borderRadius='16px';large.borderRadius=getComputedStyle(dialog).borderRadius;}
    animations.push(element.animate(opening ? [small,large]:[large,small],{duration,easing,fill:'both'}));
  }
  for(const child of dialog.children) {
    if(child===flight || child===chart) continue;
    animations.push(child.animate(opening ? [{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}]:[{opacity:1},{opacity:0}],
      {duration:opening ? 240:120,delay:opening ? 300:0,fill:'both',easing:'ease-out'}));
  }
  let cleanup, cleaned=false;
  const done=Promise.all(animations.map(animation=>animation.finished)).catch(()=>{}).finally(()=>cleanup());
  cleanup=()=>{
    if(cleaned) return;
    cleaned=true;
    animations.forEach(animation=>animation.cancel());flight.remove();
    dialog.classList.remove('is-transitioning','is-opening','is-closing');
    if(activityMotion?.flight===flight) activityMotion=null;
  };
  activityMotion={flight,cancel:cleanup,done};
  return done;
}
async function closeActivity() {
  const dialog=$('#activity-dialog');
  if(!dialog.open || dialog.classList.contains('is-closing')) return;
  activityMotion?.cancel();
  document.body.classList.remove('activity-immersed');
  if(activitySource?.isConnected) await flyActivity(false,activitySource.closest('.stat-card,.power-card'),activitySourceChart());
  if(dialog.open) dialog.close();
}
function activitySourceChart() {
  return $(activityViews[expandedActivity].sourceChart || `#${expandedActivity}-chart`);
}
document.querySelectorAll('[data-activity]').forEach(button=>button.addEventListener('click',()=>{
  if($('#activity-dialog').open) return;
  expandedActivity=button.dataset.activity;
  activitySource=button;
  button.setAttribute('aria-expanded','true');
  $('#activity-dialog').showModal();renderActivityDetail(statsData);
  flyActivity(true,button.closest('.stat-card,.power-card'),activitySourceChart());
  document.body.classList.add('activity-immersed');
}));
$('#activity-dialog form').addEventListener('submit',event=>{event.preventDefault();closeActivity();});
$('#activity-dialog').addEventListener('cancel',event=>{event.preventDefault();closeActivity();});
$('#activity-dialog').addEventListener('close',()=>{
  activityMotion?.cancel();
  document.body.classList.remove('activity-immersed');
  document.querySelectorAll('[data-activity]').forEach(button=>button.setAttribute('aria-expanded','false'));
  activitySource?.focus({preventScroll:true});
  expandedActivity=null;activitySource=null;
});
window.addEventListener('resize',()=>{activityMotion?.cancel();renderStats(statsData);});
document.addEventListener('dashboard:pause',()=>{if($('#activity-dialog').open) $('#activity-dialog').close();});

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
  $('#fan-setup').hidden=!!installed && fanControllerInfo.version>=4;
  $('#fan-setup').textContent=installed ? 'Update helper for predictive Target ↗':'Enable fan control ↗';
  if(!targetDirty && document.activeElement!==$('#cpu-target-input') && finite(fanControllerInfo.targetTemperature)) $('#cpu-target-input').value=fanControllerInfo.targetTemperature;
  updateCurveLabel();renderConstantFans(fans,constantSupported);
  $('.fan-section').classList.toggle('changing',fanChanging);
  const ramping=fans.some(fan=>finite(fan.rpm) && finite(fan.maximum) && fan.rpm<fan.maximum-200);
  $('#fan-mode-description').textContent=mode==='target' ? `CPU target ${fanControllerInfo.targetTemperature}°C · ${fanControllerInfo.safetyOverride ? 'maximum cooling':fanControllerInfo.targetAlgorithm==='predictive' ? 'predictive cooling':'legacy fan curve'}` : mode==='constant' ? 'Fixed RPM for each fan · release a slider to save.' : mode==='auto' ? 'Apple is managing fan speed.' : mode==='max' ? ramping ? 'Maximum selected · fans are ramping up.':'All fans at their firmware maximum.' : mode==='custom' ? 'A custom fan override is active.' : 'Apple manages fan speed by default.';
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
  if(!Number.isFinite(goal) || goal<50 || goal>85) return;
  const info=fanControllerInfo;
  $('#target-curve-label').textContent=info.targetAlgorithm==='predictive'
    ? `20s forecast ${finite(info.predictedTemperature) ? info.predictedTemperature.toFixed(1)+'°C':'collecting…'} · aims below ${(goal-(info.headroom || 2)).toFixed(1)}°C · ${info.learningSamples || 0} learned samples${info.learningWarning ? ' · '+info.learningWarning:''}`
    : 'Update the fan helper to enable predictive cooling that learns from temperature, CPU load, and fan response.';
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
    $('#fan-help-intro').textContent=fanControl ? 'Run the installer once more to add predictive Target cooling and retain independent Constant RPM controls. macOS needs administrator approval to replace the helper.':'Install the administrator helper once to enable Constant, Max, and CPU Target fan modes.';
    $('#fan-help-dialog').showModal();
  } catch(error) {toast(error.message,true);}
});

function leaveViewer() {
  fetch(appPath('/api/stats/leave'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({viewer:viewerId}),keepalive:true}).catch(()=>{});
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
