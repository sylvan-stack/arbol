<script lang="ts">
  import TextArea from '../components/TextArea.svelte';
  import { tick } from 'svelte';
  import Button from '../components/Button.svelte';
  import EntityReference from '../patterns/EntityReference.svelte';
  import EntityPicker from '../patterns/EntityPicker.svelte';
  import Modal from '../patterns/Modal.svelte';
  import type { ElmaRoute } from './elma-types';
  let {
    onsend,
    oninput,
    onblur,
    onpaste,
    onTop,
    onBottom,
    value = $bindable(''),
    expanded = $bindable(false),
    repository = 'repository',
    route = {} as ElmaRoute,
    disabled = false,
    readOnly = false,
    busy = false,
    status = '',
    problem = '',
    context = '',
    conflict,
    onKeepMine,
    onTakeTheirs,
    recovery,
    onRestore,
    onDiscardRecovery,
    firstSapling = false,
    empty = false,
  }: {
    onsend?: (text: string) => void;
    oninput?: (text: string,edit?:{start:number;end:number}) => void;
    onblur?: () => void;
    onpaste?: (event: ClipboardEvent, selection: { start: number; end: number }) => void;
    onTop?: () => void;
    onBottom?: () => void;
    value?: string;
    expanded?: boolean;
    repository?: string;
    route?: ElmaRoute;
    disabled?: boolean;
    readOnly?: boolean;
    busy?: boolean;
    status?: string;
    problem?: string;
    context?: string;
    conflict?: {mine:string;theirs:string}|null;
    onKeepMine?:()=>void;
    onTakeTheirs?:()=>void;
    recovery?:string|null;
    onRestore?:()=>void;
    onDiscardRecovery?:()=>void;
    firstSapling?: boolean;
    empty?: boolean;
  } = $props();
  let attached = $state(false),
    picker = $state(false),
    feedback = $state(''),
    firstInput = $state<HTMLTextAreaElement>();
  let priorContext: string | undefined,
    priorText = false;
  let beforeEdit:{start:number;end:number;length:number}|undefined;
  $effect.pre(()=>{
    const next=value,input=firstInput;
    if(!firstSapling||!input||input.value===next||document.activeElement!==input)return;
    const previous=input.value;let start=0,tail=0;
    while(start<previous.length&&start<next.length&&previous[start]===next[start])start++;
    while(tail<previous.length-start&&tail<next.length-start&&previous[previous.length-1-tail]===next[next.length-1-tail])tail++;
    const oldEnd=previous.length-tail,newEnd=next.length-tail;
    const move=(position:number)=>position<start?position:position>=oldEnd?position+next.length-previous.length:newEnd;
    const a=move(input.selectionStart),b=move(input.selectionEnd);
    void tick().then(()=>{if(input===firstInput&&input.value===next&&document.activeElement===input)input.setSelectionRange(a,b);});
  });
  $effect(() => {
    if (!firstSapling) return;
    if(busy){expanded=false;return;}
    const hasText = value.length > 0;
    if (context !== priorContext) {
      priorContext = context;
      expanded = empty || hasText;
    } else if (hasText && !priorText) expanded = true;
    priorText = hasText;
  });
  $effect(() => {
    if (firstSapling && (empty || expanded) && !readOnly && !disabled && !busy)
      void tick().then(() => {
        if (!document.querySelector('dialog[open]')) firstInput?.focus();
      });
  });
  function firstKeys(event: KeyboardEvent) {
    if (!firstSapling || empty || busy || disabled || event.defaultPrevented || document.querySelector('dialog[open]'))
      return;
    if (
      event.key === 'Enter' &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey &&
      !expanded &&
      !(
        event.target instanceof Element &&
        event.target.closest('button,a,input,textarea,select,[contenteditable=true]')
      )
    ) {
      event.preventDefault();
      expanded = true;
    }
  }
  function send() {
    if (!value.trim() || disabled || readOnly || busy) return;
    if (firstSapling) {
      if (onsend) {
        onsend(value);
      }
      return;
    }
    onsend?.(value);
    value = '';
    feedback = 'Message sent locally';
  }
  function handleKeys(event: KeyboardEvent) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.altKey) {
      event.preventDefault();
      send();
    } else if (
      firstSapling &&
      event.key === 'Escape' &&
      !event.metaKey &&
      !event.ctrlKey &&
      !empty
    ) {
      event.preventDefault();
      expanded = false;
      onblur?.();
    }
  }
</script>

