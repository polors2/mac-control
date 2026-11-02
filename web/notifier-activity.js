/* Read-only active copy summary. Finder navigation is never a transfer. */
'use strict';
// Pure selection: summaries with measured detail, never observer placeholders.
function copyProgressRows(data) {
  const terminal=new Set(['completed','failed','cancelled','unknown_after_restart','no_longer_visible']);
  const size=n=>{if(!Number.isFinite(n))return null;const [scale,unit]=n>=1e9?[1e9,'GB']:n>=1e6?[1e6,'MB']:n>=1e3?[1e3,'KB']:[1,'B'];return `${new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(n/scale)} ${unit}`;};
  function finderCopy(job){
    const parts=(job.text||'').split(' · ').map(part=>part.trim()).filter(Boolean);
    const label=parts[0]||job.title||'';
    // Finder's sidebar can expose unrelated percentage controls (for example
    // Favourites plus an entire navigation list). Require an operation label.
    if(!/^(copy(?:ing)?|mov(?:e|ing)|duplicat(?:e|ing)|preparing|replacing|verifying)\b/i.test(label))return null;
    const detail=parts.slice(1).filter(part=>/\d[\d.,]*\s*(?:[KMGT]?B|bytes?|seconds?|minutes?|hours?|days?)\b/i.test(part)).join(' · ');
    return {...job,label,detail,finder:true};
  }
  const finder=(data.finder_progress?.items||[]).filter(job=>!terminal.has(job.status)).map(finderCopy).filter(job=>job && job.detail);
  const active=(data.transfers||[]).filter(job=>!terminal.has(job.status) && job.provider!=='synthetic').map(job=>{
    const measured=Number.isFinite(job.bytes_done) && job.bytes_done>=0 && Number.isFinite(job.bytes_total) && job.bytes_total>0;
    return {...job,label:job.display_name||'Copying',detail:measured?`${size(job.bytes_done)} of ${size(job.bytes_total)}`:''};
  }).filter(job=>job.detail && !/^finder file operation$/i.test(job.label.trim()) && !(finder.length && job.provider==='finder'));
  return [...finder,...active].slice(0,8);
}

// DOM rendering.
(() => {
  let timer,busy=false,generation=0;
  const section=document.createElement('section');section.className='notifier-section';section.setAttribute('aria-label','File copy activity');section.hidden=true;
  const heading=document.createElement('div');heading.className='section-heading';
  const title=document.createElement('h2');title.textContent='Copy progress';
  const status=document.createElement('span');status.className='section-meta';heading.append(title,status);
  const cards=document.createElement('div');cards.className='notifier-cards';section.append(heading,cards);
  document.querySelector('.stats-section').insertAdjacentElement('afterend',section);
  const terminal=new Set(['completed','failed','cancelled','unknown_after_restart','no_longer_visible']);
  const setText=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
  function element(tag,className){const node=document.createElement(tag);if(className)node.className=className;return node;}
  function render(data){
    if(!data.available){section.hidden=true;cards.replaceChildren();return;}
    const items=copyProgressRows(data),keys=new Set(items.map(job=>job.id));
    section.hidden=!items.length;setText(status,items.length>1?`${items.length} copies`:'');
    for(const child of [...cards.children])if(!keys.has(child.dataset.key))child.remove();
    for(const [index,job] of items.entries()){
      let card=[...cards.children].find(child=>child.dataset.key===job.id);
      if(!card){card=element('article','notifier-card');card.dataset.key=job.id;const top=element('div','notifier-overall-top');top.append(element('h3'),element('span','notifier-overall-percent'));card.append(top,element('progress'),element('p','notifier-overall-detail'),element('p','notifier-current-file'));}
      setText(card.querySelector('h3'),job.label);
      const percent=Number.isFinite(job.percent)?Math.max(0,Math.min(100,job.percent)):null;
      setText(card.querySelector('.notifier-overall-percent'),percent==null?'':`${percent.toFixed(0)}%`);
      const progress=card.querySelector('progress');progress.hidden=percent==null;progress.max=100;progress.setAttribute('aria-label',`${job.label} progress`);if(percent!=null)progress.value=percent;
      const detail=card.querySelector('.notifier-overall-detail');detail.hidden=!job.detail;setText(detail,job.detail);
      const files=(job.files||[]).filter(file=>!terminal.has(file.status)&&file.display_name);
      const current=card.querySelector('.notifier-current-file');current.hidden=!files.length;setText(current,files.length?`Current: ${files[0].display_name}${files.length>1?` (+${files.length-1})`:''}`:'');
      if(cards.children[index]!==card)cards.insertBefore(card,cards.children[index]||null);
    }
  }
  function schedule(delay=2000){clearTimeout(timer);if(authenticated&&!document.hidden&&!busy)timer=setTimeout(refresh,delay);}
  async function refresh(){if(!authenticated||document.hidden||busy)return;busy=true;const current=generation;try{const data=await api('/api/file-activity');if(current===generation&&authenticated&&!document.hidden)render(data);}catch(error){section.hidden=true;}finally{busy=false;schedule();}}
  function pause(){clearTimeout(timer);generation++;section.hidden=true;cards.replaceChildren();}
  document.addEventListener('dashboard:resume',()=>schedule(0));document.addEventListener('dashboard:pause',pause);
  document.addEventListener('visibilitychange',()=>document.hidden?pause():schedule(0));window.addEventListener('pagehide',pause);window.addEventListener('pageshow',()=>schedule(0));schedule(0);
})();
