'use strict';
let driveData=[], driveRequest=false, unlockDrive=null, driveTimer, driveGeneration=0;
const pendingDrives=new Map();
const driveCards=new Map();
const driveSize=bytes=>bytes>=1e12 ? `${(bytes/1e12).toFixed(0)} TB`:`${Math.round(bytes/1e9)} GB`;

function renderDrives(drives) {
  drives=drives.filter(drive=>drive.connected);
  driveData=drives;
  const container=$('#drive-cards');
  const present=new Set(drives.map(drive=>drive.id));
  for(const [id,card] of driveCards) if(!present.has(id)) {card.remove();driveCards.delete(id);}
  container.querySelector('.drive-empty')?.remove();
  $('#drives-status').textContent=!authenticated ? 'SIGN IN TO CONTROL DRIVES':pendingDrives.size ? 'APPLYING MOUNT CHANGE':`${drives.filter(drive=>drive.connected).length} CONNECTED`;
  if(!drives.length) {
    const empty=document.createElement('p');empty.className='drive-empty';empty.textContent=authenticated ? 'No eligible external USB volumes are connected.':'Sign in to see your USB drives.';
    container.append(empty);return;
  }
  for(const drive of drives) {
    let card=driveCards.get(drive.id);
    if(!card) {
      card=document.createElement('article');card.className='drive-card';card.dataset.drive=drive.id;
      const top=document.createElement('div');top.className='drive-top';
      const symbol=document.createElement('span');symbol.className='drive-icon';symbol.innerHTML=icon('drive');
      const heading=document.createElement('div');heading.className='drive-heading';
      const name=document.createElement('h3');
      const subtitle=document.createElement('p');
      heading.append(name,subtitle);
      const button=document.createElement('button');button.className='state-toggle drive-mount-button';
      button.addEventListener('click',()=>{const current=driveData.find(item=>item.id===drive.id);if(current) changeDrive(current);});
      top.append(symbol,heading,button);
      const status=document.createElement('div');status.className='drive-state';
      status.append(document.createElement('i'),document.createElement('span'));
      card.append(top,status);driveCards.set(drive.id,card);container.append(card);
    }
    card.setAttribute('aria-busy',String(pendingDrives.has(drive.id)));
    card.querySelector('h3').textContent=drive.name;
    const filesystems=[...new Set((drive.volumes || []).map(volume=>(volume.filesystem || '').toUpperCase()))];
    card.querySelector('.drive-heading p').textContent=[driveSize(drive.size),...filesystems,drive.encrypted ? 'Encrypted':null].filter(Boolean).join(' · ');
    const button=card.querySelector('button');
    button.setAttribute('aria-pressed',String(!!drive.mounted));button.setAttribute('aria-label',`${drive.locked ? 'Unlock and mount':drive.mounted ? 'Unmount':'Mount'} ${drive.name}`);
    button.disabled=!authenticated || !drive.connected || pendingDrives.size>0;
    button.textContent=pendingDrives.has(drive.id) ? pendingDrives.get(drive.id) ? 'Mounting…':'Unmounting…':drive.locked ? 'Unlock':drive.mounted ? 'Mounted':'Unmounted';
    const dot=card.querySelector('.drive-state i');dot.className=drive.mounted ? 'is-mounted':'';
    const label=card.querySelector('.drive-state span');
    label.textContent=drive.locked ? 'Locked · password required':!drive.connected ? 'USB disconnected':drive.state==='partial' ? 'Some volumes are mounted':drive.mounted ? (drive.volumes || []).filter(volume=>volume.mounted).map(volume=>volume.mountPoint).join(' · '):'Unmounted · available to remount';
  }
}
function promptUnlock(drive,message='') {
  unlockDrive=drive;$('#drive-password').value='';
  $('#drive-unlock-title').textContent=`${drive.locked ? 'Unlock':'Mount'} ${drive.name}`;
  $('#drive-password').disabled=!drive.locked;$('#drive-password').hidden=!drive.locked;
  $('label[for="drive-password"]').hidden=!drive.locked;
  $('#drive-unlock-description').textContent=drive.locked ? "Enter this drive's encryption password to mount it.":'This drive is unlocked. Retry mounting it without entering its password again.';
  if(!pendingDrives.size) $('#drive-unlock-submit').textContent=drive.locked ? 'Unlock & mount':'Mount';
  $('#drive-unlock-error').textContent=message;
  if(!$('#drive-unlock-dialog').open) $('#drive-unlock-dialog').showModal();
  if(drive.locked) $('#drive-password').focus({preventScroll:true});
}
async function changeDrive(drive,password=null,mountRequested=null) {
  if(pendingDrives.size) return;
  const mount=mountRequested ?? (drive.locked || !drive.mounted);
  if(mount && drive.locked && password===null) {promptUnlock(drive);return false;}
  driveGeneration++;clearTimeout(driveTimer);
  pendingDrives.set(drive.id,mount);renderDrives(driveData);
  try {
    const request={id:drive.id,mounted:mount};if(password!==null) request.password=password;
    const result=await api('/api/drives',request,password===null?30000:50000);
    driveData=result.drives;toast(`${drive.name} ${mount ? 'mounted':'unmounted'}.`);return true;
  } catch(error) {
    if(error.data?.drives) driveData=error.data.drives;
    if(error.data?.requiresPassword || password!==null || unlockDrive?.id===drive.id) promptUnlock(driveData.find(item=>item.id===drive.id) || drive,error.message);
    else toast(error.message,true);
    return false;
  } finally {pendingDrives.clear();renderDrives(driveData);scheduleDrives();}
}
$('#drive-unlock-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!unlockDrive || pendingDrives.size) return;
  const drive=unlockDrive, field=$('#drive-password'), secret=field.disabled ? null:field.value;
  field.value='';$('#drive-unlock-submit').disabled=true;$('#drive-unlock-submit').textContent=field.disabled ? 'Mounting…':'Unlocking…';$('#drive-unlock-error').textContent='';
  try {if(await changeDrive(drive,secret,true)) $('#drive-unlock-dialog').close();}
  finally {$('#drive-unlock-submit').disabled=false;$('#drive-unlock-submit').textContent=unlockDrive?.locked===false ? 'Mount':'Unlock & mount';}
});
$('#drive-unlock-dialog').addEventListener('close',()=>{unlockDrive=null;$('#drive-password').value='';$('#drive-unlock-error').textContent='';});
function scheduleDrives(delay=10000) {
  clearTimeout(driveTimer);
  if(authenticated && !document.hidden && !driveRequest && !pendingDrives.size) driveTimer=setTimeout(refreshDrives,delay);
}
async function refreshDrives() {
  if(!authenticated || document.hidden || driveRequest || pendingDrives.size) return;
  driveRequest=true;const generation=driveGeneration;
  try {
    const result=await api('/api/drives',undefined,30000);
    if(generation===driveGeneration && authenticated && !document.hidden) renderDrives(result.drives);
  } catch(error) {$('#drives-status').textContent='MOUNT STATE UNAVAILABLE';}
  finally {driveRequest=false;scheduleDrives();}
}
function pauseDrives(){clearTimeout(driveTimer);driveGeneration++;}
document.addEventListener('dashboard:resume',()=>scheduleDrives(0));
document.addEventListener('dashboard:pause',pauseDrives);
document.addEventListener('visibilitychange',()=>document.hidden ? pauseDrives():scheduleDrives(0));
window.addEventListener('pagehide',pauseDrives);
window.addEventListener('pageshow',()=>scheduleDrives(0));
scheduleDrives(0);
