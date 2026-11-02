'use strict';

let hostStatusTimer, hostStatusRequest=false, hostStatusGeneration=0;

function renderHostStatus(data) {
  const battery=data?.battery, known=battery?.available && battery.present && Number.isFinite(battery.percent);
  const item=$('#battery-status');
  $('#battery-percent').textContent=known ? `${battery.percent}%`:'—';
  $('#battery-fill').setAttribute('width',known ? String(22*battery.percent/100):'0');
  item.classList.toggle('is-charging',known && battery.state==='charging');
  item.classList.toggle('is-low',known && battery.percent<=20 && battery.source==='battery');
  const batteryState={'charging':'Charging','charged':'Full','not-charging':'Not charging','discharging':'Discharging'};
  const source=battery?.source==='ac' ? 'AC power':battery?.source==='battery' ? 'On battery':'';
  $('#battery-detail').textContent=!authenticated ? 'Sign in':!data ? 'Checking…':!battery?.available ? 'Unavailable':battery.present===false ? 'No battery':[source,batteryState[battery.state]].filter(Boolean).join(' · ') || 'Status unknown';
  const labels={'connected':'Connected','disconnected':'Disconnected','starting':'Starting…','needs-login':'Sign in needed','needs-approval':'Approval needed','not-installed':'Not installed','unavailable':'Unavailable'};
  $('#tailscale-label').textContent=!authenticated ? 'Sign in':!data ? 'Checking…':labels[data.tailscale?.state] || 'Unavailable';
  $('#tailscale-status').classList.toggle('is-connected',authenticated && data?.tailscale?.state==='connected');
}

function scheduleHostStatus(delay=10000) {
  clearTimeout(hostStatusTimer);
  if(authenticated && !document.hidden && !hostStatusRequest) hostStatusTimer=setTimeout(refreshHostStatus,delay);
}
async function refreshHostStatus() {
  if(!authenticated || document.hidden || hostStatusRequest) return;
  hostStatusRequest=true;const generation=hostStatusGeneration;
  try {
    const data=await api('/api/host-status');
    if(generation===hostStatusGeneration && authenticated && !document.hidden) renderHostStatus(data);
  } catch {
    if(generation===hostStatusGeneration && authenticated && !document.hidden) renderHostStatus({});
  } finally {hostStatusRequest=false;scheduleHostStatus();}
}
function pauseHostStatus() {
  clearTimeout(hostStatusTimer);hostStatusGeneration++;
  renderHostStatus(null);
}
document.addEventListener('dashboard:resume',()=>scheduleHostStatus(0));
document.addEventListener('dashboard:pause',pauseHostStatus);
document.addEventListener('visibilitychange',()=>document.hidden ? pauseHostStatus():scheduleHostStatus(0));
window.addEventListener('pagehide',pauseHostStatus);
window.addEventListener('pageshow',()=>scheduleHostStatus(0));
renderHostStatus(null);scheduleHostStatus(0);
