
// LOW TIER — DO NOT ENABLE OR RECREATE
// Historical examples only. Read before adding related tests; never execute.
// LOW-TIER-BEGIN: tests/mid/archived/tests/ui/pastes.mjs
// Reason: Reviewed browser source: ordinary presentation/selection or a controller-level repetition of the retained real-relay Draft/send/recovery checks; it adds no distinct consequential observation sufficient to justify another browser run. Case reviewed: Standalone pastes check program; its combined scenarios are retained together.
// Source: arbol@f66335c7e203794dc84e40fe3106e85f8cae2dd6:tests/mid/archived/tests/ui/pastes.mjs
// Historical fixtures and class context are available at the source revision; no active dependencies restored.
// LOW-TIER-SOURCE-BEGIN
// // Preserve the original fixture/resource base after the tier move.
// const _originalTestURL = new URL("../../../../ui/pastes.mjs", import.meta.url).href;
// import assert from 'node:assert/strict';
// import { createServer } from '../../../../../ui/elma/node_modules/vite/dist/node/index.js';
// import { chromium } from '../../../../../ui/elma/node_modules/playwright/index.mjs';
// const server=await createServer({root:new URL('../../ui/elma',_originalTestURL).pathname,configFile:new URL('../../ui/elma/vite.config.ts',_originalTestURL).pathname,server:{host:'127.0.0.1',port:0}});await server.listen();
// const browser=await chromium.launch({headless:true}),page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
// try{
//  await page.addInitScript(()=>{window.posts=[];window.webkit={messageHandlers:{arbol:{postMessage:raw=>window.posts.push(raw)}}};});await page.goto(server.resolvedUrls.local[0]+'tests/drafts.html');await page.waitForFunction(()=>window.fixture);
//  await page.evaluate(()=>{
//   const {Bridge,Drafts,parseWire,stringifyWire}=window.fixture;window.parse=parseWire;window.receive=value=>window.arbolBridge.receive(stringifyWire(value));window.bridge=new Bridge({build:'1'});window.receive({type:'hello',bridge:1,root:{root:'t1',name:'Test',status:'working',current:true},build:'1'});window.manager=new Drafts(window.bridge);window.editor=window.manager.select('t1',{folder:'/fictional/pastes'});const sub=window.posts.map(parseWire).find(v=>v.topic==='draft');window.receive({type:'event',id:sub.id,seq:1,event:{kind:'snapshot',draft:null}});window.calls=method=>window.posts.map(parseWire).filter(v=>v.method===method);window.sent=[];
//  });
//  assert.equal(await page.evaluate(()=>window.editor.pastes.paste('😀'.repeat(9999),{start:0,end:0})),false);assert.equal(await page.evaluate(()=>window.calls('paste.save').length),0);
//  const pending=await page.evaluate(()=>{
//   window.editor.input('AoldZ');window.editor.pastes.paste('😀'.repeat(10000),{start:1,end:4});window.editor.input('PREFIX '+window.editor.text);window.editor.pastes.paste('b'.repeat(10000),{start:window.editor.text.length,end:window.editor.text.length});window.editor.pastes.requestSend(()=>window.sent.push(window.editor.text));window.editor.pastes.requestSend(()=>window.sent.push('DUPLICATE'));void window.editor.flush();return{count:window.editor.pastes.pending,queued:window.editor.pastes.queued,drafts:window.calls('draft.save').length,rawKept:Object.values(sessionStorage)[0].includes('😀')};
//  });assert.deepEqual(pending,{count:2,queued:true,drafts:0,rawKept:true});
//  await page.evaluate(()=>{const call=window.calls('paste.save')[1];window.receive({type:'reply',id:call.id,result:{path:'/fictional/Private Root/pastes/two.txt'}});});await page.waitForFunction(()=>window.editor.pastes.pending===1);assert.equal(await page.evaluate(()=>window.sent.length),0);
//  await page.evaluate(()=>{const call=window.calls('paste.save')[0];window.receive({type:'reply',id:call.id,result:{path:'/fictional/Private Root/pastes/one.txt'}});});await page.waitForFunction(()=>window.editor.pastes.pending===0);const result=await page.evaluate(()=>({text:window.editor.text,sent:window.sent,draft:window.calls('draft.save').at(-1)?.params.text}));
//  const expected='PREFIX A[Pasted text (10,000 characters)](</fictional/Private Root/pastes/one.txt>)Z[Pasted text (10,000 characters)](</fictional/Private Root/pastes/two.txt>)';assert.equal(result.text,expected);assert.deepEqual(result.sent,[expected]);assert.equal(result.draft,expected);
//  await page.evaluate(()=>{const call=window.calls('draft.save').at(-1);window.receive({type:'reply',id:call.id,result:{revision:1}});});await page.waitForFunction(()=>!window.editor.saving);
//  await page.evaluate(()=>{window.editor.pastes.paste('x'.repeat(10000),{start:0,end:0});window.editor.pastes.requestSend(()=>window.sent.push('BAD'));const call=window.calls('paste.save').at(-1);window.receive({type:'reply',id:call.id,error:{code:'disk_full',message:'The paste file could not be saved'}});});await page.waitForFunction(()=>!window.editor.pastes.pending);assert.equal(await page.evaluate(()=>window.sent.length),1);assert(await page.evaluate(()=>window.editor.text.startsWith('x'.repeat(10000))));assert.match(await page.evaluate(()=>window.editor.pastes.problem),/not saved.*paste file/);
//  await page.evaluate(()=>{window.editor.input('');window.editor.pastes.paste('z'.repeat(10000),{start:0,end:0});window.editor.pastes.requestSend(()=>window.sent.push('EDIT OVERWRITTEN'));window.editor.input('zzUSER EDIT'+window.editor.text.slice(2));const call=window.calls('paste.save').at(-1);window.receive({type:'reply',id:call.id,result:{path:'/fictional/root/pastes/edited.txt'}});});await page.waitForFunction(()=>!window.editor.pastes.pending);assert(await page.evaluate(()=>window.editor.text.startsWith('zzUSER EDIT')));assert.equal(await page.evaluate(()=>window.sent.length),1);assert.match(await page.evaluate(()=>window.editor.pastes.problem),/Your edits are kept/);
//  await page.evaluate(()=>{window.manager.close();window.bridge.close();});assert.deepEqual(errors,[]);console.log('Paste protocol: 10,000 Unicode codepoint threshold, selected insertion, edit-aware ranges, out-of-order files, raw recovery, Draft flush waits for links, one queued send, failure/overlapping edits preserve text and cancel queue passed');
// }finally{await browser.close();await server.close();}
// LOW-TIER-SOURCE-END
// LOW-TIER-END
