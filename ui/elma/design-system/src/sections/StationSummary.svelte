<script module lang="ts">
  export interface StationData {
    title: string;
    status?: string;
    drafted?: boolean;
    unread?: boolean;
    ongoing?: boolean;
    inElma?: boolean;
    failure?: string;
    preview?: string;
    detail?: string;
    harness?: string;
    activityAt?: string;
    usage?: string;
  }

  const localTime = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });

  const age = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto', style: 'narrow' });

  function activityAge(activityAt: string, now: number): string {
    const minutes = Math.max(0, Math.floor((now - Date.parse(activityAt)) / 60_000));
    if (minutes < 1) return age.format(0, 'second');
    if (minutes < 60) return age.format(-minutes, 'minute');
    if (minutes < 1440) return age.format(-Math.floor(minutes / 60), 'hour');
    return age.format(-Math.floor(minutes / 1440), 'day');
  }
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import Button from '../components/Button.svelte';
  import TextField from '../components/TextField.svelte';
  let {
    title, status, drafted = false, unread = false, ongoing = false, inElma = false,
    density = 'full', condensed = false, failure, preview, detail, harness, activityAt, usage,
    readOnly = false, now = Date.now(), onOpen,
  }: StationData & {
    density?: string;
    condensed?: boolean;
    readOnly?: boolean;
    now?: number;
    onOpen?: () => void;
  } = $props();
  let name = $state(untrack(() => title));
  let draft = $state(untrack(() => title));
  let editing = $state(false);
  let feedback = $state('');
  const stateLabel = $derived(
    status === 'Running' ? 'Responding'
      : status === 'Failed' ? 'Error'
      : drafted || status === 'Draft' ? 'Draft ready'
      : unread ? 'New response'
      : status && (status !== 'Complete' || harness) ? status : harness ? 'Imported' : 'Idle',
  );
  const metadata = $derived([harness, detail].filter(Boolean).join(' · '));
</script>

<article class="station" class:condensed class:compact={density === 'compact'}
  class:minimal={density === 'minimal'} class:running={status === 'Running'}
  class:has-draft={drafted || status === 'Draft'} class:unread class:in-elma={inElma}
  class:failed={status === 'Failed'} class:interrupted={status === 'Interrupted'}>
  <div class="card-topline">
    <span class="state">
      <span class="state-dot" aria-hidden="true"></span>{stateLabel}
    </span>
    {#if ongoing}<span class="cue" title="Ongoing"><span aria-hidden="true">★</span><span class="sr-only">Ongoing</span></span>{/if}
    {#if drafted && stateLabel !== 'Draft ready'}
      <span class="cue" title="Draft ready"><span aria-hidden="true">✎</span><span class="sr-only">Draft ready</span></span>
    {/if}
    {#if unread && stateLabel !== 'New response'}<span class="cue">Unread</span>{/if}
    {#if inElma}<span class="cue">In Elma</span>{/if}
    {#if activityAt && density !== 'minimal' && Number.isFinite(Date.parse(activityAt))}
      <time datetime={activityAt} title={localTime.format(new Date(activityAt))}>{activityAge(activityAt, now)}</time>
    {/if}
  </div>

  <h3 class="card-title" title={readOnly ? title : name}>
    {#if readOnly || editing}{readOnly ? title : name}
    {:else}<button class="title" onclick={() => (feedback = 'Opened in the local preview')}>{name}</button>
    {/if}
  </h3>

  {#if !readOnly && editing}
    <TextField label="Chat Session title" bind:value={draft} />
    <div class="row">
      <Button
        label="Save title"
        disabled={!draft.trim()}
        onclick={() => {
          name = draft;
          editing = false;
        }}
      />
      <Button label="Cancel" onclick={() => (editing = false)} />
    </div>
  {/if}

  {#if density !== 'minimal'}
    {#if metadata}<p class="metadata mono muted" title={metadata}>{metadata}</p>{/if}
    {#if failure}<p class="small error">{failure}</p>
    {:else if density === 'full' && preview}<p class="preview small muted">{preview}</p>{/if}
  {/if}

  {#if density === 'full' && (usage || !readOnly)}
    <div class="card-footer row spread">
      {#if usage}<span class="small muted">{usage}</span>{/if}
      {#if !readOnly}
        <div class="row">
          <Button
            label={failure ? 'Retry' : 'Open chat'}
            onclick={() =>
              (feedback = failure ? 'Retry queued locally' : 'Opened in the local preview')}
          />
          <Button label="Rename" tone="ghost" onclick={() => (editing = true)} />
        </div>
      {/if}
    </div>
  {/if}
  {#if feedback}<small role="status">{feedback}</small>{/if}
  {#if readOnly && onOpen}
    <button type="button" class="open-chat" aria-label={`Open ${title} in Elma Chat`} onclick={onOpen}></button>
  {/if}
</article>

<style>
  .station {
    --state-rail: transparent;
    --state-color: var(--muted);
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
    min-height: 142px;
    padding: 16px 16px 16px 18px;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--panel);
    box-shadow: var(--arbol-shadow-1);
    overflow-wrap: anywhere;
  }
  .station::before {
    content: '';
    position: absolute;
    inset: 0 auto 0 0;
    width: 4px;
    background: var(--state-rail);
    pointer-events: none;
  }
  .open-chat {
    position: absolute;
    inset: 0;
    cursor: pointer;
    background: transparent;
    border: 0;
    border-radius: inherit;
  }
  .open-chat:hover { box-shadow: inset 0 0 0 1px var(--accent); }
  .open-chat:focus-visible { outline-offset: -3px; }
  .station.has-draft { --state-rail: var(--muted); }
  .station.unread { --state-rail: var(--success); --state-color: var(--success); }
  .station.running {
    --state-rail: transparent;
    --state-color: var(--link);
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
    background: color-mix(in srgb, var(--accent) 6%, var(--panel));
  }
  .station.interrupted { --state-color: var(--warning); }
  .station.failed { --state-rail: var(--failure); --state-color: var(--failure); }
  .station.in-elma {
    outline: 1px solid var(--accent);
    outline-offset: -1px;
    background: var(--selected);
  }
  .station.condensed {
    min-height: 100px;
    gap: 7px;
    padding: 11px 11px 11px 13px;
    border-radius: var(--radius-md);
  }
  .station.condensed::before { width: 3px; }
  .station.compact {
    min-height: 0;
    gap: 6px;
    padding: 12px;
  }
  .station.minimal {
    min-height: 0;
    padding: 8px 12px;
  }
  .card-topline {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px 7px;
    font: 600 calc(10px * var(--font-scale))/1.25 var(--font-mono);
  }
  .state {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: var(--state-color);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .state-dot {
    width: 6px;
    height: 6px;
    flex-shrink: 0;
    border-radius: 50%;
    background: currentColor;
  }
  .cue { color: var(--link); }
  time { margin-inline-start: auto; color: var(--muted); white-space: nowrap; }
  .card-title {
    color: var(--text);
    font-size: calc(16px * var(--font-scale));
    font-weight: 650;
    line-height: 1.3;
  }
  .station.condensed .card-title { font-size: calc(13px * var(--font-scale)); }
  .station.unread .card-title { font-weight: 750; }
  .metadata {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .station.condensed .metadata { font-size: calc(11px * var(--font-scale)); }
  .card-title,
  .preview {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }
  .card-footer {
    margin-top: auto;
    padding-top: 8px;
    border-top: 1px solid var(--border);
  }
  .title {
    font: inherit;
    background: none;
    border: 0;
    padding: 0;
    color: var(--text);
    text-align: left;
    min-height: 24px;
  }
</style>
