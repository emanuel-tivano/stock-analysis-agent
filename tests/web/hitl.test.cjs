// Execute production JavaScript using Node built-ins and a DOM contract double.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../src/merval_agent/api/web/app.js'), 'utf8');

function harness(initial = {}, fetcher = async () => {throw Error('unexpected fetch');}) {
  const store = new Map(Object.entries(initial));
  let focused;
  class Element {
    constructor(tag) {this.tagName=tag; this.children=[]; this.events={}; this.dataset={}; this.classList={toggle(){}}; this.value=''; this.checked=false; this.disabled=false; this.attrs={};}
    append(...nodes) {for (const node of nodes) {this.children.push(node); node.parent=this;}}
    prepend(node) {this.children.unshift(node); node.parent=this;}
    addEventListener(name, fn) {this.events[name]=fn;}
    setAttribute(k,v) {this.attrs[k]=v;}
    focus() {focused=this;}
    scrollIntoView() {}
    replaceChildren(...nodes) {this.children=[]; this.append(...nodes);}
    remove() {this.parent.children=this.parent.children.filter(n=>n!==this);}
    querySelectorAll(tag) {return this.children.flatMap(n=>[...(n.tagName===tag?[n]:[]), ...n.querySelectorAll(tag)]);}
    get lastElementChild() {return this.children.at(-1);}
    requestSubmit() {this.events.submit({preventDefault(){}});}
  }
  const ids = Object.fromEntries(['composer','message','send','messages','conversation','status','error','new-conversation'].map(id=>[id,new Element(id)]));
  const document = {
    querySelector: selector=>ids[selector.slice(1)], querySelectorAll:()=>[],
    createElement:tag=>new Element(tag), createTextNode:text=>Object.assign(new Element('text'),{textContent:text}),
    getElementById:id=>ids.messages.querySelectorAll('article').find(n=>n.id===id),
  };
  let sequence=0;
  const context = vm.createContext({document, sessionStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)}, crypto:{randomUUID:()=>`opaque-key-${++sequence}`}, fetch:fetcher, URL, console});
  vm.runInContext(source+'\nglobalThis.ui={renderAction,renderAgentMessage,submitMessage,recoverAction,renderTechnicalDetails};',context);
  return {ui:context.ui,ids,store,focused:()=>focused, elements:tag=>ids.messages.querySelectorAll(tag)};
}
const proposal=()=>({action_id:'action-opaque',session_id:'session-opaque',trace_id:'trace-opaque',ticker:'GGAL',as_of:'2026-09-17',version:1,status:'PENDING',summary:'<img onerror=alert(1)>',proposed_payload:{focus:'overview',include_sections:['overview','trend','momentum','risk'],review_note:''},available_actions:['approve','modify','reject']});
const button=(h,name)=>h.elements('button').find(e=>e.textContent===name);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const response=(data,status=200)=>({ok:status<400,status,json:async()=>data});

