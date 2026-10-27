/** Complete renderer contract/browser suite. Build the production bundle before running. */
import {spawn} from 'node:child_process';
for(const file of ['bridge','relay_browser','frame','navigation','response','live','live_browser','reading'])await new Promise((resolve,reject)=>{const child=spawn(process.execPath,['tests/ui/'+file+'.mjs'],{stdio:'inherit'});child.once('error',reject);child.once('exit',code=>code===0?resolve():reject(new Error(file+' failed with '+code)));});
console.log('Complete Elma renderer suite passed');
