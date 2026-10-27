import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import assert from 'node:assert/strict';
import { chromium } from '../../ui/elma/node_modules/playwright/index.mjs';
const child=spawn(process.env.ELMA_TEST_PYTHON||'.venv/bin/python',['-I','-B',process.env.ELMA_TEST_FIXTURE||'tests/ui/fixture_backend.py','--bundle',process.env.ELMA_TEST_BUNDLE||'ui/elma/dist','--build',process.env.ELMA_TEST_BUILD||'development'],{stdio:['pipe','pipe','pipe']});
let errors='';child.stderr.on('data',data=>errors+=data);const lines=createInterface({input:child.stdout});
const url=await new Promise((resolve,reject)=>{lines.once('line',resolve);child.once('exit',()=>reject(new Error('Fixture ended early')));});
const browser=await chromium.launch({headless:true}).catch(async error=>{const exit=new Promise(resolve=>child.once('exit',resolve));child.kill('SIGTERM');await exit;lines.close();throw error;});const context=await browser.newContext();const page=await context.newPage();const pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));
try {
 await page.goto(url);await page.getByRole('heading',{name:/Elma Chat · Fixture Root/}).waitFor();
 assert(!page.url().includes('token='));assert(!page.url().includes('reloadedFor='),'The compiled renderer must match the backend Build on first hello');const cookies=await context.cookies();assert.equal(cookies.length,1);assert.equal(cookies[0].httpOnly,true);assert.equal(cookies[0].sameSite,'Strict');
 const unauth=await browser.newContext();const denied=await unauth.newPage();const response=await denied.goto(new URL(page.url()).origin);assert.equal(response.status(),403);await unauth.close();
 child.stdin.write(JSON.stringify({kind:'disconnect'})+'\n');await page.getByRole('status').filter({hasText:'Reconnecting…'}).waitFor();await page.getByRole('heading',{name:/Elma Chat · Fixture Root/}).waitFor();assert.deepEqual(pageErrors,[]);
 console.log('relay.browser-cookie/csp/websocket/lost/newhello: passed against real loopback HTTP/WS and private stand-in Unix socket');
} finally {
 await browser.close();const exited=new Promise(resolve=>child.once('exit',resolve));child.kill('SIGTERM');const code=await exited;assert.equal(code,0);assert.equal(errors,'');lines.close();
}
