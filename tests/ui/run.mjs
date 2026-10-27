/** Complete renderer contract/browser suite. Build the production bundle before running. */
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',import.meta.url));
for(const file of ['bridge','relay_browser','frame','navigation','response','live','live_browser','reading','drafts','draft_browser'])await new Promise((resolve,reject)=>{const child=spawn(process.execPath,['tests/ui/'+file+'.mjs'],{cwd:root,stdio:'inherit'});child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(new Error(file+' failed with '+code)));});
console.log('Complete Elma renderer suite passed');
