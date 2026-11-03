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
  renderClaudeUsage(data);
  renderCodexUsage(data);
}

const claudeResetClock=new Intl.DateTimeFormat([], {timeZone:'Asia/Manila',weekday:'short',hour:'numeric',minute:'2-digit'});
function claudeReportAge(seconds) {
  const minutes=Math.max(0,Math.round((Date.now()/1000-seconds)/60));
  return minutes<1 ? 'just now':minutes<60 ? `${minutes} min ago`:minutes<1440 ? `${Math.round(minutes/60)} h ago`:`${Math.round(minutes/1440)} d ago`;
}
function claudePercent(usage) {
  return Number.isFinite(usage?.usedPercent) ? Math.round(Math.min(100,Math.max(0,usage.usedPercent))):null;
}
function showClaudeWindow(item,used,visible) {
  item.hidden=!visible;
  item.querySelector('strong').textContent=used===null ? '—':`${used}%`;
  item.querySelector('.claude-meter i').style.width=`${used ?? 0}%`;
  item.classList.toggle('is-high',used!==null && used>=80 && used<100);
  item.classList.toggle('is-full',used===100);
}
function renderClaudeUsage(data) {
  const claude=data?.claude, available=authenticated && claude?.state==='available', details=[];
  const reset=usage=>`resets ${claudeResetClock.format(new Date(usage.resetsAt*1000))} Manila`;
  for(const [selector,usage,name] of [['#claude-five-hour',claude?.fiveHour,'5-hour'],['#claude-seven-day',claude?.sevenDay,'Weekly']]) {
    const used=available ? claudePercent(usage):null;
    showClaudeWindow($(selector),used,available);
    details.push(used===null ? `${name}: no active window reported`:`${name}: ${used}% used, ${reset(usage)}`);
  }
  // Per-model weekly windows (Fable) come from the dashboard's periodic Claude Code usage check.
  const models=available && Array.isArray(claude.modelWeekly) ? claude.modelWeekly.filter(usage=>typeof usage?.name==='string' && claudePercent(usage)!==null):[];
  for(const usage of models) details.push(`${usage.name} weekly: ${claudePercent(usage)}% used, ${reset(usage)}`);
  const model=models.find(usage=>usage.name==='Fable') || models[0], modelItem=$('#claude-model-week');
  showClaudeWindow(modelItem,model ? claudePercent(model):null,Boolean(model));
  modelItem.querySelector('.claude-window-label').textContent=model?.name || 'Fable';
  const note=!authenticated ? 'Sign in':!data ? 'Checking…':available ? '':claude?.state==='not-configured' ? 'Set up':'Unavailable';
  $('#claude-note').textContent=note;$('#claude-note').hidden=!note;
  const age=available && Number.isFinite(claude.updatedAt) ? Date.now()/1000-claude.updatedAt:null;
  $('#claude-usage').classList.toggle('is-stale',available && (age===null || age>1800));
  $('#claude-usage').title=available ? `Claude plan usage\n${details.join('\n')}\nUpdated from Claude Code ${age===null ? 'at an unknown time':claudeReportAge(claude.updatedAt)}`
    :note==='Set up' ? 'Claude plan usage is not set up: add the Mac Control status line to Claude Code (see README)':`Claude plan usage: ${note}`;
}

function codexWindowLabel(minutes,fallback) {
  return !Number.isFinite(minutes) || minutes<=0 ? fallback:minutes%1440===0 ? `${minutes/1440}d`:minutes%60===0 ? `${minutes/60}h`:`${minutes}m`;
}
function renderCodexUsage(data) {
  const codex=data?.codex, available=authenticated && codex?.state==='available', details=[];
  for(const [key,fallback] of [['primary','5h'],['secondary','7d']]) {
    const usage=codex?.[key], item=$(`#codex-${key}`), label=codexWindowLabel(usage?.windowMinutes,fallback);
    const used=available && usage?.resetsAt>Date.now()/1000 ? claudePercent(usage):null;
    showClaudeWindow(item,used,available);
    item.querySelector('.claude-window-label').textContent=label;
    details.push(used===null ? `${label}: no active window reported`:`${label}: ${used}% used, resets ${claudeResetClock.format(new Date(usage.resetsAt*1000))} Manila`);
  }
  const note=!authenticated ? 'Sign in':!data || codex?.state==='checking' ? 'Checking…':available ? '':codex?.state==='not-configured' ? 'Set up':'Unavailable';
  $('#codex-note').textContent=note;$('#codex-note').hidden=!note;
  const age=available && Number.isFinite(codex.updatedAt) ? Date.now()/1000-codex.updatedAt:null;
  $('#codex-usage').classList.toggle('is-stale',available && (age===null || age>1800));
  $('#codex-usage').title=available ? `Codex plan usage\n${details.join('\n')}\nUpdated from Codex ${age===null ? 'at an unknown time':claudeReportAge(codex.updatedAt)}`
    :note==='Set up' || note==='Unavailable' ? 'Codex plan usage: install Codex and sign in with ChatGPT on the host Mac (see README)':`Codex plan usage: ${note}`;
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
