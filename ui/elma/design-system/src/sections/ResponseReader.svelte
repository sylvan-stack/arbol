<script lang="ts">
 import { tick,type ComponentProps } from 'svelte';
 import Response from './Response.svelte';
 export interface ReadPosition {top:number;following:boolean}
 let {identity,response,snapshot=0,positions=new Map<string,ReadPosition>()}:{identity:string;response:ComponentProps<typeof Response>;snapshot?:number;positions?:Map<string,ReadPosition>}=$props();
 let area=$state<HTMLDivElement>(),content=$state<HTMLDivElement>(),beacon=$state(false);
 let active='',generation=-1,wasComplete=false,following=true,desired:number|'threshold'|null=null,programmatic=false,frame=0;
 const bottom=()=>area?Math.max(0,area.scrollHeight-area.clientHeight):0;
 function answerTop(){const marker=area?.querySelector<HTMLElement>('[data-answer-threshold]');return area&&marker?Math.max(0,Math.min(bottom(),marker.getBoundingClientRect().top-area.getBoundingClientRect().top+area.scrollTop)):null;}
 function save(){if(area&&active)positions.set(active,{top:typeof desired==='number'?desired:area.scrollTop,following});}
 function move(top:number){if(!area)return;programmatic=true;area.scrollTop=top;cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{programmatic=false;});}
 function measure(){if(!area)return;if(following&&response.streaming)move(bottom());else if(desired==='threshold'){const top=answerTop();if(top!==null)move(top);}else if(typeof desired==='number')move(desired);const marker=area.querySelector<HTMLElement>('[data-answer-threshold]');beacon=!response.streaming&&!!marker&&marker.getBoundingClientRect().top>=area.getBoundingClientRect().bottom;save();}
 function release(){desired=null;following=false;}
 function scroll(){if(!area)return;if(!programmatic){desired=null;following=bottom()-area.scrollTop<=2;save();}const marker=area.querySelector<HTMLElement>('[data-answer-threshold]');beacon=!response.streaming&&!!marker&&marker.getBoundingClientRect().top>=area.getBoundingClientRect().bottom;}
 function jumpAnswer(){release();const top=answerTop();if(top!==null)move(top);measure();}
 export function scrollToEdge(edge:'top'|'bottom'){release();following=edge==='bottom'&&!!response.streaming;move(edge==='top'?0:bottom());measure();}
 function keys(event:KeyboardEvent){if(!area||event.defaultPrevented||document.querySelector('dialog[open]')||!event.metaKey||!event.shiftKey||!event.altKey||!['Digit7','Digit8'].includes(event.code))return;event.preventDefault();release();const stops=[0,answerTop(),bottom()].filter((v):v is number=>v!==null).sort((a,b)=>a-b).filter((v,i,values)=>i===0||v-values[i-1]>1);const current=area.scrollTop;move(event.code==='Digit7'?(stops.find(v=>v>current+2)??bottom()):([...stops].reverse().find(v=>v<current-2)??0));measure();}
 $effect.pre(()=>{identity;snapshot;if(area&&active)save();});
 $effect(()=>{const key=identity,nextGeneration=snapshot,complete=!response.streaming;response.blocks;if(!area)return;
  if(key!==active){active=key;const position=positions.get(key);following=position?.following??!complete;desired=position?.top??(complete?'threshold':null);}
  else if(nextGeneration!==generation){const position=positions.get(key);following=position?.following??following;desired=position?.top??area.scrollTop;}
  else if(complete&&!wasComplete&&following){following=false;desired='threshold';}
  generation=nextGeneration;wasComplete=complete;void tick().then(measure);
 });
 $effect(()=>{if(!area||!content)return;const observer=new ResizeObserver(measure);observer.observe(area);observer.observe(content);return()=>{observer.disconnect();cancelAnimationFrame(frame);};});
</script>
<svelte:window onkeydown={keys}/>
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions (Wheel, touch and scrolling keys control this focusable reading region, without an activation action.) -->
<div class="response-scroll" role="region" tabindex="0" aria-label="Response reading area" bind:this={area} onscroll={scroll} onwheel={event=>{if(event.deltaY<0)release();else if(event.deltaY)desired=null;}} ontouchstart={release} onpointerdown={event=>{if(event.target===area)release();}} onkeydown={event=>{if(!event.metaKey&&['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key))release();}}>
 <div bind:this={content}>{#key snapshot}<Response {...response} showBeacon={beacon} onbeacon={jumpAnswer}/>{/key}</div>
</div>
<style>.response-scroll{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;overflow-anchor:none;position:relative}.response-scroll:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}</style>
