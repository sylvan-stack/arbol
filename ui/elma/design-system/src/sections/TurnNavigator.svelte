<script lang="ts">
 import Select from '../components/Select.svelte';
 let {index=3,total=5,busy=false,branches=[] as string[],branch=$bindable(''),onolder,onnewer,onopen}: {index?:number;total?:number;busy?:boolean;branches?:string[];branch?:string;onolder?:()=>void;onnewer?:()=>void;onopen?:()=>void}=$props();
 let local=$state<number|null>(null);const shown=$derived(local??index);
</script>
<nav class="stepper" aria-label="Conversation navigation">
 <button aria-label="Older turn" title="Older turn (⌘[)" disabled={busy||shown<=1} onclick={()=>onolder?onolder():local=shown-1}>‹</button>
 <button aria-label={`Turn ${shown} of ${total}. Jump to turn`} title="Jump to turn (⌘P)" onclick={onopen}><span>{shown}</span>/{total}</button>
 <button aria-label="Newer turn" title="Newer turn (⌘])" disabled={busy||shown>=total} onclick={()=>onnewer?onnewer():local=shown+1}>›</button>
{#if branches.length}<Select label="Advanced Root branch" options={branches} bind:value={branch}/>{/if}
</nav>
<style>.stepper{display:flex;align-items:center;gap:3px;flex-shrink:0}.stepper button{background:var(--panel);color:var(--text);border:1px solid transparent;border-radius:5px;min-height:26px;min-width:24px;padding:2px 6px;font:calc(11.5px * var(--font-scale))/1.3 var(--font-mono)}.stepper button:hover:not(:disabled){border-color:var(--border);background:var(--inset)}.stepper button:disabled{color:var(--disabled);cursor:default}</style>
