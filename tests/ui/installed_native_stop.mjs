/** Deliberate installed First Sapling journey. Never included in the default UI suite. */
import {readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {chromium} from '../../ui/elma/node_modules/playwright/index.mjs';
assert.equal(process.env.ARBOL_INSTALLED_JOURNEY,'1','An installed live journey requires its explicit switch.');
const input=JSON.parse(await readFile(process.argv[2],'utf8'));
const reservations=(await readFile(input.budget,'utf8')).trim().split('\n').map(JSON.parse);
assert(reservations.some(r=>r.attempt===input.attempt&&r.case===input.case&&r.prompt===input.prompt));
await writeFile(input.started,JSON.stringify({attempt:input.attempt,at:new Date().toISOString()})+'\n',{mode:0o600,flag:'wx'});
assert(['stop'].includes(input.case));assert([['claude','test-anthropic'],['codex','test-chatgpt']].some(([d,s])=>d===input.driver&&s===input.subscription));
const browser=await chromium.launch({headless:true}),context=await browser.newContext({viewport:{width:1280,height:900},permissions:['clipboard-read','clipboard-write']});
const proof={attempt:input.attempt,root:'sapling',driver:input.driver,subscription:input.subscription,model:input.model,build:input.build,frames:[],errors:[],remote:[],reopened:false,streamedBeforeClose:false,streamedAfterReopen:false};
let sent,canonical,ended=false,page;
async function until(check,seconds=120){const end=Date.now()+seconds*1000;while(Date.now()<end){const v=await check();if(v)return v;await new Promise(r=>setTimeout(r,20));}throw new Error('Installed first-path observation timed out');}
function observe(p){p.on('pageerror',e=>proof.errors.push(e.message));p.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:'))proof.remote.push(r.url());});p.on('websocket',ws=>{
 ws.on('framesent',frame=>{try{const r=JSON.parse(String(frame.payload));if(r.type==='call'&&r.method==='chat.send'){assert(!sent||sent.exchange===r.params.exchange);sent=r.params;proof.sent=sent;}}catch(e){proof.errors.push(String(e));}});
 ws.on('framereceived',frame=>{try{const r=JSON.parse(String(frame.payload));if(r.type==='hello')assert.equal(r.build,input.build);if(r.type!=='event')return;const e=r.event;proof.frames.push(e);if(!sent)return;
 if(e.kind==='lines'&&e.exchange===sent.exchange){for(const line of e.lines){if(line.end)ended=true;if(['text_delta','text'].includes(line.event?.type)&&line.event.text){if(proof.reopened)proof.streamedAfterReopen=true;else proof.streamedBeforeClose=true;}}}
 const rows=e.kind==='saved'?[e.exchange]:e.kind==='snapshot'&&Array.isArray(e.exchanges)?e.exchanges:[];for(const row of rows)if(row.exchange===sent.exchange&&['completed','failed','cancelled','interrupted'].includes(row.state)){canonical=row;ended=true;}
 }catch(e){proof.errors.push(String(e));}});
 });}
try{
 page=await context.newPage();observe(page);await page.goto(input.url);await page.getByRole('heading',{name:'Elma Chat · First Sapling - New Chat',exact:true}).waitFor();await page.getByRole('button',{name:/^arbol-trunk ⌘\d$/}).click();await page.getByRole('button',{name:new RegExp('^'+input.driver+' · '+input.subscription+' ⌃[1-9]$')}).click();
 for(let n=0;n<20;n++){const model=page.getByRole('button',{name:/^Model:/});const label=await model.innerText();if(label.split('⌃')[0].trim()==='Model: '+input.model)break;assert(n<19,'The explicit bounded model is not in the actual catalogue');await model.click();}
 if(input.effort){for(let n=0;n<8;n++){const effort=page.getByRole('button',{name:/^Thinking:/});if((await effort.innerText()).split('⌃')[0].trim()==='Thinking: '+input.effort)break;assert(n<7,'Requested effort unavailable');await effort.click();}}
 await until(async()=>!(await page.getByRole('textbox',{name:'Message',exact:true}).inputValue()));await page.getByRole('textbox',{name:'Message',exact:true}).fill(input.prompt);await page.keyboard.press('Meta+Enter');await until(()=>sent);assert.equal(sent.workingFolder,input.folder);assert.equal(sent.route.subscription,input.subscription);assert.equal(sent.route.model,input.model);assert.equal(sent.message,input.prompt);
 await until(()=>proof.streamedBeforeClose||canonical);assert(proof.streamedBeforeClose&&!canonical,'Stop needs actual native streamed text before completion');await page.keyboard.press('Meta+Escape');await page.keyboard.press('Meta+Escape');await page.getByText('Stopping…',{exact:true}).waitFor();await until(()=>canonical);assert.equal(canonical.state,'cancelled');await page.getByText('⏹ Stopped',{exact:true}).waitFor();proof.canonical=canonical;const target=new URL(input.url);target.searchParams.set('open',sent.chat);await page.goto(target.href);await page.getByText('⏹ Stopped',{exact:true}).waitFor();assert.deepEqual(proof.errors,[]);assert.deepEqual(proof.remote,[]);await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('paper');await page.screenshot({path:input.screenshot,fullPage:true});proof.passed=true;proof.actualNativeStop=true;proof.completedAt=new Date().toISOString();await writeFile(input.result,JSON.stringify(proof,undefined,2)+'\n',{mode:0o600,flag:'wx'});console.log(JSON.stringify({nativeStopPassed:true,chat:sent.chat,exchange:sent.exchange,state:canonical.state}));
}catch(error){proof.failure=String(error);proof.canonical=canonical;if(page&&!page.isClosed())await page.screenshot({path:input.screenshot+'.failed.png',fullPage:true});await writeFile(input.result+'.failed.json',JSON.stringify(proof,undefined,2)+'\n',{mode:0o600,flag:'wx'});throw error;}finally{await browser.close();}
