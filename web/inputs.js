'use strict';
let inputData=null, inputBusy=false, inputRequest=false, inputTimer, inputGeneration=0;
let inputPermissionError=false;
const inputNames={keyboard:'Built-in keyboard',trackpad:'Built-in trackpad'};

function renderInputs() {
  const installed=!!inputData?.installed;
  if(installed && typeof inputData.permissionGranted==='boolean') inputPermissionError=!inputData.permissionGranted;
  const currentBundle=installed && inputData.version>=2;
  $('#inputs-setup').hidden=currentBundle && !inputPermissionError;
  $('#inputs-setup-label').textContent=installed && !currentBundle ? 'Update input helper':installed ? 'Allow input access':'Enable input controls';
  $('#input-install-steps').hidden=currentBundle;
  $('#inputs-permission-note').hidden=!inputPermissionError || !authenticated;
  $('#inputs-status').textContent=!authenticated ? 'SIGN IN TO CONTROL INPUTS':!inputData ? 'CHECKING INPUT STATE':!installed ? 'ONE-TIME SETUP NEEDED':!currentBundle ? 'UPDATE INPUT HELPER':inputBusy ? 'APPLYING CHANGE':inputPermissionError ? 'INPUT MONITORING PERMISSION NEEDED':'INTERNAL DEVICES ONLY';
  for(const device of ['keyboard','trackpad']) {
    const info=inputData?.[device], button=$(`#input-${device}`);
    const enabled=info?.enabled;
    button.disabled=!authenticated || !installed || !info?.controllable || inputBusy;
    if(typeof enabled==='boolean') button.setAttribute('aria-pressed',String(enabled));
    else button.removeAttribute('aria-pressed');
    button.textContent=typeof enabled==='boolean' ? enabled ? 'On':'Off':'—';
    button.setAttribute('aria-label',`${inputNames[device]} ${typeof enabled==='boolean' ? enabled ? 'on; click to disable':'off; click to enable':'state unavailable'}`);
    $(`#input-${device}-note`).textContent=!authenticated ? 'Sign in to control this input.':!inputData ? 'Reading input state…':!installed ? 'Install the input helper to enable this switch.':!info?.present ? 'No supported internal device found.':enabled ? 'Accepting input.': 'Input blocked · turn On to restore.';
  }
}
async function changeInput(device) {
  if(inputBusy || !inputData?.[device]?.controllable) return;
  const enabled=!inputData[device].enabled;
  inputBusy=true;inputGeneration++;clearTimeout(inputTimer);renderInputs();
  try {
    inputData=await api('/api/inputs',{device,enabled});
    if(!enabled) inputPermissionError=false;
    toast(`${inputNames[device]} ${enabled ? 'enabled':'disabled'}.`);
  } catch(error) {
    if(error.data?.keyboard && error.data?.trackpad) inputData=error.data;
    if(/Input Monitoring|0xe00002e2/i.test(error.message)) inputPermissionError=true;
    toast(error.message,true);
  } finally {inputBusy=false;renderInputs();scheduleInputs();}
}
function scheduleInputs(delay=5000) {
  clearTimeout(inputTimer);
  if(authenticated && !document.hidden && !inputRequest && !inputBusy) inputTimer=setTimeout(refreshInputs,delay);
}
async function refreshInputs() {
  if(!authenticated || document.hidden || inputRequest || inputBusy) return;
  inputRequest=true;const generation=inputGeneration;
  try {
    const result=await api('/api/inputs');
    if(generation===inputGeneration && authenticated && !document.hidden) {inputData=result;renderInputs();}
  } catch(error) {$('#inputs-status').textContent='INPUT STATE UNAVAILABLE';}
  finally {inputRequest=false;scheduleInputs();}
}
function pauseInputs(){clearTimeout(inputTimer);inputGeneration++;if(!authenticated){inputData=null;renderInputs();}}
for(const device of ['keyboard','trackpad']) $(`#input-${device}`).addEventListener('click',()=>changeInput(device));
$('#inputs-setup').addEventListener('click',()=>$('#input-help-dialog').showModal());
document.addEventListener('dashboard:resume',()=>scheduleInputs(0));
document.addEventListener('dashboard:pause',pauseInputs);
document.addEventListener('visibilitychange',()=>document.hidden ? pauseInputs():scheduleInputs(0));
window.addEventListener('pagehide',pauseInputs);
window.addEventListener('pageshow',()=>scheduleInputs(0));
renderInputs();scheduleInputs(0);
