'use strict';

let powerHours=1, powerData=null, powerTimer, powerRequest=false, powerGeneration=0;
const powerEnergy=value=>finite(value) ? value>=1000 ? `${(value/1000).toFixed(3)} kWh`:`${value.toFixed(2)} Wh`:'— Wh';
const powerDuration=seconds=>seconds<60 ? `${Math.floor(seconds)}s`:`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`;
const powerClock=timestamp=>new Date(timestamp*1000).toLocaleTimeString([], {timeZone:'Asia/Manila',hour:'numeric',minute:'2-digit',second:'2-digit'});
Object.assign(activityViews,{
  'power-now':{sourceChart:'#power-watts',renderDetail:()=>renderPowerDetail(false)},
  'power-history':{renderDetail:()=>renderPowerDetail(false)},
  'power-energy':{renderDetail:()=>renderPowerDetail(true)}
});

function renderPowerDetail(energy) {
  const data=powerData, now=data?.now || Date.now()/1000;
  $('#activity-dialog .eyebrow').textContent=energy ? 'POWER & ENERGY · TODAY · MANILA':`POWER & ENERGY · LAST ${powerHours} ${powerHours===1 ? 'HOUR':'HOURS'}`;
  $('#activity-title').textContent=energy ? 'Energy today':expandedActivity==='power-now' ? 'Current power draw':'Power draw';
  $('#activity-detail').textContent=energy ? 'Cumulative recorded energy since 12:00am, Asia/Manila.':'Whole-Mac system power · readings every 10 seconds.';
  $('#activity-summary').classList.remove('has-memory');
  $('#memory-available').hidden=true;
  const container=$('#activity-values');container.replaceChildren();
  const group=document.createElement('div');
  const history=data?.hours===powerHours ? data.history:[];
  const values=history.map(point=>point.value).filter(finite);
  const rows=energy ? [['Recorded today',powerEnergy(data?.today?.energyWh)],['Time recorded',powerDuration(data?.today?.coveredSeconds || 0)],['Average draw',data?.today?.coveredSeconds>0 ? `${(data.today.energyWh*3600/data.today.coveredSeconds).toFixed(1)} W`:'—']]:
    [['Now',finite(data?.watts) ? `${data.watts.toFixed(1)} W`:'—'],['Chart average',values.length ? `${(values.reduce((sum,value)=>sum+value,0)/values.length).toFixed(1)} W`:'—'],['Chart peak',values.length ? `${Math.max(...values).toFixed(1)} W`:'—']];
  for(const [label,value] of rows) {
    const row=document.createElement('p'), name=document.createElement('span'), output=document.createElement('strong');
    name.textContent=label;output.textContent=value;row.append(name,output);group.append(row);
  }
  container.append(group);
  $('#activity-chart').setAttribute('viewBox','0 0 600 240');
  powerChart('activity-chart',energy ? data?.today?.history || []:history,energy ? data?.today?.start || now:now-powerHours*3600,now,energy);
  $('#activity-dialog .activity-time span:first-child').textContent=energy ? '12:00am · Manila':`${powerHours} ${powerHours===1 ? 'hour':'hours'} ago`;
  $('#activity-status').textContent=data?.error || (!authenticated ? 'Sign in to see power readings.':data?.hours!==powerHours && !energy ? 'Loading power history…':data?.running ? 'Live · updates every 10 seconds. Sleep and downtime appear as gaps.':'Power readings unavailable. Saved totals include recorded periods only.');
}