test('PAUSED renders safe text, accessible controls and stores only IDs',()=>{
  const h=harness(); h.ui.renderAgentMessage({status:'PAUSED',pending_action:proposal()});
  assert.equal(h.elements('button').length,3);
  assert.equal(h.elements('textarea')[0].maxLength,500);
  assert.equal(h.elements('p')[0].textContent,'<img onerror=alert(1)>');
  assert.equal(h.elements('img').length,0);
  assert.deepEqual([...h.store.values()],['session-opaque','action-opaque']);
  assert.equal(h.focused().tagName,'h3');
  assert(h.elements('p').some(p=>p.attrs['aria-live']==='polite'));
});
test('loading prevents double submit; rejection clears active ID',async()=>{
  let complete, calls=0;
  const h=harness({},()=>{calls++;return new Promise(r=>complete=r);});
  h.ui.renderAction(proposal());
  const click=button(h,'Rechazar').events.click; click(); click();
  assert.equal(calls,1);
  assert(h.elements('button').every(b=>b.disabled));
  assert.equal(h.elements('article')[0].attrs['aria-busy'],'true');
  complete(response({action:{...proposal(),status:'REJECTED',available_actions:[]},message:'Rechazado',result:null}));
  await flush();
  assert.equal(h.store.has('stock-analysis-action-id'),false);
  assert.equal(h.elements('button').length,0);
  assert.equal(h.focused().tagName,'h3');
});
test('modify sends allowed fields; unsaved changes cannot be approved',async()=>{
  const requests=[];
  const h=harness({},async(u,o)=>{requests.push(JSON.parse(o.body));return response({action:{...proposal(),version:2,status:'MODIFIED',proposed_payload:{...proposal().proposed_payload,focus:'momentum'}},message:'Pendiente',result:null});});
  h.ui.renderAction(proposal()); h.elements('select')[0].value='momentum';
  button(h,'Aprobar').events.click(); assert.equal(requests.length,0);
  button(h,'Modificar').events.click(); await flush();
  assert.deepEqual(Object.keys(requests[0].changes),['focus','include_sections','review_note']);
  assert.equal(requests[0].changes.focus,'momentum');
  assert.equal(h.store.get('stock-analysis-action-id'),'action-opaque');
});
test('network retries reuse key and restore controls',async()=>{
  const requests=[];
  const h=harness({},async(u,o)=>{requests.push(JSON.parse(o.body));throw Error('connection lost');});
  h.ui.renderAction(proposal()); button(h,'Aprobar').events.click(); await flush();
  assert(h.elements('button').every(b=>!b.disabled));
  button(h,'Aprobar').events.click(); await flush();
  assert.equal(requests[0].idempotency_key,requests[1].idempotency_key);
});
test('conflict GETs current version and never auto-approves',async()=>{
  const methods=[];
  const h=harness({},async(u,o)=>{methods.push(o?.method||'GET');return o?response({detail:'conflict'},409):response({action:{...proposal(),version:2,status:'MODIFIED'},result:null});});
  h.ui.renderAction(proposal()); button(h,'Aprobar').events.click(); await flush();
  assert.deepEqual(methods,['POST','GET']);
  assert(h.elements('p').some(p=>p.textContent?.includes('Versión 2')));
});
test('reload restores result and escapes human note',async()=>{
  const result={ticker:'GGAL',as_of:'2026-09-17',trace_id:'trace-opaque',publication:{sections:{overview:'Resumen'},editorial:{review_note:'<script>bad()</script>'}}};
  const h=harness({'stock-analysis-action-id':'action-opaque','stock-analysis-session-id':'session-opaque'},async()=>response({action:{...proposal(),status:'EXECUTED',available_actions:[]},result}));
  await flush();
  assert.equal(h.store.has('stock-analysis-action-id'),false);
  assert.equal(h.elements('script').length,0);
  assert(h.elements('p').some(p=>p.textContent==='<script>bad()</script>'));
});
test('invalid sections send nothing; new conversation preserves pending action',()=>{
  const h=harness(); h.ui.renderAction(proposal());
  h.elements('input').forEach(c=>c.checked=false); button(h,'Modificar').events.click();
  assert.equal(h.focused().tagName,'select');
  h.ids['new-conversation'].events.click();
  assert.equal(h.store.get('stock-analysis-action-id'),'action-opaque');
});
test('422 keeps pending action with a human error',async()=>{
  const h=harness({},async()=>response({detail:[]},422));h.ui.renderAction(proposal());
  button(h,'Modificar').events.click();await flush();
  assert(h.elements('p').some(p=>p.textContent?.includes('modificación no es válida')));
  assert(h.elements('button').every(b=>!b.disabled));
});

for (const [code,label] of Object.entries({CONFIRMED:'Confirma el movimiento de la última barra histórica',NOT_CONFIRMED:'Volumen disponible, sin confirmación',UNAVAILABLE:'Sin datos suficientes para evaluar volumen'})) {
  test(`volume ${code} renders separately with its own date`,()=>{
    const h=harness();
    h.ui.renderTechnicalDetails(h.ids.messages,{technical_details:{
      trend:{label:'Bajista'},momentum:{label:'Bajista'},momentum_state:{label:'Bajista'},
      confirmation:{label:'Sin confirmación conjunta'},confidence:{label:'Media'},
      volume_confirmation:{code,label},volume_as_of:'2026-09-23',sample_size_display:'126',
      trace_id:'trace',missing_indicators:{},warnings:[],signal_explanations:[]
    }});
    assert(h.elements('dt').some(n=>n.textContent==='Confirmación'));
    assert(h.elements('dt').some(n=>n.textContent==='Confirmación por volumen al 23/09/2026'));
    assert(h.elements('dd').some(n=>n.textContent===label));
    assert(h.elements('dd').some(n=>n.textContent==='Sin confirmación conjunta'));
  });
}
