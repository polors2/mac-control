'use strict';

const paths = {
  trackpad:'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 16h18m-9 0v5"/>',
  fan:'<circle cx="12" cy="12" r="2"/><path d="M12 10C7 8 7 2 11 2c5 0 5 5 2 8m1 2c2-5 8-5 8-1 0 5-5 5-8 2m-2 1c5 2 5 8 1 8-5 0-5-5-2-8m-1-2c-2 5-8 5-8 1 0-5 5-5 8-2"/>',
  thermometer:'<path d="M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0Z"/><path d="M12 8v10"/><circle cx="12" cy="18" r="1.5"/>',
  drive:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="12" cy="10" r="4"/><path d="m12 10 5 6M7 18h.01M10 18h.01"/>',
  power:'<path d="M12 2v10M6 5a9 9 0 1 0 12 0"/>',
  cpu:'<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/>',
  gpu:'<rect x="2" y="5" width="20" height="13" rx="2"/><circle cx="10" cy="11.5" r="3.5"/><path d="M16 9h3m-3 4h3M6 18v3m3-3v3m3-3v3m3-3v3"/>',
  network:'<path d="M12 3v11m-4-4 4 4 4-4M4 17v4h16v-4M3 4l3-1m12 0 3 1"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  'sun-small':'<circle cx="12" cy="12" r="3"/><path d="M12 5V4m0 16v-1M5 12H4m16 0h-1M6.3 6.3l-.7-.7m12.8 12.8-.7-.7M6.3 17.7l-.7.7M17.7 6.3l.7-.7"/>',
  keyboard:'<rect x="2" y="6" width="20" height="13" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 13h.01M10 13h.01M14 13h.01M18 13h.01M7 16h10"/>',
  'keyboard-dim':'<rect x="2" y="7" width="20" height="12" rx="2"/><path d="M6 11h.01M10 11h.01M14 11h.01M18 11h.01M7 15h10"/>',
  volume:'<path d="m11 5-6 4H2v6h3l6 4V5ZM15 8a5 5 0 0 1 0 8m3-11a9 9 0 0 1 0 14"/>',
  'volume-low':'<path d="m11 5-6 4H2v6h3l6 4V5ZM15 9a4 4 0 0 1 0 6"/>',
  muted:'<path d="m11 5-6 4H2v6h3l6 4V5ZM16 9l6 6m0-6-6 6"/>',
  expand:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  laptop:'<rect x="4" y="3" width="16" height="13" rx="2"/><path d="M4 16 2 20h20l-2-4M9 20h6"/>',
  devices:'<rect x="2" y="3" width="14" height="12" rx="2"/><path d="M8 15v4m-3 0h6"/><rect x="15" y="10" width="7" height="11" rx="1.5"/><path d="M18 18h1"/>',
  logout:'<path d="M9 4H4v16h5m5-12 4 4-4 4m-6-4h13"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  music:'<path d="M9 17V5l12-2v12M9 9l12-2"/><ellipse cx="6" cy="17" rx="3" ry="3"/><ellipse cx="18" cy="15" rx="3" ry="3"/>',
  previous:'<path d="M4 5v14M20 5 8 12l12 7V5Z"/>',
  next:'<path d="M20 5v14M4 5l12 7-12 7V5Z"/>',
  play:'<path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke-width="1"/>',
  sparkles:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4m-2-2h4"/>',
  moon:'<path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.sun}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => {el.innerHTML = icon(el.dataset.icon);});
const $ = selector => document.querySelector(selector);
const sliders = ['brightness', 'keyboard', 'volume'];
let state = null, online = false, busy = false, authenticated = false, setupRequired = false, canSetup = false;
let drainTimer, toastTimer, lastInteraction = 0, failures = 0;
const pending = new Map(), desired = new Map();
const presets = {
  work:{name:'Workday', brightness:75,keyboard:45,volume:30,mute:0},
  evening:{name:'After hours',brightness:35,keyboard:25,volume:15,mute:0},
  quiet:{name:'Quiet time',brightness:50,keyboard:30,volume:0,mute:1}
};

async function api(path, body, timeoutMs=12000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {method:body === undefined ? 'GET':'POST',
      headers:body === undefined ? {} : {'Content-Type':'application/json'},
      body:body === undefined ? undefined : JSON.stringify(body), signal:controller.signal});
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || 'Your Mac could not apply this change.');
      error.data = result; error.status = response.status; throw error;
    }
    return result;
  } catch(error) {
    if (error.name === 'AbortError') throw new Error('The Mac took too long to respond. Check the connection and try again.');
    throw error;
  } finally {clearTimeout(timeout);}
}

