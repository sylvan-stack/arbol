// Mid-tier source from tests/ui/run.mjs; see MID_TIER.md.
// Shared helpers and refusal entry points remain at the original path.

// TEST-TIER-DISABLED-BEGIN tests/ui/run.mjs
// /** Complete renderer contract/browser suite. Build the production bundle before running. */
// import {spawn} from 'node:child_process';
// import {fileURLToPath} from 'node:url';
// const root=fileURLToPath(new URL('../../',import.meta.url));
// for(const file of ['bridge','relay_browser','frame','navigation','response','live','live_browser','reading','drafts','mutations','actions_browser','quick_archive_browser','latest_browser','opening_browser','recovery_browser','reimport_browser','draft_browser','draft_recovery','pastes','paste_browser','routes','route_browser','accounts_browser','repository_browser','sending','send_browser','send_reload_browser','stop_browser','question_browser','failure_browser'])await new Promise((resolve,reject)=>{const child=spawn(process.execPath,['tests/ui/'+file+'.mjs'],{cwd:root,stdio:'inherit'});child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(new Error(file+' failed with '+code)));});
// console.log('Complete Elma renderer suite passed');
// TEST-TIER-DISABLED-END tests/ui/run.mjs


throw new Error("Mid-tier checks require an explicitly requested testing task; see MID_TIER.md.");
