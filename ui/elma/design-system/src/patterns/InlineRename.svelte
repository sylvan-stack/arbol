<script lang="ts">
 import {onMount} from 'svelte';
 import Button from '../components/Button.svelte';
 let {value='',label='Name',max,busy=false,problem='',onsave,oninput,oncancel}:{value?:string;label?:string;max?:number;busy?:boolean;problem?:string;onsave?:()=>void;oninput?:(value:string)=>void;oncancel?:()=>void}=$props();
 let input=$state<HTMLInputElement>();
 const id=$props.id();
 const count=$derived(Array.from(value.trim()).length);
 const invalid=$derived(!!max&&count>max||value.includes('\0'));
 onMount(()=>{input?.focus();input?.select();});
 $effect(()=>{if(!busy)input?.focus();});
 function keys(event:KeyboardEvent){
  if(event.isComposing)return;
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!busy)oncancel?.();}
  if(event.key==='Enter'){event.preventDefault();event.stopPropagation();if(!busy&&!invalid)onsave?.();}
 }
</script>
<form class="inline-rename" aria-label={'Rename '+label.toLowerCase()} onsubmit={event=>{event.preventDefault();if(!busy&&!invalid)onsave?.();}}>
 <label class="label" for={id}>{label}</label>
 <input bind:this={input} {id} aria-describedby={id+'-help'} aria-invalid={invalid} disabled={busy} {value} onkeydown={keys} oninput={event=>oninput?.(event.currentTarget.value)}/>
 <div class="buttons"><Button label="OK" type="submit" tone="primary" disabled={invalid||busy}/><Button label="Cancel" disabled={busy} onclick={oncancel}/></div>
 <span class="help" id={id+'-help'}>{#if busy}Saving…{:else if invalid}{value.includes('\0')?'A name cannot contain NUL.':`Use at most ${max} characters (${count} entered).`}{:else if max}{count}/{max} characters{/if}</span>
 {#if problem}<span class="problem" role="alert">{problem}</span>{/if}
</form>
<style>
 .inline-rename{display:flex;align-items:center;flex-wrap:wrap;gap:6px;min-width:0;font:inherit}.label{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}input{min-width:80px;width:min(32ch,100%);flex:1;border:1px solid var(--border);border-radius:4px;background:var(--inset);color:var(--text);padding:5px 8px;font:inherit}.buttons{display:flex;gap:5px}.help,.problem{flex-basis:100%;font-size:.8em;font-weight:400;overflow-wrap:anywhere}.help{color:var(--muted)}.problem{color:var(--failure)}
</style>
