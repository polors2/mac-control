/* Mac Control owns authentication and lifecycle; only active real copies appear. */
'use strict';
(() => {
  let timer, busy=false, generation=0;
  const terminal=new Set(['completed','failed','cancelled','unknown_after_restart']);
  const section=document.createElement('section');section.className='notifier-section';section.setAttribute('aria-label','File copy activity');
  const heading=document.createElement('div');heading.className='section-heading';
  const title=document.createElement('h2');title.textContent='Copy progress';
  const status=document.createElement('span');status.className='section-meta';status.textContent='SIGN IN TO VIEW';heading.append(title,status);
  const cards=document.createElement('div');cards.className='notifier-cards';
  section.append(heading,cards);document.querySelector('main').prepend(section);
  const size=n=>{if(n==null)return '—';const [scale,unit]=n>=1e9?[1e9,'GB']:n>=1e6?[1e6,'MB']:n>=1e3?[1e3,'KB']:[1,'B'];return `${new Intl.NumberFormat(undefined,{maximumFractionDigits:1}).format(n/scale)} ${unit}`;};
  const text=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
  function bar(node,value,label){node.max=100;node.hidden=value==null;node.setAttribute('aria-label',label);if(value!=null&&(!node.hasAttribute('value')||node.value!==value))node.value=value;}
  function element(tag,className){const node=document.createElement(tag);if(className)node.className=className;return node;}
  function fileRows(card,job){
    const list=card.querySelector('.notifier-file-list'), empty=card.querySelector('.notifier-file-empty');
    const files=job.files||[], keys=new Set(files.map(file=>file.id));
    for(const child of [...list.children])if(!keys.has(child.dataset.key))child.remove();
    for(const [index,file] of files.entries()){
      let row=[...list.children].find(child=>child.dataset.key===file.id);
      if(!row){row=element('li','notifier-file');row.dataset.key=file.id;const top=element('div','notifier-file-top');top.append(element('span','notifier-filename'),element('span','notifier-file-percent'));row.append(top,element('progress'),element('p','notifier-file-detail'));}
      text(row.querySelector('.notifier-filename'),file.display_name);
      text(row.querySelector('.notifier-file-percent'),file.percent==null?'Copying':`${file.percent.toFixed(0)}%${file.progress_accuracy==='estimated'?' · estimated':''}`);
      bar(row.querySelector('progress'),file.percent,`${file.display_name} progress`);
      const done=file.progress_accuracy==='exact'?file.bytes_done:file.observed_offset_bytes;
      text(row.querySelector('.notifier-file-detail'),file.percent!=null?`${size(done)} / ${size(file.bytes_total)}`:file.bytes_total==null?'Copying':`${size(file.bytes_total)} · copying`);
      if(list.children[index]!==row)list.insertBefore(row,list.children[index]||null);
    }
    empty.hidden=files.length>0;
    text(empty,job.finder?(job.file_details_available===false?'Per-file details are unavailable for this copy.':'Waiting for Finder to open the next file…'):'Discovering files…');
  }
  function render(data){
    status.textContent=!data.available?'NOTIFIER UNAVAILABLE':data.finder_progress?.available?'LIVE':'FINDER ACCESS NEEDED';
    if(!data.available){if(cards.dataset.offline!=='true'){cards.replaceChildren();const p=element('p');p.textContent='The file activity service is not connected.';cards.append(p);cards.dataset.offline='true';}return;}
    cards.dataset.offline='false';
    const active=(data.transfers||[]).filter(job=>!terminal.has(job.status)&&job.provider!=='synthetic');
    const finder=(data.finder_progress?.items||[]).map(job=>({...job,finder:true}));
    const items=[...finder,...active].slice(0,8), keys=new Set(items.map(job=>job.id));
    for(const child of [...cards.children])if(!keys.has(child.dataset.key)&&!(child.dataset.empty==='true'&&!items.length))child.remove();
    if(!items.length){let p=cards.querySelector('[data-empty]');if(!p){p=element('p');p.dataset.empty='true';cards.append(p);}text(p,data.finder_progress?.available?'No copy in progress.':'Allow DevBox Finder Observer in macOS Accessibility settings to show Finder’s copy progress.');}
    for(const [index,job] of items.entries()){
      let card=[...cards.children].find(child=>child.dataset.key===job.id);
      if(!card){
        card=element('article','notifier-card');card.dataset.key=job.id;
        const top=element('div','notifier-overall-top');top.append(element('h3'),element('span','notifier-overall-percent'));
        const files=element('div','notifier-files');const label=element('h4');label.textContent='Files';files.append(label,element('ul','notifier-file-list'),element('p','notifier-file-empty'));
        card.append(top,element('p','notifier-overall-label'),element('progress'),element('p','notifier-overall-detail'),files);
      }
      const parts=(job.text||'').split(' · ');
      text(card.querySelector('h3'),job.finder?(parts[0]||job.title||'Finder copy'):job.display_name);
      text(card.querySelector('.notifier-overall-percent'),job.percent==null?'':`${job.percent.toFixed(0)}%`);
      text(card.querySelector('.notifier-overall-label'),job.finder?'Overall progress · Finder':'Overall progress');
      bar(card.querySelector('progress'),job.percent,'Overall copy progress');
      text(card.querySelector('.notifier-overall-detail'),job.finder?(parts.slice(1).join(' · ')||job.text):`${size(job.bytes_done)} / ${size(job.bytes_total)} · ${job.status.replaceAll('_',' ')}`);
      fileRows(card,job);
      if(cards.children[index]!==card)cards.insertBefore(card,cards.children[index]||null);
    }
  }
  function schedule(delay=2000){clearTimeout(timer);if(authenticated&&!document.hidden&&!busy)timer=setTimeout(refresh,delay);}
  async function refresh(){if(!authenticated||document.hidden||busy)return;busy=true;const current=generation;try{const data=await api('/api/file-activity');if(current===generation&&authenticated&&!document.hidden)render(data);}catch(error){status.textContent='DISCONNECTED · MAY BE STALE';}finally{busy=false;schedule();}}
  function pause(){clearTimeout(timer);generation++;status.textContent='PAUSED';cards.replaceChildren();}
  document.addEventListener('dashboard:resume',()=>schedule(0));document.addEventListener('dashboard:pause',pause);
  document.addEventListener('visibilitychange',()=>document.hidden?pause():schedule(0));window.addEventListener('pagehide',pause);window.addEventListener('pageshow',()=>schedule(0));schedule(0);
})();
