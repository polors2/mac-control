/* Mac Control's api(), authenticated state and lifecycle events stay authoritative. */
'use strict';
(() => {
  let timer, busy=false, generation=0, previous=new Set();
  const section=document.createElement('section');section.className='notifier-section';section.setAttribute('aria-label','File copy activity');
  const heading=document.createElement('div');heading.className='section-heading';
  const title=document.createElement('h2');title.textContent='Finder copies & transfers';
  const status=document.createElement('span');status.className='section-meta';status.textContent='SIGN IN TO VIEW';
  heading.append(title,status);
  const note=document.createElement('p');note.className='stats-footnote';note.textContent='Finder copies mirror its visible progress window when access is allowed. Managed copies use verified byte counters.';
  const cards=document.createElement('div');cards.className='notifier-cards';cards.setAttribute('aria-live','polite');
  section.append(heading,cards,note);document.querySelector('main').prepend(section);
  const size=n=>n==null?'unknown':new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(n/1e6)+' MB';
  const terminal=new Set(['completed','failed','cancelled','unknown_after_restart']);
  function render(data){
    status.textContent=!data.available?'NOTIFIER UNAVAILABLE':data.finder_progress?.available?'CONNECTED TO FINDER':'FINDER ACCESS NEEDED';
    if(!data.available){if(cards.dataset.offline!=='true'){cards.replaceChildren();const p=document.createElement('p');p.textContent='The file activity service is not connected.';cards.append(p);cards.dataset.offline='true';}return;}
    cards.dataset.offline='false';
    const active=data.transfers.filter(j=>!terminal.has(j.status));
    const finder=(data.finder_progress?.items||[]).map(j=>({...j,display_name:j.title||'Finder file operation',status:'visible_in_finder',finder:true}));
    const items=[...finder.map(j=>[j,false]),...active.map(j=>[j,false]),...data.transfers.filter(j=>terminal.has(j.status)).slice(0,2).map(j=>[j,false])].slice(0,8);
    const keys=new Set(items.map(([j])=>j.id));
    for(const child of [...cards.children])if(!keys.has(child.dataset.key)&&!(child.dataset.empty==='true'&&!items.length))child.remove();
    if(!items.length){let p=cards.querySelector('[data-empty]');if(!p){p=document.createElement('p');p.dataset.empty='true';cards.append(p);}const message=data.finder_progress?.available?'No Finder copy window or active transfer.':'Allow DevBox Finder Observer in macOS Accessibility settings to show Finder’s copy progress.';if(p.textContent!==message)p.textContent=message;}
    for(const [job,hint] of items){
      let card=[...cards.children].find(n=>n.dataset.key===job.id);
      if(!card){card=document.createElement('article');card.className='notifier-card';card.dataset.key=job.id;card.append(document.createElement('h3'),document.createElement('progress'),document.createElement('p'));cards.append(card);}
      const [name,progress,detail]=card.children;
      if(name.textContent!==job.display_name)name.textContent=job.display_name;
      progress.max=100;progress.hidden=job.percent==null;if(job.percent!=null&&(progress.value!==job.percent||!progress.hasAttribute('value')))progress.value=job.percent;
      const description=job.finder?(job.text||'Finder progress window visible'):`${job.status.replaceAll('_',' ')} · ${job.percent==null?'total unknown':job.percent.toFixed(1)+'%'} · ${size(job.bytes_done)} / ${size(job.bytes_total)}`;
      if(detail.textContent!==description)detail.textContent=description;
    }
    previous=new Set(items.map(([j])=>j.id));
  }
  function schedule(delay=2000){clearTimeout(timer);if(authenticated&&!document.hidden&&!busy)timer=setTimeout(refresh,delay);}
  async function refresh(){if(!authenticated||document.hidden||busy)return;busy=true;const current=generation;try{const data=await api('/api/file-activity');if(current===generation&&authenticated&&!document.hidden)render(data);}catch(error){status.textContent='ACTIVITY DISCONNECTED · MAY BE STALE';}finally{busy=false;schedule();}}
  function pause(){clearTimeout(timer);generation++;status.textContent='PAUSED';cards.replaceChildren();}
  document.addEventListener('dashboard:resume',()=>schedule(0));document.addEventListener('dashboard:pause',pause);
  document.addEventListener('visibilitychange',()=>document.hidden?pause():schedule(0));window.addEventListener('pagehide',pause);window.addEventListener('pageshow',()=>schedule(0));schedule(0);
})();
