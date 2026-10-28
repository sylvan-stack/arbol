<script lang="ts">
  import TextField from '../components/TextField.svelte';
  import KbdHint from '../components/KbdHint.svelte';
  import Button from '../components/Button.svelte';
  export interface CommandRow {id:string;label:string;detail?:string;shortcut?:string;disabled?:boolean;action?:{label:string;disabled?:boolean}}
  let {commands=['Seqoya · Dashboard','Seqoya · Organizations','Seqoya · Repos','Elma · New chat','Willo · Stations','Willo · Telegram','Oaken · Swimlanes','Oaken · Grafts'],rows,title='Go to page',emptyLabel='No matching commands.',searchable=true,numbered=true,onselect,onaction}: {commands?:string[];rows?:CommandRow[];title?:string;emptyLabel?:string;searchable?:boolean;numbered?:boolean;onselect?:(id:string)=>void;onaction?:(id:string)=>void}=$props();
  let query=$state(''),selected=$state(''),index=$state(0),root:HTMLElement;
  const visible=$derived((rows??commands.map((label):CommandRow=>({id:label,label}))).filter(row=>(row.label+' '+(row.detail??'')).toLowerCase().includes(query.toLowerCase())));
  $effect(()=>{if(index>=visible.length)index=Math.max(0,visible.length-1);});
  function choose(row:CommandRow){if(row.disabled)return;if(onselect)onselect(row.id);else selected=row.label;}
  function handleKeys(e:KeyboardEvent){
    if(e.defaultPrevented||!root?.contains(document.activeElement)||e.altKey||e.metaKey||e.ctrlKey||e.isComposing)return;
    if(e.key==='Enter'&&e.target instanceof Element&&e.target.closest('[data-row-action]'))return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();index=(index+(e.key==='ArrowDown'?1:-1)+visible.length)%Math.max(visible.length,1);root.querySelectorAll<HTMLButtonElement>('[data-command-row]')[index]?.focus();return;}
    if(e.key==='Enter'&&visible[index]){e.preventDefault();choose(visible[index]);return;}
    if(searchable&&e.target instanceof HTMLInputElement)return;
    const shortcut=visible.find(row=>row.shortcut?.toLowerCase()===e.key.toLowerCase());
    const digit=numbered&&/^[0-9]$/.test(e.key)?visible[e.key==='0'?9:Number(e.key)-1]:undefined;
    if(shortcut||digit){e.preventDefault();choose((shortcut??digit)!);}
  }
</script>
<svelte:window onkeydown={handleKeys}/>
<section bind:this={root} class="panel stack" aria-label={title}>
  <h2>{title}</h2>
  {#if searchable}<TextField label="Search destinations" bind:value={query} type="search"/>{/if}
  {#if searchable}<p class="eyebrow">{query?'Results':'Recent & suggested'}</p>{/if}
  <div class="stack" style="gap:4px">
    {#each visible as row,i(row.id)}<div class="command-row"><button data-command-row class:active={i===index} disabled={row.disabled} onfocus={()=>index=i} onclick={()=>choose(row)}><span class="entry"><span>{row.label}</span>{#if row.detail}<span class="detail">{row.detail}</span>{/if}</span>{#if row.shortcut||numbered&&i<10}<kbd>{row.shortcut??(i===9?'0':String(i+1))}</kbd>{/if}</button>{#if row.action}<span data-row-action><Button label={row.action.label} disabled={row.disabled||row.action.disabled||!onaction} onclick={()=>onaction?.(row.id)}/></span>{/if}</div>{:else}<p class="muted">{emptyLabel}</p>{/each}
  </div>
  <KbdHint keys={['↑','↓','↵']} label="Choose"/>{#if selected}<p class="notice" role="status">Selected {selected}</p>{/if}
</section>
<style>
.command-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.command-row>button{flex:1 1 240px;min-width:0}button{display:flex;justify-content:space-between;gap:16px;text-align:left;min-height:40px;padding:8px 12px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--text)}button.active{background:var(--selected);border-color:var(--border)}.entry{display:flex;flex-direction:column;min-width:0;overflow-wrap:anywhere}.detail,kbd{color:var(--muted)}kbd{flex-shrink:0}.detail{font-size:.9em}button:disabled{opacity:.55}
</style>
