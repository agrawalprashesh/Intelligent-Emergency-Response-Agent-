// Frontend renders the simulation. All A* costs and dispatch decisions come from Python.
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rid = (a, b) => [a,b].sort().join('|');
const fmt = (number, digits=2) => number == null ? '—' : Number(number).toFixed(digits);
let state, search = null, step = 0, focused = null, mapView = 'live', tracePhase = 'exit', noticeTimer;

async function api(endpoint, data) {
  const options = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)};
  const response = await fetch('/api/' + endpoint, options);
  const body = await response.json();
  if (!response.ok) throw Error(body.error || 'Server error');
  return body;
}
function toast(message, error=false) {
  $('toast').textContent = message;
  $('toast').className = 'toast visible' + (error ? ' error' : '');
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => $('toast').className='toast', 3500);
}
function fill(id, names, chosen) {
  $(id).innerHTML = names.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');
  if (chosen) $(id).value=chosen;
}
function renderStats() {
  $('stat-total').textContent = state.incidents.length;
  $('stat-waiting').textContent = state.incidents.filter(i=>i.status==='Waiting'||i.status==='No route').length;
  $('stat-available').textContent = state.vehicles.filter(v=>v.status==='Available').length;
  $('stat-done').textContent = state.incidents.filter(i=>i.status==='Completed').length;
}
function renderVehicles() {
  $('vehicles').innerHTML = state.vehicles.map(v=>`<div class="vehicle-row">
    <span class="vehicle-icon">${v.kind==='Response'?'R':'A'}</span>
    <div><strong>${esc(v.id)}</strong><small>${esc(v.location)} · ${esc(v.equipment.join(', '))}</small></div>
    <span class="status ${v.status==='Available'?'available':''}">${esc(v.status)}</span></div>`).join('');
}
const pathLabel = route => route?.path?.length ? route.path.map(esc).join(' → ') : 'No reachable route';
function renderIncidents() {
  const priority={Critical:4,High:3,Medium:2,Low:1};
  const items=[...state.incidents].sort((a,b)=>priority[b.level]-priority[a.level]||a.id-b.id);
  $('incidents').innerHTML = items.length ? items.map(i=>{
    const active=i.status!=='Completed', planned=i.route;
    const who=i.vehicle || i.preview_vehicle;
    const assigned=Boolean(i.vehicle);
    const evac=i.evacuation;
    return `<article class="incident ${focused===i.id?'focused':''} ${active?'':'completed'}" data-focus="${i.id}" style="--complaint:${i.color}">
      <div class="ticket" style="background:${i.color}">#${i.id}</div>
      <div class="detail"><div class="incident-heading"><strong>${esc(i.event)} · ${esc(i.location)}</strong><span class="badge ${esc(i.level)}">${esc(i.level)}</span><span class="chip">${esc(i.status)}</span></div>
      <small>${assigned?'Automatically assigned':'Waiting — estimated from'} ${who?esc(who):'no suitable vehicle'}${i.status==='Completed'?' · route released':''}</small>
      ${planned ? `<p class="planned"><b>Response to scene:</b> ${pathLabel(planned)} <span class="metrics">${fmt(planned.distance)} km · ${fmt(planned.minutes)} min · <b>${fmt(planned.cost)} pts</b></span></p>
        <p class="alternatives"><b>Shortest:</b> ${pathLabel(i.shortest)} (${fmt(i.shortest?.distance)} km) &nbsp; | &nbsp; <b>Fastest:</b> ${pathLabel(i.fastest)} (${fmt(i.fastest?.minutes)} min)</p>` : `<p class="planned">No reachable path at the moment. Reopen a road to recalculate.</p>`}
      <p class="exit-plan"><b>↗ ${esc(i.event)} exit:</b> ${esc(i.exit_gate)}<br>
      ${evac?.path?.length ? `${pathLabel(evac)} <span class="metrics">${fmt(evac.distance)} km · ${fmt(evac.minutes)} min · ${fmt(evac.cost)} pts</span>` : '<span class="blocked-exit">No safe route available — reopen a connecting road.</span>'}</p>
      </div><label class="complete-label ${assigned&&active?'':'disabled'}" title="${assigned&&active?'Resolve and free reserved roads':'Only assigned and active complaints can be completed'}">
        <input type="checkbox" data-finish="${i.id}" ${!assigned||!active?'disabled':''} ${!active?'checked':''}>
        <span>Complete</span></label>
    </article>`;
  }).join('') : '<p class="muted">Register a complaint to see its shortest and recommended routes immediately.</p>';
  $('route-colors').innerHTML = items.filter(i=>i.status!=='Completed').map(i=>`<span class="route-key"><i style="background:${i.color}"></i>#${i.id} ${esc(i.event)} ${esc(i.status==='Waiting'?'(preview)':'')}</span>`).join('') || '<span class="muted">Colored complaint routes appear after registration.</span>';
}
function setMapView(view) {
  mapView = view;
  $('live-view').className='btn '+(view==='live'?'selected':'light');
  $('astar-view').className='btn '+(view==='astar'?'selected':'light');
  renderMap();
}
function effectiveUses(road) {
  if (focused===null) return road.use;
  let amount=0;
  const priority={Critical:4,High:3,Medium:2,Low:1};
  const active=state.incidents.filter(i=>i.status!=='Completed').sort((a,b)=>priority[b.level]-priority[a.level]||a.id-b.id);
  for(const item of active) {
    if(item.id===focused) break;
    const path=item.vehicle?item.route?.path||[]:[];
    if(path.slice(1).some((node,index)=>rid(path[index],node)===rid(road.a,road.b))) amount++;
  }
  return amount;
}
function roadLabelPosition(road, points) {
  const [x1,y1]=points[road.a], [x2,y2]=points[road.b];
  const key=rid(road.a,road.b);
  // Carefully spaced label placements keep every distance/time/cost tag legible.
  if(key===rid('Clinic','Sports')) return [430,274];
  if(key===rid('Academic','Library')) return [523,217];
  if(key===rid('Sports','Store')) return [613,452];
  if(key===rid('Store','Fire Exit')) return [925,446];
  if(key===rid('Lab','Store')) return [788,477];
  if(key===rid('Clinic','Academic')) return [291,224];
  if(key===rid('Library','Sports')) return [680,225];
  if(key===rid('Academic','Sports')) return [435,355];
  if (y1===y2) return [(x1+x2)/2, y1-42];
  if (x1===x2) return [x1===780?x1+82:x1+73, (y1+y2)/2];
  return [(x1+x2)/2, (y1+y2)/2];
}
function renderMap() {
  if (!state) return;
  const p=state.places;
  const tracing=mapView==='astar'&&search;
  const s=tracing ? search.steps[step] : null;
  const finalPath=tracing&&step===search.steps.length-1?search.path:[];
  const foundRoads=new Set(finalPath.slice(1).map((n,k)=>rid(finalPath[k],n)));
  const open=new Set(s?.open.map(n=>n.node)||[]), closed=new Set(s?.closed||[]);
  let out='<rect x="-45" y="-15" width="1180" height="750" rx="14" fill="#f8faff"/>';
  out+='<defs><marker id="path-arrow" markerWidth="8" markerHeight="8" refX="18" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8 Z" fill="#1c66c6"/></marker></defs>';
  for (const r of state.roads) {
    const [x1,y1]=p[r.a], [x2,y2]=p[r.b], key=rid(r.a,r.b);
    const type=r.blocked?'blocked':r.traffic>1?'traffic':'';
    out+=`<line data-road="${esc(key)}" class="road ${type}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"><title>${esc(r.a)} ↔ ${esc(r.b)}: ${fmt(r.distance,3)} km; ${fmt(r.distance*60/r.speed*r.traffic*(1+.4*r.use))} min; ${r.use} active route(s)</title></line>`;
  }
  // Every complaint uses one hue: solid for responder, dashed for the exit plan.
  // Offset shared road segments so simultaneous complaints remain distinguishable.
  const counts={};
  if (!tracing) {
    for (const i of state.incidents.filter(i=>i.status!=='Completed')) {
      for (const [route, evacuation] of [[i.route,false], [i.evacuation,true]]) {
        if (!route?.path?.length) continue;
        for (const [idx,b] of route.path.slice(1).entries()) {
          const a=route.path[idx], key=rid(a,b), r=state.roads.find(q=>rid(q.a,q.b)===key);
          if (r?.blocked) continue;
          const [x1,y1]=p[a], [x2,y2]=p[b], dx=x2-x1,dy=y2-y1,length=Math.hypot(dx,dy);
          if (!length) continue;
          const n=counts[key]||0; counts[key]=n+1;
          const shift=(n%2===0?1:-1)*(3+Math.floor(n/2)*6);
          const ox=-dy/length*shift, oy=dx/length*shift;
          const opacity=focused!==null&&focused!==i.id?0.26:1;
          out+=`<line class="complaint-route ${evacuation?'evacuation-route':i.vehicle?'':'preview-route'}" stroke="${esc(i.color)}" opacity="${opacity}" x1="${x1+ox}" y1="${y1+oy}" x2="${x2+ox}" y2="${y2+oy}"><title>#${i.id} ${esc(evacuation?'Exit plan':'Responder route')}: ${esc(a)} to ${esc(b)}</title></line>`;
          if (focused===i.id && evacuation) {
            const angle=Math.atan2(dy,dx), mx=(x1+x2)/2+ox,my=(y1+y2)/2+oy;
            const tipX=mx+Math.cos(angle)*8,tipY=my+Math.sin(angle)*8;
            out+=`<path d="M ${mx-Math.cos(angle-0.6)*8} ${my-Math.sin(angle-0.6)*8} L ${tipX} ${tipY} L ${mx-Math.cos(angle+0.6)*8} ${my-Math.sin(angle+0.6)*8}" fill="none" stroke="${esc(i.color)}" stroke-width="3"/>`;
          }
        }
      }
    }
  } else {
    for (const r of state.roads) if (foundRoads.has(rid(r.a,r.b))) {
      const [x1,y1]=p[r.a], [x2,y2]=p[r.b];
      out+=`<line class="astar-route" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
    }
  }
  // Costs are always visible, even on roads covered by a coloured route.
  for (const r of state.roads) {
    const [x,y]=roadLabelPosition(r,p), used=effectiveUses(r), minutes=r.distance*60/r.speed*r.traffic*(1+.4*used);
    out+=`<g class="road-tag" data-road="${esc(rid(r.a,r.b))}" transform="translate(${x},${y})">
      <rect x="-60" y="-29" width="120" height="59" rx="9"/>
      <text y="-12" class="km-label">${fmt(r.distance,2)} km</text>
      <text y="4" class="min-label">${fmt(minutes,2)} min${used?' · '+used+' busy':''}</text>
      <text y="22" class="score-label">${fmt(r.distance+minutes,2)} points</text>
      <title>${esc(r.a)} – ${esc(r.b)}. Distance ${fmt(r.distance,3)} km + time ${fmt(minutes,3)} min = ${fmt(r.distance+minutes,3)} points; speed ${r.speed} km/h, traffic ×${r.traffic}, ${used} higher-priority active route(s)</title>
    </g>`;
  }
  for (const [name,[x,y]] of Object.entries(p)) {
    const kind=s?.current===name?'current':finalPath.includes(name)?'path-node':open.has(name)?'open':closed.has(name)?'closed':'';
    const gate=Object.prototype.hasOwnProperty.call(state.exit_gates,name);
    const selectedOrigin=search?.start===name && tracing, selectedGoal=search?.goal===name && tracing;
    const nodeInfo = selectedOrigin ? 'START' : selectedGoal ? 'GOAL' : gate ? 'EXIT' : '';
    if(nodeInfo) out+=`<text class="node-role" x="${x}" y="${y-38}">${nodeInfo}</text>`;
    if (gate) {
      out+=`<rect class="place exit-node ${kind}" x="${x-26}" y="${y-26}" width="52" height="52" rx="13"/><text class="gate-symbol" x="${x}" y="${y+8}">⇥</text><text class="label exit-label" x="${x}" y="${y+57}">${esc(name)}</text>`;
    } else {
      out+=`<circle class="place ${kind}" cx="${x}" cy="${y}" r="26"/><circle class="node-center" cx="${x}" cy="${y}" r="8"/><text class="label" x="${x}" y="${y+57}">${esc(name)}</text>`;
    }
    const units=state.vehicles.filter(v=>v.location===name);
    units.forEach((v,index)=>{
      const cx=x-((units.length-1)*51)/2+index*51;
      out+=`<rect class="unit-pill ${v.status==='Available'?'':'busy'}" x="${cx-22}" y="${y-55}" width="44" height="20" rx="7"/><text class="unit" x="${cx}" y="${y-41}">${esc(v.id)}</text>`;
    });
    state.incidents.filter(i=>i.location===name&&i.status!=='Completed').forEach((i,index)=>{
      out+=`<circle cx="${x+25+index*16}" cy="${y+1}" r="11" fill="${i.color}" stroke="white" stroke-width="2"/><text class="complaint-number" x="${x+25+index*16}" y="${y+5}">${i.id}</text>`;
    });
  }
  $('map').innerHTML=out;
}
function routeDirections(title, route, subtitle='') {
  if (!route?.path?.length) return `<div class="route-phase"><h4>${esc(title)}</h4><p class="blocked-exit">No accessible route with the current road closures.</p></div>`;
  const start=route.path[0], end=route.path[route.path.length-1];
  const legs=route.legs||[];
  const unit=route.unit||'points';
  const instructions=legs.length ? `<ol class="directions-list">${legs.map(l=>`<li><div><b>${esc(l.from_node)} → ${esc(l.to_node)}</b> <span class="compass">${esc(l.direction)} ↗</span></div><small>${fmt(l.distance,3)} km · ${fmt(l.minutes,2)} min · road cost ${fmt(l.road_cost,3)} ${esc(unit)}</small><small class="formula">g=${fmt(l.g,3)} + h(${esc(l.to_node)})=${fmt(l.h,3)} ⇒ f=${fmt(l.f,3)}</small></li>`).join('')}</ol>` : '<p class="micro">Already at the destination.</p>';
  return `<div class="route-phase"><h4>${esc(title)}</h4><p class="route-summary">${esc(start)} → ${esc(end)} <b>${fmt(route.distance,2)} km · ${fmt(route.minutes,2)} min · ${fmt(route.cost,2)} ${esc(unit)}</b></p>${subtitle?`<p class="micro">${esc(subtitle)}</p>`:''}${instructions}</div>`;
}
function renderDirections() {
  const incident=state?.incidents.find(i=>i.id===focused);
  const switcher=$('trace-switch');
  switcher.hidden=!incident || incident.status==='Completed';
  $('trace-dispatch').className='btn '+(tracePhase==='dispatch'?'selected':'light');
  $('trace-exit').className='btn '+(tracePhase==='exit'?'selected':'light');
  if (incident) {
    $('directions-intro').textContent=`Request #${incident.id} · ${incident.event} at ${incident.location} → ${incident.exit_gate}${incident.status==='Completed'?' · completed':''}. Directions are read from the map, not live GPS.`;
    $('directions-content').innerHTML=routeDirections('1. Response team → emergency',incident.route,incident.vehicle?'Assigned team '+incident.vehicle:'Provisional route; no team assigned yet')+
      routeDirections('2. Incident → '+incident.exit_gate,incident.evacuation,'Event-specific planned exit; this is not an automatically driven vehicle journey.');
  } else if (search) {
    $('directions-intro').textContent=`Manual A* directions · optimize ${search.mode} · destination ${search.goal}.`;
    $('directions-content').innerHTML=routeDirections('A* selected path',search,'Straight-line heuristic h(n) is an optimistic estimate, not an extra fee charged on every road.');
  } else {
    $('directions-content').innerHTML='<p class="micro">Register an incident or run A* to see step-by-step directions.</p>';
  }
}

function renderQuickHeuristics() {
  const box=$('quick-h-grid');
  if (!box) return;
  if (!search || !search.heuristics?.length) {
    $('quick-h-goal').textContent='Goal: —';
    box.innerHTML='<span class="quick-h-empty">Run A* or register a route to view heuristic values.</span>';
    return;
  }
  $('quick-h-goal').textContent=`Goal: ${search.goal} · ${search.unit}`;
  box.innerHTML=search.heuristics
    .map(n=>`<div class="quick-h-item" title="h(${esc(n.node)}) = ${fmt(n.h,3)} ${esc(search.unit)} to ${esc(search.goal)}"><b>${esc(n.node)}</b><span>${fmt(n.h,3)}</span></div>`)
    .join('');
}

function renderHeuristics() {
  if (!search) return;
  const current=search.steps[step];
  const known=new Map(current.known.map(n=>[n.node,n]));
  const open=new Set(current.open.map(n=>n.node)), closed=new Set(current.closed);
  $('heuristic-target').textContent=`Start: ${search.start} → Goal: ${search.goal} · ${search.unit} · ${search.heuristics.length} nodes. All g★/h reference values use this same route and unit.`;
  $('heuristic-nodes').innerHTML=search.heuristics.map(n=>{
    const v=known.get(n.node), status=current.current===n.node?'Now':open.has(n.node)?'Open':closed.has(n.node)?'Closed':'Unseen';
    return `<tr class="${status==='Now'?'heuristic-active':''}" title="${esc(status)}: ${v?'A* g = '+fmt(v.g,3):'not yet discovered by A*'}"><td>${esc(n.node)}<small class="row-state">${status}</small></td><td>${fmt(n.g_reference,3)}</td><td>${fmt(n.h,3)}</td><td>${fmt(n.f_reference,3)}</td><td class="${v?'live-cost':'undiscovered'}">${fmt(v?.g,3)}</td></tr>`;
  }).join('');
  renderQuickHeuristics();
}
function renderStep() {
  if (!search) return;
  const count=search.steps.length,c=search.steps[step],n=c.selected;
  $('step-count').textContent=`${step+1} / ${count}`;
  $('prev').disabled=step===0; $('next').disabled=step===count-1;
  $('step-title').textContent=`Step ${step+1}: expand ${c.current}`;
  $('step-description').textContent=c.found?'Destination found. Follow the colored A* result in map view.':
    c.updates.length?c.updates.map(u=>`${u.node}: ${u.message}`).join(' · '):'No neighboring nodes improve the route.';
  $('math').textContent=`${fmt(n.g,3)} + ${fmt(n.h,3)} = ${fmt(n.f,3)}`;
  $('current-note').textContent=`${c.current}: A* live g accumulates actual road costs; h(${c.current}) is constant for this destination. Units: ${search.unit}.`;
  $('open-nodes').textContent=c.open.map(x=>x.node).join(', ')||'Empty';
  $('closed-nodes').textContent=c.closed.join(', ')||'Empty';
  $('scores').innerHTML=c.open.length?c.open.map(x=>`<tr><td>${esc(x.node)}</td><td>${fmt(x.g,3)}</td><td>${fmt(x.h,3)}</td><td><b>${fmt(x.f,3)}</b></td></tr>`).join(''):'<tr><td class="empty" colspan="4">OPEN list is empty</td></tr>';
  $('decision-reason').textContent=c.reason;
  $('neighbor-choices').innerHTML=c.choices.length ? [...c.choices].sort((a,b)=>(a.f??Infinity)-(b.f??Infinity)).map(x=>`<tr><td><b>${esc(x.node)}</b><small class="dir-inline">${esc(x.direction)}</small></td><td>${fmt(x.road_cost,3)}</td><td>${fmt(x.tentative_g,3)}</td><td>${fmt(x.h,3)}</td><td><b>${fmt(x.f,3)}</b></td><td>${esc(x.decision)}</td></tr>`).join('') : `<tr><td colspan="6" class="empty">${c.found?'Goal reached.':'No outgoing candidates.'}</td></tr>`;
  $('next-choice').textContent=c.found?'The goal has h(goal) = 0, so f(goal) = g(goal).':c.open.length?`Next OPEN node: ${c.open[0].node} (lowest f = ${fmt(c.open[0].f,3)} ${search.unit}).`:'No more reachable OPEN candidates. The goal cannot be reached.';
  renderHeuristics();
  renderDirections();
  $('result').className='result'+(step===count-1&&search.path.length?' finished':'');
  $('result').textContent=step===count-1?(search.path.length?
    `✓ Best route: ${search.path.join(' → ')} · g(goal) = ${fmt(search.cost,3)} ${search.unit} · ${fmt(search.distance)} km · ${fmt(search.minutes)} min`:
    'No reachable route. Try reopening a road.'):
    `Expanding nodes. Final path and cost will appear at step ${count}.`;
  renderMap();
}
async function runSearch(silent=false, origin=null, destination=null, switchView=true) {
  try {
    const payload={start:origin||$('origin').value,goal:destination||$('goal').value,mode:$('mode').value};
    const output=await api('search',payload);
    search=output.search; step=0;
    $('origin').value=payload.start; $('goal').value=payload.goal;
    renderStep();
    if (switchView) setMapView('astar');
    if (!silent) toast('A* is ready. Click Next step to follow g, h and f.');
  } catch(e){toast(e.message,true);}
}
async function loadIncidentTrace(phase='exit', switchView=false) {
  const incident=state.incidents.find(i=>i.id===focused);
  if (!incident || incident.status==='Completed') return;
  try {
    const answer=await api('incident-search',{id:incident.id,phase});
    tracePhase=phase;
    if (answer.search) {
      search=answer.search;step=0;
      $('origin').value=search.start;$('goal').value=search.goal;$('mode').value='balanced';
      renderStep();
    }
    if (switchView) setMapView('astar');
  }catch(e){toast(e.message,true);}
}
async function selectIncident(id) {
  focused=id;
  renderIncidents();setMapView('live');
  await loadIncidentTrace('exit');
  renderDirections();
}
async function action(endpoint,data={}) {
  try {
    const answer=await api(endpoint,data);
    state=answer.state;
    renderStats();renderVehicles();renderIncidents();renderMap();
    if (answer.incident_id) await selectIncident(answer.incident_id);
    else if (['road','reset','finish'].includes(endpoint)) {
      if (focused!==null) await loadIncidentTrace(tracePhase);
      else if (search) await runSearch(true,null,null,false);
    }
    renderDirections();
    if (answer.message) toast(answer.message);
  }catch(e){toast(e.message,true);renderIncidents();}
}
function connect() {
  const previewHeuristics=()=>runSearch(true, $('location').value || 'Gate', $('exit-target').value || $('goal').value || 'Medical Exit', false);
  const syncGate=()=>{const gate=state.gates_by_type[$('event').value]; $('exit-target').value=gate; $('gate-preview').innerHTML=`Selected exit: <b>${esc(gate)}</b> · Automatically linked to ${esc($('event').value)}.`; previewHeuristics();};
  $('event').onchange=syncGate;
  $('location').onchange=previewHeuristics;
  $('exit-target').onchange=()=>{$('event').value=Object.keys(state.gates_by_type).find(type=>state.gates_by_type[type]===$('exit-target').value);syncGate();};
  syncGate();
  $('trace-dispatch').onclick=()=>loadIncidentTrace('dispatch',true);
  $('trace-exit').onclick=()=>loadIncidentTrace('exit',true);
  $('register').onsubmit=e=>{e.preventDefault();action('register',{location:$('location').value,event:$('event').value,level:$('level').value});};
  $('search-form').onsubmit=e=>{e.preventDefault();focused=null;renderIncidents();runSearch();};
  $('demo').onclick=()=>action('demo');
  $('block').onclick=()=>action('road',{key:$('road').value,change:'block'});
  $('traffic').onclick=()=>action('road',{key:$('road').value,change:'traffic'});
  $('reset').onclick=()=>action('reset');
  $('live-view').onclick=()=>setMapView('live');
  $('astar-view').onclick=()=>setMapView('astar');
  $('prev').onclick=()=>{if(search&&step>0){step--;setMapView('astar');renderStep();}};
  $('next').onclick=()=>{if(search&&step<search.steps.length-1){step++;setMapView('astar');renderStep();}};
  $('map').onclick=e=>{const element=e.target.closest('[data-road]');if(element){$('road').value=element.dataset.road;toast(`Selected ${element.dataset.road.replace('|',' ↔ ')}: block or change traffic below.`);}};
  $('incidents').onclick=e=>{
    if (e.target.closest('.complete-label')) return;
    const el=e.target.closest('[data-focus]');if(el)selectIncident(Number(el.dataset.focus));
  };
  $('incidents').onchange=e=>{
    const input=e.target.closest('[data-finish]');
    if(input&&input.checked)action('finish',{id:Number(input.dataset.finish)});
  };
}
async function main() {
  try {
    state=await api('state');
    const names=Object.keys(state.places);
    fill('location',state.campus_locations,'Hostel');fill('origin',names,'Gate');fill('goal',names,'Hostel');fill('event',state.types,'Medical');
    fill('exit-target',Object.values(state.gates_by_type),state.gates_by_type.Medical);
    fill('road',state.roads.map(r=>rid(r.a,r.b)));
    for(const opt of $('road').options)opt.textContent=opt.value.replace('|',' ↔ ');
    connect();renderStats();renderVehicles();renderIncidents();renderMap();
    await runSearch(true,'Gate','Hostel',false);
  }catch(e){toast('Python server not connected. Run python main.py first.',true);}
}
main();
