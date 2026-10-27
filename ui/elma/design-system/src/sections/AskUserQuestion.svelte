<script lang="ts">
 import Button from '../components/Button.svelte';
 import TextArea from '../components/TextArea.svelte';
 import {interactiveQuestions,pretty,answerLabels,type QuestionView,type Answer} from './elma-response';
 let {firstSapling=false,question,onanswer}:{firstSapling?:boolean;question?:QuestionView;onanswer?:(answer:Answer)=>void}=$props();
 let choices=$state<Record<string,string[]>>({});
 const items=$derived(interactiveQuestions(question?.ask));
 const retry=$derived(!!question?.problem);
 const editable=$derived(!!onanswer&&!!question?.open&&(!question.answer||retry)&&!question.pending);
 function selected(id:string){return Object.hasOwn(choices,id)?choices[id]:[];}
 const complete=$derived(!!items&&items.every(item=>!item.options.length||selected(item.id).some(label=>item.options.some(option=>option.label===label))));
 const hasOptions=$derived(!!items?.some(item=>item.options.length));
 function choose(id:string,label:string,multiple:boolean,checked:boolean){const current=selected(id);choices={...choices,[id]:multiple?checked?[...current.filter(value=>value!==label),label]:current.filter(value=>value!==label):[label]};}
 function submit(){if(!items||!editable||!complete)return;onanswer?.({type:'answers',answers:Object.fromEntries(items.map(item=>[item.id,selected(item.id).filter(label=>item.options.some(option=>option.label===label))]))});}
 let answer=$state('Comfortable'),other=$state(''),submitted=$state(false);
</script>
{#if firstSapling&&question}
<section class="agent-question" aria-label="Agent question">
 <h3>{question.open?'Question from the agent':'Question closed'}</h3>
 {#if items}{#each items as item (item.id)}
  {#if editable||question.pending}<fieldset disabled={!editable}><legend>{item.header||item.question}</legend>{#if item.header}<p>{item.question}</p>{/if}{#if item.multiple&&item.options.length}<small>You can pick more than one</small>{/if}{#each item.options as option}<label class="option"><input type={item.multiple?'checkbox':'radio'} name={question.id+':'+item.id} checked={selected(item.id).includes(option.label)} onchange={event=>choose(item.id,option.label,item.multiple,event.currentTarget.checked)}/><span>{option.label}{option.description?' · '+option.description:''}</span></label>{/each}</fieldset>
  {:else}<p>{item.header?item.header+': ':''}{item.question}</p><ul>{#each item.options as option}<li>{option.label}{option.description?' · '+option.description:''}</li>{/each}</ul>{/if}
 {/each}{:else}<p>This Build does not recognize this question format. Its data is kept below.</p><pre>{pretty(question.ask)}</pre>{/if}
 {#if question.answer!==undefined}<h4>Your answer</h4><p>{answerLabels(question.answer)}</p>{/if}
 {#if question.pending}<p role="status">Answer sent; waiting for the agent’s recorded answer…</p>{/if}
 {#if question.problem}<p class="problem" role="alert">{question.problem}</p>{/if}
 {#if onanswer&&question.open&&(!question.answer||retry||question.pending)}<div class="actions">{#if items}<Button label={hasOptions?'Submit':'Continue'} tone="primary" disabled={!editable||!complete} onclick={submit}/>{/if}<Button label="Cancel" disabled={question.pending} onclick={()=>onanswer?.({type:'decline'})}/></div>{/if}
</section>
{:else}
<section class="panel stack" aria-label="Question">
  <h2>Which density should this workspace use?</h2>
  <p class="muted">You can change this later in preferences.</p>
  {#each ['Comfortable', 'Compact', 'Custom'] as option}<label class="row"
      ><input
        type="radio"
        name="density-answer"
        value={option}
        bind:group={answer}
        disabled={submitted}
      />{option}</label
    >{/each}{#if answer === 'Custom'}<TextArea label="Your preference" bind:value={other} />{/if}
  <div>
    <Button
      label={submitted ? 'Answer submitted' : 'Submit answer'}
      tone="primary"
      disabled={submitted || (answer === 'Custom' && !other.trim())}
      onclick={() => (submitted = true)}
    />
  </div>
  {#if submitted}<p role="status">{answer === 'Custom' ? other : answer}</p>{/if}
</section>

{/if}
<style>.agent-question{padding:12px;margin:16px 0;border:1px solid var(--border);border-radius:6px;background:var(--panel);min-width:0;overflow-wrap:anywhere}.agent-question h3,.agent-question h4{margin:0 0 8px;font-size:1em}.agent-question p{white-space:pre-wrap;margin:6px 0}.agent-question pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.agent-question fieldset{border:0;padding:0;margin:10px 0;min-width:0}.agent-question legend{font-weight:600}.option{display:flex;gap:8px;align-items:baseline;padding:5px 0}.option span{min-width:0}.option input{flex-shrink:0}.actions{display:flex;gap:8px;margin-top:12px}.problem{color:var(--failure)}</style>
