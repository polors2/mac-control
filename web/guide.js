// Render the repository guides as text nodes, never executable Markdown/HTML.
function guideInline(parent, text) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[([^\]]+)\]\(([^)]+)\))/g;
  let end=0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(end,match.index)));
    let node;
    if (match[2]) {
      node=document.createElement('span');node.textContent=match[2];node.title=match[3];
      // Repository-relative links stay descriptive; live contracts are above.
      if (/^https?:\/\//.test(match[3])) {
        node=document.createElement('a');node.textContent=match[2];node.href=match[3];
        node.target='_blank';node.rel='noopener noreferrer';
      }
    } else {
      node=document.createElement(match[0].startsWith('`') ? 'code':'strong');
      node.textContent=match[0].startsWith('`') ? match[0].slice(1,-1):match[0].slice(2,-2);
    }
    parent.append(node);end=match.index+match[0].length;
  }
  parent.append(document.createTextNode(text.slice(end)));
}

function renderGuide(markdown, target) {
  target.replaceChildren();
  const lines=markdown.split('\n');
  let paragraph=[], list=null;
  function flush() {
    if(paragraph.length) {const p=document.createElement('p');guideInline(p,paragraph.join(' '));target.append(p);paragraph=[];}
  }
  for(let i=0;i<lines.length;i++) {
    const line=lines[i];
    if(line.startsWith('```')) {
      flush();list=null;const code=[];
      while(++i<lines.length && !lines[i].startsWith('```')) code.push(lines[i]);
      const pre=document.createElement('pre'), node=document.createElement('code');
      node.textContent=code.join('\n');pre.append(node);target.append(pre);continue;
    }
    if(line.startsWith('|')) {
      flush();list=null;const wrap=document.createElement('div'), table=document.createElement('table');
      wrap.className='guide-table';wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Documentation table');
      const head=document.createElement('thead'), body=document.createElement('tbody');
      let rowIndex=0;
      while(i<lines.length && lines[i].startsWith('|')) {
        const cells=lines[i].split('|').slice(1,-1).map(cell=>cell.trim());
        if(!cells.every(cell=>/^:?-+:?$/.test(cell))) {
          const row=document.createElement('tr');
          cells.forEach(cell=>{const node=document.createElement(rowIndex===0 ? 'th':'td');if(rowIndex===0) node.scope='col';guideInline(node,cell);row.append(node);});
          (rowIndex===0 ? head:body).append(row);rowIndex++;
        }
        i++;
      }
      i--;table.append(head,body);wrap.append(table);target.append(wrap);continue;
    }
    const heading=line.match(/^(#{1,6})\s+(.+)$/), item=line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if(heading) {flush();list=null;const node=document.createElement(`h${Math.min(heading[1].length+1,6)}`);guideInline(node,heading[2]);target.append(node);}
    else if(item) {
      flush();const tag=/^\s*\d/.test(line) ? 'ol':'ul';
      if(!list || list.tagName.toLowerCase()!==tag) {list=document.createElement(tag);target.append(list);}
      const node=document.createElement('li');guideInline(node,item[1]);list.append(node);
    } else if(!line.trim()) {flush();list=null;}
    else {list=null;paragraph.push(line);}
  }
  flush();
}

let dashboardDocs=null, guideSection='guide';
function showGuideSection() {
  document.querySelectorAll('[data-guide]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.guide===guideSection)));
  if(dashboardDocs) renderGuide(dashboardDocs[guideSection],$('#guide-content'));
}
$('#dashboard-guide').addEventListener('click',async()=>{
  if(!authenticated) {showLogin();return;}
  const dialog=$('#guide-dialog');
  if(!dialog.open) dialog.showModal();
  $('#guide-status').textContent=dashboardDocs ? '':'Loading documentation…';
  $('#guide-content').setAttribute('aria-busy','true');
  try {
    if(!dashboardDocs) dashboardDocs=await api('/api/docs');
    $('#guide-status').textContent='';showGuideSection();
  } catch(error) {$('#guide-status').textContent=`${error.message} Close and reopen the guide to retry.`;}
  finally {$('#guide-content').setAttribute('aria-busy','false');}
});
document.querySelectorAll('[data-guide]').forEach(button=>button.addEventListener('click',()=>{
  guideSection=button.dataset.guide;showGuideSection();
}));
