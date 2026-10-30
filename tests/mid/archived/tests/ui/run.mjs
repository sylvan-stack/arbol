// Preserve the original fixture/resource base after the tier move.
const _originalTestURL = new URL("../../../../ui/run.mjs", import.meta.url).href;
/** Retained mid-tier renderer selection. Build the production bundle before running. */
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',_originalTestURL));
for(const file of ["draft_browser", "draft_recovery", "failure_browser", "live_browser", "opening_browser", "paste_browser", "question_browser", "quick_archive_browser", "recovery_browser", "reimport_browser", "response", "send_browser", "send_reload_browser"])await new Promise((resolve,reject)=>{const child=spawn(process.execPath,['tests/ui/'+file+'.mjs'],{cwd:root,stdio:'inherit'});child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(new Error(file+' failed with '+code)));});
console.log('Retained Elma renderer selection passed; this is not full qualification');