function toast(message, error=false) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').className = `toast visible${error ? ' error':''}`;
  toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), error ? 7000:3500);
}

function setOnline(value) {
  const wasOnline=online;
  online = value;
  document.body.classList.toggle('online', value);
  document.body.classList.toggle('offline', !value);
  $('#connection-label').textContent = value ? 'Connected locally':(authenticated ? 'Reconnecting…':'Sign in');
  render();
  if(value && !wasOnline) document.dispatchEvent(new Event('dashboard:resume'));
  if(!authenticated) document.dispatchEvent(new Event('dashboard:pause'));
}

function controlLevel(control) {
  if (desired.has(control)) return desired.get(control);
  if (desired.has(`${control}Power`)) {
    if (!desired.get(`${control}Power`) && control !== 'volume') return 0;
    if (desired.get(`${control}Power`) && !(state?.[control] > 0)) return state?.restoreLevels?.[control] || {brightness:65,keyboard:50,volume:30}[control];
  }
  return state?.[control];
}

function render() {
  const capabilities = state?.capabilities || {};
  for (const control of sliders) {
    const supported = !!capabilities[control];
    const value = controlLevel(control);
    const available = online && supported;
    const range = $(`#${control}`), card = $(`[data-control="${control}"]`);
    range.disabled = !available;
    card.classList.toggle('unavailable', state !== null && !supported);
    card.classList.toggle('saving', desired.has(control) || desired.has(`${control}Power`));
    $(`#${control}-value`).textContent = value == null ? '—' : Math.round(value);
    range.value = value ?? 0;
    range.style.setProperty('--fill', `${value ?? 0}%`);
    range.setAttribute('aria-valuetext', value == null ? 'Unavailable':`${Math.round(value)} percent`);
    card.style.setProperty('--art-level',(value ?? 0)/100);
    card.style.setProperty('--sun-rotation',`${(value ?? 0)*1.4}deg`);
    document.querySelectorAll(`[data-step^="${control}:"],[data-max="${control}"]`).forEach(button => {button.disabled = !available;});
  }
  $('#device-name').textContent = state?.device || 'Your Mac';
  const display = controlLevel('brightness') ?? 50;
  const keyboard = controlLevel('keyboard') ?? 0;
  const volume = controlLevel('volume') ?? 0;
  const muted = desired.has('volumePower') ? !desired.get('volumePower') : desired.has('mute') ? !!desired.get('mute') : !!state?.muted;
  $('#brightness-note').textContent = !state ? 'Reading display…' : !capabilities.brightness ? 'Brightness unavailable' : display === 0 ? 'Off · previous level saved':'Built-in display';
  $('#keyboard-note').textContent = !state ? 'Reading keyboard…' : !capabilities.keyboard ? 'No supported backlight':keyboard === 0 ? 'Off · previous level saved':state.keyboardSuppressed ? 'Limited by ambient light':state.keyboardAuto ? 'Adapting to ambient light':'Manual brightness';
  $('#volume-note').textContent = !state ? 'Reading sound…' : !capabilities.volume ? 'Output volume unavailable':muted ? 'Muted · volume saved':'Output volume';
  $('#audio-output').textContent = state?.audioOutput || 'Just the right amount of everything.';
  document.querySelectorAll('[data-power]').forEach(button=>{
    const control=button.dataset.power;
    const enabled=control==='volume' ? !muted && volume>0 : (controlLevel(control) ?? 0)>0;
    button.disabled=!online || !capabilities[control==='volume' ? 'mute':control];
    button.setAttribute('aria-pressed',String(enabled));
    button.querySelector('.power-label').textContent=enabled ? 'On':'Off';
    button.title=enabled ? (control==='volume' ? 'Mute sound':`Set ${control==='brightness' ? 'display brightness':'keyboard backlight'} to 0%`) : 'Restore previous level';
    $(`[data-control="${control}"]`).classList.toggle('is-off',!!state && !enabled);
  });
  const auto = desired.has('keyboardPower') && !desired.get('keyboardPower') ? false : desired.has('keyboardAuto') ? !!desired.get('keyboardAuto'):!!state?.keyboardAuto;
  $('#keyboard-auto').disabled = !online || !capabilities.keyboardAuto;
  $('#keyboard-auto').setAttribute('aria-pressed',String(auto));
  $('#keyboard-auto .state-label').textContent=auto ? 'On':'Off';
  document.querySelectorAll('[data-media]').forEach(button => {button.disabled = !online || !capabilities.media;});
  $('#media-help').hidden = !!capabilities.media;
  $('#media-description').textContent = capabilities.media ? 'Your Mac’s media keys, right here.':'One-time Accessibility setup for media keys.';
  document.querySelectorAll('[data-preset]').forEach(button => {
    button.disabled = !online || busy || !sliders.some(key=>capabilities[key]);
    const preset = presets[button.dataset.preset];
    const active = online && state && sliders.every(key=>!capabilities[key] || Math.abs((state[key] ?? -100)-preset[key])<=1) && (!capabilities.mute || !!state.muted===!!preset.mute);
    button.classList.toggle('active',!!active);
    button.setAttribute('aria-pressed',String(!!active));
    button.title = `${preset.name}: display ${preset.brightness}%, keyboard ${preset.keyboard}%, volume ${preset.volume}%, ${preset.mute ? 'muted':'unmuted'}`;
  });
  $('#logout').hidden = !authenticated;
  $('#logout').disabled = busy || pending.size > 0;
  $('#sync-label').textContent = !online ? (authenticated ? 'WAITING FOR YOUR MAC':'SIGN IN TO GET STARTED') : busy || pending.size ? 'APPLYING YOUR CHANGES':'IN SYNC WITH YOUR MAC';
  $('#footer-status').textContent = online ? 'LOCAL FIRST. ALWAYS.':'WAITING FOR A LOCAL CONNECTION';
}

