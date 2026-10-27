<script lang="ts">
 export interface HistoryRow {id:string;number:number;message:string;depth?:number;branchLabel?:string}
 let {items=[{id:'first',number:1,message:'A fictional first prompt'},{id:'second',number:2,message:'Compare the shared patterns'},{id:'third',number:3,message:'Build the useful components'}],selected='',more=false,busy=false,problem='',onselect,onmore,branching=false}: {items?:HistoryRow[];selected?:string;more?:boolean;busy?:boolean;problem?:string;onselect?:(id:string)=>void;onmore?:()=>void;branching?:boolean}=$props();
 let query=$state(''),local=$state('');const rows=$derived((branching?[...items]:[...items].reverse()).filter(item=>item.message.toLocaleLowerCase().includes(query.toLocaleLowerCase())));
 function choose(id:string){local=id;onselect?.(id);}
 function keys(event:KeyboardEvent){if(event.metaKey||event.ctrlKey||event.altKey||event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement)return;const digit='1234567890'.indexOf(event.key);if(digit>=0&&rows[digit]){event.preventDefault();choose(rows[digit].id);}}
</script>
<svelte:window onkeydown={keys}/>
<section class="history" aria-label="Conversation history">
 <label>Search <input aria-label="Search loaded messages" type="search" bind:value={query}/></label>
 {#if problem}<p role="alert">{problem}</p>{/if}
 <p class="scope">{rows.length} of {items.length} loaded prompts</p>
 {#if branching}<p class="scope">Advanced Root proposal: alternative branches are outside First Sapling.</p>{/if}
 <ul>{#each rows as row,i}<li style:margin-left={branching?Math.min(row.depth??0,4)*12+'px':undefined}><button data-history-row aria-current={(selected||local)===row.id?'true':undefined} onclick={()=>choose(row.id)}><span class="turn">Turn {row.number}</span><span class="message">{row.branchLabel?row.branchLabel+' · ':''}{row.message}</span>{#if i<10}<kbd>{(i+1)%10}</kbd>{/if}</button></li>{/each}</ul>
 {#if !rows.length}<p>No matching loaded messages.</p>{/if}
 {#if more}<button class="more" disabled={busy||!onmore} onclick={onmore}>{busy?'Loading…':'Load older turns'}</button>{/if}
</section>
<style>
.history{display:flex;flex-direction:column;gap:12px;min-width:0}.history label{display:flex;flex-direction:column;gap:4px;color:var(--muted);font-size:calc(12px * var(--font-scale))}.history input{background:var(--inset);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:8px;min-width:0;max-width:100%}.scope{color:var(--muted);font-size:calc(11.5px * var(--font-scale))}ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:4px}li button{display:flex;align-items:start;gap:12px;text-align:left;width:100%;padding:10px;background:transparent;color:var(--text);border:1px solid transparent;border-radius:5px}li button:hover,li button[aria-current]{background:var(--selected);border-color:var(--border)}.turn,kbd{font:calc(11.5px * var(--font-scale))/1.5 var(--font-mono);color:var(--muted);flex-shrink:0}.message{flex:1;min-width:0;overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;line-clamp:3;overflow:hidden}.more{align-self:start;border:1px solid var(--border);border-radius:5px;background:var(--inset);color:var(--text);padding:6px 12px}
</style>