<svelte:window onkeydown={firstKeys} />
{#if firstSapling}
  <section class="first-composer" class:empty aria-label="Message composer">
    {#if empty}<p class="context-line">
        {repository} · {route.driver ?? '—'} · {route.subscription ?? '—'} · model: {route.model ??
          '—'} · thinking: {route.effort ?? '—'}
      </p>{/if}
    {#if empty || expanded&&!busy}<textarea
        bind:this={firstInput}
        aria-label="Message"
        placeholder={'Message ' + repository + '…'}
        rows={empty ? 10 : 3}
        bind:value
        {disabled}
        readonly={readOnly || busy}
        onbeforeinput={event=>beforeEdit={start:event.currentTarget.selectionStart,end:event.currentTarget.selectionEnd,length:event.currentTarget.value.length}}
        oninput={(event) => {
          value = event.currentTarget.value;
          const edit=beforeEdit;beforeEdit=undefined;
          if(edit&&edit.start===edit.end&&value.length<edit.length){if(event instanceof InputEvent&&event.inputType.includes('Backward'))edit.start+=value.length-edit.length;else edit.end+=edit.length-value.length;}
          oninput?.(value,edit);
        }}
        onblur={() => onblur?.()}
        onpaste={(event) =>
          onpaste?.(event, {
            start: event.currentTarget.selectionStart,
            end: event.currentTarget.selectionEnd,
          })}
        onkeydown={handleKeys}></textarea><small class="muted"
        >{status || (onsend ? '⌘⏎ to Send' : '')}{!empty && !busy
          ? ' · Esc to collapse'
          : ''}</small
      >
    {:else}<div class="closed">
        <button class="start-message" disabled={busy} onclick={() => (expanded = true)}
          >Press Enter to start new message ⏎</button
        ><button
          class="scroll"
          aria-label="Scroll to top"
          title="Scroll to top"
          disabled={!onTop}
          onclick={onTop}>↑</button
        ><button
          class="scroll"
          aria-label="Scroll to bottom"
          title="Scroll to bottom"
          disabled={!onBottom}
          onclick={onBottom}>↓</button
        >
      </div>{/if}
    {#if !empty && !expanded && status}<small class="muted" role="status">{status}</small>{/if}
    {#if problem}<p class="problem" role="alert">{problem}</p>{/if}
    {#if conflict}<section class="conflict" aria-label="Changed elsewhere"><strong>Changed elsewhere</strong><div class="versions"><div><b>Your text</b><pre>{conflict.mine||'(empty)'}</pre></div><div><b>Other text</b><pre>{conflict.theirs||'(removed)'}</pre></div></div><div class="choices"><button onclick={onKeepMine} disabled={!onKeepMine}>Keep mine</button><button onclick={onTakeTheirs} disabled={!onTakeTheirs}>Take theirs</button></div></section>{/if}
    {#if recovery!==undefined&&recovery!==null}<section class="conflict" aria-label="Unsaved text from this window"><strong>Unsaved text from this window</strong><p>The Draft still has the revision this text was typed over.</p><pre>{recovery||'(empty)'}</pre><div class="choices"><button onclick={onRestore} disabled={!onRestore}>Restore text</button><button onclick={onDiscardRecovery} disabled={!onDiscardRecovery}>Discard</button></div></section>{/if}
  </section>
{:else}
  <section class="panel stack" aria-label="Message composer">
    <TextArea
      onkeydown={handleKeys}
      label="Message"
      bind:value
      rows={3}
      placeholder="Write a follow-up or add context…"
    />{#if attached}<div class="row">
        <EntityReference title="Design System" /><Button
          label="Remove context"
          tone="ghost"
          onclick={() => (attached = false)}
        />
      </div>{/if}
    <div class="row spread">
      <div class="row">
        <Button label="Add context" onclick={() => (picker = true)} /><small class="muted"
          >⌘/Ctrl + Enter to send</small
        >
      </div>
      <Button label="Send" tone="primary" disabled={disabled || !value.trim()} onclick={send} />
    </div>
    <small role="status" class="muted"
      >{feedback || 'Local preview draft · Preserved while this composer remains mounted'}</small
    >
  </section>
  {#if picker}<Modal title="Add context" onclose={() => (picker = false)}
      ><EntityPicker
        onselect={() => {
          attached = true;
          picker = false;
        }}
      /></Modal
    >{/if}
{/if}

<style>
  .first-composer {
    padding: 12px 24px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    flex-shrink: 0;
    width: 100%;
    max-width: var(--elma-reading-width, 720px);
    margin: 0 auto;
  }
  .first-composer.empty {
    flex: 1;
    min-height: 0;
    justify-content: safe center;
    overflow-y: auto;
  }
  .context-line {
    margin: 0 0 6px;
    color: var(--muted);
    font-size: 0.9em;
    overflow-wrap: anywhere;
  }
  .first-composer textarea {
    flex-shrink: 0;
    width: 100%;
    min-width: 0;
    resize: vertical;
    background: var(--inset);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 12px;
    font: inherit;
    line-height: 1.5;
  }
  .first-composer textarea:read-only {
    opacity: 0.8;
  }
  .first-composer textarea:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }
  .closed {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .start-message {
    flex: 1;
    background: none;
    border: 0;
    padding: 4px;
    color: var(--muted);
    font: inherit;
    text-align: left;
    min-width: 0;
  }
  .scroll {
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--panel);
    color: var(--text);
    font: inherit;
    min-width: 30px;
    min-height: 30px;
  }
  .problem {
    margin: 0;
    color: var(--failure);
    font-size: 0.9em;
    overflow-wrap: anywhere;
  }
  .conflict{border:1px solid var(--warning);padding:12px;border-radius:4px;max-height:40vh;overflow:auto}.versions{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:8px 0}.versions>div{min-width:0}.conflict pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:4px 0}.choices{display:flex;gap:8px}.choices button{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:6px 10px}.choices button:focus-visible{outline:2px solid var(--focus)}
  @media (max-width: 600px) {
    .versions{grid-template-columns:1fr}
    .first-composer {
      padding: 12px;
    }
  }
</style>