function enqueue(control, value, immediate=false) {
  if (!online) return;
  lastInteraction = Date.now();
  desired.set(control,value); pending.set(control,value);
  render();
  clearTimeout(drainTimer);
  drainTimer = setTimeout(drain, immediate ? 0:110);
}

async function drain() {
  if (busy || !pending.size) return;
  busy = true; render();
  while (pending.size && online) {
    const [control,value] = pending.entries().next().value;
    pending.delete(control);
    try {
      const power=control.endsWith('Power');
      const baseControl=power ? control.slice(0,-5):control;
      state = await api(power ? '/api/toggle':'/api/control',power ? {control:baseControl,enabled:!!value}:{control,value});
      if (!pending.has(control)) {
        desired.delete(control);
        const card = $(`[data-control="${baseControl}"]`);
        if (card) {card.classList.remove('saved'); void card.offsetWidth; card.classList.add('saved');}
      }
    } catch(error) {
      if (error.data?.capabilities) state = error.data;
      if (!pending.has(control)) desired.delete(control);
      toast(error.message || 'Could not reach your Mac.',true);
      if (error.status===401) {authenticated=false; setOnline(false); showLogin();}
      if (!error.status) {pending.clear(); desired.clear(); setOnline(false);}
    }
    render();
  }
  busy = false; lastInteraction = Date.now(); render();
}

sliders.forEach(control => {
  $(`#${control}`).addEventListener('input',event => enqueue(control,Number(event.target.value)));
  $(`#${control}`).addEventListener('change',()=>{clearTimeout(drainTimer);drain();});
});
document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click',()=>{
  const [control,step] = button.dataset.step.split(':');
  enqueue(control,Math.max(0,Math.min(100,(desired.get(control) ?? state[control])+Number(step))),true);
}));
document.querySelectorAll('[data-max]').forEach(button => button.addEventListener('click',()=>enqueue(button.dataset.max,100,true)));
document.querySelectorAll('[data-power]').forEach(button=>button.addEventListener('click',()=>enqueue(`${button.dataset.power}Power`,button.getAttribute('aria-pressed')!=='true',true)));
$('#keyboard-auto').addEventListener('click',()=>enqueue('keyboardAuto',Number(!(desired.has('keyboardAuto') ? desired.get('keyboardAuto'):state.keyboardAuto)),true));
document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click',()=>{
  const preset = presets[button.dataset.preset];
  const skipped = sliders.filter(control=>!state.capabilities[control]);
  for (const control of sliders) if (state.capabilities[control]) enqueue(control,preset[control],true);
  if (state.capabilities.mute) enqueue('mute',preset.mute,true);
  if (skipped.length) toast(`Applying available controls. ${skipped.join(', ')} unavailable on this Mac.`,true);
}));
document.querySelectorAll('[data-media]').forEach(button => button.addEventListener('click',async()=>{
  button.disabled = true; lastInteraction = Date.now();
  try {
    state = await api('/api/media',{action:button.dataset.media});
    toast({play:'Play / pause key sent',next:'Next track key sent',previous:'Previous track key sent'}[button.dataset.media]);
  } catch(error) {toast(error.message,true);}
  render();
}));

