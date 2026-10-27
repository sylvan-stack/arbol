<script lang="ts">
 import TurnNavigator from './TurnNavigator.svelte';
 let {text='Preserve the useful parts of this interface.',index=1,total=1,busy=false,onolder,onnewer,onhistory,oncopy}: {text?:string;index?:number;total?:number;busy?:boolean;onolder?:()=>void;onnewer?:()=>void;onhistory?:()=>void;oncopy?:(text:string)=>Promise<void>}=$props();
 let expanded=$state(false),canExpand=$state(false),feedback=$state('');let prompt=$state<HTMLParagraphElement>();
 $effect(()=>{text;expanded=false;feedback='';});
 $effect(()=>{text;const element=prompt;if(!element)return;const measure=()=>{const height=parseFloat(getComputedStyle(element).lineHeight);canExpand=element.scrollHeight>height*3+1;};const observer=new ResizeObserver(measure);observer.observe(element);measure();return()=>observer.disconnect();});
 async function copy(){try{await(oncopy?.(text)??navigator.clipboard.writeText(text));feedback='Prompt copied';}catch{feedback='The prompt could not be copied.';}}
</script>
<section class="pinned" aria-label="Pinned user message">
 <div class="message"><p bind:this={prompt} class:expanded>{text}</p>{#if canExpand}<button class="expand" aria-expanded={expanded} onclick={()=>expanded=!expanded}>{expanded?'See less':'See more'}</button>{/if}</div>
 <div class="controls">{#if total>1}<TurnNavigator {index} {total} {busy} {onolder} {onnewer} onopen={onhistory}/>{/if}<button class="copy" onclick={copy}>Copy prompt</button></div>
 {#if feedback}<span class="feedback" role="status">{feedback}</span>{/if}
</section>
<style>
.pinned{position:relative;flex:none;display:flex;gap:12px;align-items:start;flex-wrap:wrap;border-bottom:1px solid var(--border);background:var(--panel);padding:12px 16px}.message{flex:1;min-width:0}.message p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;line-clamp:3;overflow:hidden;max-height:4.65em}.message p.expanded{display:block;max-height:min(50dvh,32rem);overflow-y:auto}.controls{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-left:auto}.expand,.copy{color:var(--link);background:none;border:1px solid transparent;border-radius:5px;padding:3px 5px;font-size:calc(11.5px * var(--font-scale))}.expand:hover,.copy:hover{background:var(--inset);border-color:var(--border)}.feedback{font-size:calc(11.5px * var(--font-scale));color:var(--muted);width:100%}
@media(max-width:600px){.message{flex-basis:100%}}
</style>
