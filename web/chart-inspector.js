'use strict';

function nearestChartPoint(points,time,maxDistance=Infinity) {
  let nearest=null, distance=Infinity;
  for(const point of points) {
    const next=Math.abs(point.time-time);
    if(next<distance) {nearest=point;distance=next;}
  }
  return distance<=maxDistance ? nearest:null;
}

const chartInspectors=new WeakMap();
let activeChartInspector=null;
const chartSampleClock=time=>new Date(time*1000).toLocaleString([],{
  timeZone:'Asia/Manila',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'
})+' · Manila';

function inspectChart(chart,config) {
  let inspector=chartInspectors.get(chart);
  if(!inspector) {
    const tooltip=document.createElement('div');tooltip.className='chart-tooltip';tooltip.hidden=true;
    tooltip.id=`${chart.id}-tooltip`;tooltip.setAttribute('role','tooltip');
    inspector={chart,tooltip,config,ratio:null};chartInspectors.set(chart,inspector);
    chart.setAttribute('tabindex','0');chart.setAttribute('aria-describedby',tooltip.id);
    chart.classList.add('inspectable-chart');
    chart.addEventListener('pointermove',event=>pointChartInspector(inspector,event));
    chart.addEventListener('pointerdown',event=>pointChartInspector(inspector,event));
    chart.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch') hideChartInspector(inspector);});
    chart.addEventListener('pointercancel',()=>hideChartInspector(inspector));
    chart.addEventListener('blur',()=>hideChartInspector(inspector));
    chart.addEventListener('focus',()=>{
      if(inspector.ratio===null) inspector.ratio=1;
      showChartInspector(inspector);
    });
    chart.addEventListener('keydown',event=>{
      if(event.key==='Escape') {hideChartInspector(inspector);return;}
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const {points,start,end}=inspector.config;
      if(!points.length) return;
      const selected=nearestChartPoint(points,start+(inspector.ratio ?? 1)*(end-start));
      let index=points.indexOf(selected);
      index=event.key==='Home' ? 0:event.key==='End' ? points.length-1:Math.max(0,Math.min(points.length-1,index+(event.key==='ArrowLeft' ? -1:1)));
      inspector.ratio=(points[index].time-start)/Math.max(1,end-start);showChartInspector(inspector);
    });
  }
  inspector.config=config;
  if(inspector.ratio!==null && activeChartInspector===inspector) showChartInspector(inspector);
}

function pointChartInspector(inspector,event) {
  const bounds=inspector.chart.getBoundingClientRect(), {left,right,width}=inspector.config;
  const local=(event.clientX-bounds.left)*width/Math.max(1,bounds.width);
  inspector.ratio=Math.max(0,Math.min(1,(local-left)/Math.max(1,right-left)));
  showChartInspector(inspector);
}

function hideChartInspector(inspector=activeChartInspector) {
  if(!inspector) return;
  inspector.tooltip.hidden=true;inspector.ratio=null;
  inspector.chart.querySelector('.chart-crosshair')?.remove();
  if(activeChartInspector===inspector) activeChartInspector=null;
}

function showChartInspector(inspector) {
  if(activeChartInspector && activeChartInspector!==inspector) hideChartInspector(activeChartInspector);
  activeChartInspector=inspector;
  const {chart,tooltip,config,ratio}=inspector;
  const {points,start,end,left,right,top,bottom,width,x,y,series,maxDistance}=config;
  const time=start+ratio*(end-start), point=nearestChartPoint(points,time,maxDistance);
  const sampleTime=point?.time ?? time, position=point ? x(sampleTime):left+ratio*(right-left);
  const parent=chart.closest('dialog') || document.body;
  if(tooltip.parentElement!==parent) parent.append(tooltip);
  tooltip.replaceChildren();
  const clock=document.createElement('div');clock.className='chart-tooltip-time';
  clock.textContent=config.formatTime ? config.formatTime(sampleTime,point):chartSampleClock(sampleTime);tooltip.append(clock);
  const group=document.createElementNS('http://www.w3.org/2000/svg','g');group.classList.add('chart-crosshair');group.setAttribute('aria-hidden','true');
  const line=document.createElementNS(group.namespaceURI,'path');
  line.setAttribute('d',`M${position} ${top}V${bottom}`);line.setAttribute('stroke','#526358');line.setAttribute('stroke-dasharray','3 3');group.append(line);
  for(const seriesLine of series) {
    const value=point?.[seriesLine.key], valid=typeof value==='number' && Number.isFinite(value);
    const row=document.createElement('div'), name=document.createElement('span'), output=document.createElement('strong');
    name.textContent=seriesLine.name;output.textContent=valid ? seriesLine.format(value,point):'No sample';row.append(name,output);tooltip.append(row);
    if(valid) {
      const dot=document.createElementNS(group.namespaceURI,'circle');
      for(const [key,entry] of Object.entries({cx:position,cy:y(value),r:4,fill:seriesLine.color,stroke:'#fff','stroke-width':1.5})) dot.setAttribute(key,String(entry));
      group.append(dot);
    }
  }
  chart.querySelector('.chart-crosshair')?.remove();chart.append(group);tooltip.hidden=false;
  const bounds=chart.getBoundingClientRect(), box=tooltip.getBoundingClientRect();
  const viewportWidth=document.documentElement.clientWidth, viewportHeight=document.documentElement.clientHeight;
  const anchor=bounds.left+position/width*bounds.width;
  tooltip.style.left=`${Math.max(8,Math.min(viewportWidth-box.width-8,anchor-box.width/2))}px`;
  const above=bounds.top-box.height-10;
  tooltip.style.top=`${Math.max(8,Math.min(viewportHeight-box.height-8,above>=8 ? above:bounds.bottom+10))}px`;
}
document.addEventListener('scroll',()=>hideChartInspector(),true);
document.addEventListener('pointerdown',event=>{
  if(activeChartInspector && !activeChartInspector.chart.contains(event.target)) hideChartInspector();
});
document.addEventListener('dashboard:pause',()=>hideChartInspector());
document.addEventListener('visibilitychange',()=>{if(document.hidden) hideChartInspector();});
document.addEventListener('close',()=>hideChartInspector(),true);
window.addEventListener('resize',()=>hideChartInspector());