async function refresh(force=false) {
  if (!authenticated || busy || pending.size || (!force && Date.now()-lastInteraction < 1200)) return;
  try {
    state = await api('/api/state'); failures = 0; setOnline(true);
  } catch(error) {
    failures++;
    if (failures>=2 || error.status===401) setOnline(false);
    if (error.status===401) {authenticated=false; setOnline(false); showLogin();}
  }
}

function showLogin() {
  const setup = setupRequired && canSetup;
  $('#auth-title').textContent = setup ? 'Set your password.' : 'Welcome back.';
  $('#auth-intro').textContent = setup ? 'Choose a password for your dashboard. Use it on any device on your network.' : setupRequired ? 'Set your dashboard password once on the host Mac at localhost:8765, then sign in here.' : 'Enter your password to control your Mac.';
  $('#login-submit-label').textContent = setup ? 'Set password & sign in' : 'Sign in';
  $('#password-input').autocomplete = setup ? 'new-password' : 'current-password';
  $('#confirm-password-section').hidden = !setup;
  $('#confirm-password').required = setup;
  $('#login-submit').disabled = setupRequired && !canSetup;
  if (!$('#auth-dialog').open) $('#auth-dialog').showModal();
}
$('#auth-dialog').addEventListener('cancel',event=>event.preventDefault());
$('#login-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const button = $('#login-submit');
  const password = $('#password-input').value;
  $('#login-error').textContent='';
  if (setupRequired && canSetup && password !== $('#confirm-password').value) {
    $('#login-error').textContent='Passwords do not match.'; return;
  }
  button.disabled = true;
  try {
    await api(setupRequired && canSetup ? '/api/setup' : '/api/session',{password,remember:$('#remember-device').checked});
    authenticated=true; setupRequired=false;
    $('#auth-dialog').close(); $('#password-input').value=''; $('#confirm-password').value=''; await refresh(true);
  } catch(error) {$('#login-error').textContent=error.message;}
  finally {button.disabled=false;}
});

$('#logout').addEventListener('click',async()=>{
  try {
    document.dispatchEvent(new Event('dashboard:pause'));
    await api('/api/logout',{});
    authenticated=false; state=null; pending.clear(); desired.clear();
    setOnline(false); $('#login-error').textContent=''; showLogin();
  } catch(error) {toast(error.message,true);}
});

$('#network-device').addEventListener('click',async()=>{
  if (!authenticated) {showLogin(); return;}
  try {
    const info = await api('/api/connection');
    $('#lan-url').textContent = info.urls[0] || `http://${info.hostname}:${info.port}`;
    $('#connection-note').textContent = info.urls.length ? 'The Mac must stay awake and this service must stay running.':'No local network address found. Connect the Mac to Wi-Fi or Ethernet.';
    $('#network-dialog').showModal();
  } catch(error) {toast(error.message,true);}
});
$('#copy-url').addEventListener('click',async()=>{
  const text = $('#lan-url').textContent;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else {
      const input = document.createElement('textarea'); input.value=text; input.style.position='fixed'; input.style.opacity='0';
      $('#network-dialog').append(input);input.select();
      const copied = document.execCommand('copy'); input.remove(); if (!copied) throw new Error('Copy unavailable');
    }
    toast('Network address copied.');
  } catch {toast('Select and copy the address above.');}
});
$('#media-help').addEventListener('click',async()=>{
  try {
    const info = await api('/api/connection');
    $('#helper-path').textContent = info.helperPath || 'Mac Control Media.app (the installer prints its location on the host Mac)';
    $('#help-dialog').showModal();
  } catch(error) {toast(error.message,true);}
});
document.querySelectorAll('dialog:not(#auth-dialog)').forEach(dialog=>dialog.addEventListener('click',event=>{
  const box=dialog.getBoundingClientRect();
  if (event.target===dialog && (event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom)) dialog.close();
}));
document.addEventListener('visibilitychange',()=>{
  document.body.classList.toggle('is-background',document.hidden);
  if (!document.hidden) refresh(true);
});
window.addEventListener('focus',()=>refresh(true));

async function start() {
  render();
  try {
    const session = await api('/api/session');
    authenticated = session.authenticated; setupRequired = session.setupRequired; canSetup = session.canSetup;
    if (authenticated) await refresh(true);
    else {setOnline(false); showLogin();}
  } catch(error) {
    setOnline(false);toast('Unable to connect to the Mac service. Keep the server running, then reload.',true);
  }
  setInterval(()=>{if (!document.hidden) refresh();},2500);
}
start();