function powerChart(id, points, begin, end, energy=false) {
  const chart=$(`#${id}`), values=points.map(point=>point.value).filter(finite);
  const width=Math.round(chart.getBoundingClientRect().width || 600), height=Math.round(chart.getBoundingClientRect().height || 240);
  chart.setAttribute('viewBox',`0 0 ${width} ${height}`);
  chart.setAttribute('preserveAspectRatio','none');
  const baseline=height-14, top=24, right=Math.max(44,width-(energy ? 110:70));
  const peak=Math.max(energy ? 1:10,...values), magnitude=10**Math.floor(Math.log10(peak));
  const maximum=Math.ceil(peak/magnitude)*magnitude;
  const x=time=>8+Math.max(0,Math.min(1,(time-begin)/Math.max(1,end-begin)))*(right-8);
  const y=value=>baseline-Math.min(1,value/maximum)*(baseline-top);
  const color=energy ? '#719478':'#b18b51';
  let html=`<defs><linearGradient id="${id}-fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${color}" stop-opacity=".2"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`;
  for(const height of [top,(top+baseline)/2,baseline]) html+=`<path d="M8 ${height}H${right}" stroke="#ced9d0" stroke-width="1" stroke-dasharray="3 5"/>`;
  html+=`<text x="${width-2}" y="20" text-anchor="end" fill="#526358" font-size="14">${energy ? powerEnergy(maximum):`${maximum} W`}</text><text x="${width-2}" y="${baseline+4}" text-anchor="end" fill="#526358" font-size="14">0</text>`;
  let group=[];
  const flush=()=>{
    if(!group.length) return;
    const path=group.map((point,index)=>`${index ? 'L':'M'}${x(point.time).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ');
    if(group.length>1) html+=`<path d="${path} L${x(group.at(-1).time).toFixed(2)},${baseline} L${x(group[0].time).toFixed(2)},${baseline} Z" fill="url(#${id}-fill)"/><path d="${path}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    html+=`<circle cx="${x(group.at(-1).time).toFixed(2)}" cy="${y(group.at(-1).value).toFixed(2)}" r="3.5" fill="${color}"/>`;
    group=[];
  };
  for(const point of points) {
    if(!finite(point.value)) flush();
    else group.push(point);
  }
  flush();
  if(!values.length) html+=`<text x="${width/2}" y="${(top+baseline)/2}" text-anchor="middle" fill="#526358" font-size="14">Waiting for readings</text>`;
  chart.innerHTML=html;
  inspectChart(chart,{points,start:begin,end,left:8,right,top,bottom:baseline,width,x,y,
    maxDistance:energy ? 90:Math.max(15,powerHours*3600/600*1.5),
    series:[{key:'value',name:energy ? 'Energy recorded':'Power draw',color,format:energy ? powerEnergy:value=>`${value.toFixed(1)} W`}]});
  chart.setAttribute('aria-label',energy ? `Cumulative recorded energy since midnight Manila: ${powerEnergy(powerData?.today?.energyWh)}. Gaps indicate missing readings.`:`System power over the last ${powerHours} ${powerHours===1 ? 'hour':'hours'}. Current draw: ${finite(powerData?.watts) ? powerData.watts.toFixed(1)+' watts':'unavailable'}. Gaps indicate missing readings.`);
}

function renderPower(data, error=null) {
  const live=!!data?.running && !error;
  $('#power-watts').textContent=live && finite(data.watts) ? data.watts.toFixed(1):'—';
  $('#power-live').textContent=live ? 'Live':!authenticated ? 'Sign in':error || data?.error ? 'Unavailable':'Waiting';
  $('#power-live').classList.toggle('is-live',live);
  $('#power-updated').textContent=data?.sampleTime ? `Last read ${powerClock(data.sampleTime)}`:'Updates every 10 seconds';
  $('#power-energy').textContent=powerEnergy(data?.today?.energyWh);
  $('#power-history-start').textContent=`${powerHours} ${powerHours===1 ? 'hour':'hours'} ago`;
  const now=data?.now || Date.now()/1000;
  powerChart('power-history-chart',data?.history || [],now-powerHours*3600,now);
  powerChart('power-energy-chart',data?.today?.history || [],data?.today?.start || now,now,true);
  $('#power-note').textContent=error ? 'Reconnecting to power readings. Saved energy totals remain available.':data?.error ? data.error:`${powerDuration(data?.today?.coveredSeconds || 0)} recorded today · Logs continue with the dashboard closed · Sleep and downtime appear as gaps.`;
  renderPowerDaily(data);
  if(activityViews[expandedActivity]?.renderDetail) renderActivityDetail();
}

function renderPowerDaily(data) {
  const daily=data?.daily || [], body=$('#power-daily-rows');
  body.replaceChildren();
  $('#power-daily-empty').hidden=!!daily.length;
  for(const day of daily) {
    const row=document.createElement('tr');
    for(const value of [day.day+(day.day===data.today.day ? ' · today':''),powerEnergy(day.energy_wh),powerDuration(day.covered_seconds),day.covered_seconds>0 ? `${(day.energy_wh*3600/day.covered_seconds).toFixed(1)} W`:'—']) {
      const cell=document.createElement('td');cell.textContent=value;row.append(cell);
    }
    body.append(row);
  }
  renderDailyEnergyChart(data);
}

function dailyEnergySeries(daily, todayKey) {
  const byDay=new Map(daily.map(day=>[day.day,day]));
  // Calendar arithmetic uses UTC noon on the Manila date, independent of the viewer's zone.
  const today=new Date(`${todayKey}T12:00:00Z`), points=[];
  for(let index=0;index<90;index++) {
    const date=new Date(today);date.setUTCDate(date.getUTCDate()-(89-index));
    const key=date.toISOString().slice(0,10), day=byDay.get(key);
    points.push({day:key,value:finite(day?.energy_wh) && day.energy_wh>=0 ? day.energy_wh:null,
      seconds:day?.covered_seconds || 0,index});
  }
  return points;
}

function renderDailyEnergyChart(data) {
  const chart=$('#power-daily-chart');
  const today=data?.today?.day || new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Manila'}).format(new Date());
  const points=dailyEnergySeries(data?.daily || [],today), recorded=points.filter(point=>finite(point.value));
  const total=recorded.reduce((sum,point)=>sum+point.value,0);
  $('#power-daily-total').textContent=recorded.length ? powerEnergy(total):'— Wh';
  $('#power-daily-count').textContent=`${recorded.length} / 90`;
  $('#power-daily-today').textContent=powerEnergy(data?.today?.energyWh);
  const width=Math.round(chart.getBoundingClientRect().width || 900), height=Math.round(chart.getBoundingClientRect().height || 320);
  chart.setAttribute('viewBox',`0 0 ${width} ${height}`);
  const left=48, right=width-18, top=34, baseline=height-40;
  const peak=Math.max(1,...recorded.map(point=>point.value)), magnitude=10**Math.floor(Math.log10(peak));
  const maximum=Math.ceil(peak/magnitude)*magnitude, divisor=maximum>=1000 ? 1000:1, unit=divisor===1000 ? 'kWh':'Wh';
  const x=index=>left+index/89*(right-left), y=value=>baseline-value/maximum*(baseline-top);
  let html=`<text x="${left}" y="17" fill="#526358" font-size="14">${unit} / day</text>`;
  for(const value of [0,maximum/2,maximum]) {
    const label=(value/divisor).toLocaleString(undefined,{maximumFractionDigits:2});
    html+=`<path d="M${left} ${y(value)}H${right}" stroke="#d7dfd9" stroke-dasharray="3 5"/><text x="${left-10}" y="${y(value)+5}" text-anchor="end" fill="#526358" font-size="14">${label}</text>`;
  }
  const dateFormat=new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',timeZone:'UTC'});
  for(const index of width<500 ? [0,45,89]:[0,30,60,89]) {
    html+=`<text x="${x(index)}" y="${height-8}" text-anchor="${index===0 ? 'start':index===89 ? 'end':'middle'}" fill="#526358" font-size="14">${dateFormat.format(new Date(points[index].day+'T12:00:00Z'))}</text>`;
  }
  let group=[];
  const flush=()=>{
    if(group.length>1) html+=`<path class="daily-energy-line" d="${group.map((point,index)=>`${index ? 'L':'M'}${x(point.index).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ')}" fill="none" stroke="#50775b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
    group=[];
  };
  for(const point of points) {
    if(finite(point.value)) group.push(point);
    else flush();
  }
  flush();
  for(const point of recorded) {
    const partial=point.day===today;
    html+=`<circle class="daily-energy-point" cx="${x(point.index)}" cy="${y(point.value)}" r="${recorded.length===1 ? 5:3.5}" fill="${partial ? '#fff':'#50775b'}" stroke="#50775b" stroke-width="2"><title>${point.day}${partial ? ' · today, in progress':''}: ${powerEnergy(point.value)} · ${powerDuration(point.seconds)} recorded</title></circle>`;
  }
  if(recorded.length<2) html+=`<text x="${(left+right)/2}" y="${top+(baseline-top)/2}" text-anchor="middle" fill="#526358" font-size="14">${recorded.length ? 'More days will form a line.':'No daily readings yet.'}</text>`;
  chart.innerHTML=html;
  const dated=points.map(point=>({...point,time:Date.parse(point.day+'T00:00:00+08:00')/1000}));
  inspectChart(chart,{points:dated,start:dated[0].time,end:dated.at(-1).time,left,right,top,bottom:baseline,width,
    x:time=>left+(time-dated[0].time)/(dated.at(-1).time-dated[0].time)*(right-left),y,
    formatTime:(time,point)=>point ? `${point.day}${point.day===today ? ' · in progress':''} · Manila`:chartSampleClock(time),
    series:[{key:'value',name:'Daily energy',color:'#50775b',format:powerEnergy}]});
  chart.setAttribute('aria-label',`Daily energy line chart for the last 90 days. ${recorded.length} ${recorded.length===1 ? 'day':'days'} recorded, ${powerEnergy(total)} total. Missing days are gaps. Today is in progress.`);
  $('#power-daily-note').textContent=recorded.length===1 ? `Only ${recorded[0].day} has data so far. Earlier days are unrecorded, not zero.`:'Each point is one day of recorded energy. Missing days are gaps; today is shown with an open point.';
}

function schedulePower(delay=10000) {
  clearTimeout(powerTimer);
  if(authenticated && !document.hidden && !powerRequest) powerTimer=setTimeout(refreshPower,delay);
}
async function refreshPower() {
  if(!authenticated || document.hidden || powerRequest) return;
  powerRequest=true;
  const generation=powerGeneration, hours=powerHours;
  try {
    const data=await api(`/api/power?hours=${hours}`);
    if(generation!==powerGeneration || hours!==powerHours || !authenticated || document.hidden) return;
    powerData=data;renderPower(data);
  } catch(error) {
    if(generation===powerGeneration && authenticated && !document.hidden) renderPower(powerData,error.message);
    if(error.status===401) {authenticated=false;setOnline(false);showLogin();}
  } finally {powerRequest=false;schedulePower(hours===powerHours ? 10000:0);}
}
for(const button of document.querySelectorAll('[data-power-hours]')) button.addEventListener('click',()=>{
  powerHours=Number(button.dataset.powerHours);powerGeneration++;
  for(const choice of document.querySelectorAll('[data-power-hours]')) choice.setAttribute('aria-pressed',String(Number(choice.dataset.powerHours)===powerHours));
  $('#power-history-start').textContent=`${powerHours} ${powerHours===1 ? 'hour':'hours'} ago`;
  if(activityViews[expandedActivity]?.renderDetail) renderActivityDetail();
  schedulePower(0);
});
$('#power-daily-open').addEventListener('click',()=>{
  $('#power-daily-dialog').showModal();
  renderDailyEnergyChart(powerData);
});
function pausePower() {
  clearTimeout(powerTimer);powerGeneration++;
  $('#power-live').classList.remove('is-live');
  $('#power-live').textContent=authenticated ? 'Paused':'Sign in';
  if(!authenticated) {powerData=null;renderPower(null);}
}
document.addEventListener('dashboard:resume',()=>schedulePower(0));
document.addEventListener('dashboard:pause',pausePower);
document.addEventListener('visibilitychange',()=>document.hidden ? pausePower():schedulePower(0));
window.addEventListener('pagehide',pausePower);
window.addEventListener('pageshow',()=>schedulePower(0));
renderPower(null);
schedulePower(0);

window.addEventListener('resize',()=>renderPower(powerData));
