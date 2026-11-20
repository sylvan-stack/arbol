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
    activityAt?: string;
    usage?: string;
  }

  const localTime = new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import Badge from '../components/Badge.svelte';
  import Button from '../components/Button.svelte';
  import TextField from '../components/TextField.svelte';
  let {
    title, status, drafted = false, unread = false, ongoing = false, inElma = false,
    density = 'full', condensed = false, failure, preview, detail, activityAt, usage, readOnly = false,
  }: StationData & { density?: string; condensed?: boolean; readOnly?: boolean } = $props();
  let name = $state(untrack(() => title));
  let draft = $state(untrack(() => title));
  let editing = $state(false);
  let feedback = $state('');
  const tone = $derived(
    status === 'Running' ? 'working'
      : status === 'Failed' ? 'failure'
      : status === 'Interrupted' ? 'warning'
      : status === 'Complete' ? 'success' : 'neutral',
  );
</script>

<article class="station" class:condensed class:compact={density === 'compact'}
  class:minimal={density === 'minimal'} class:running={status === 'Running'}
  class:has-draft={drafted || status === 'Draft'} class:unread class:in-elma={inElma}
  class:failed={status === 'Failed'}>
  <div class="card-heading">
    <h3>
      {#if readOnly || editing}{readOnly ? title : name}
      {:else}<button class="title" onclick={() => (feedback = 'Opened in the local preview')}>{name}</button>
      {/if}
    </h3>
    {#if status || drafted || unread || ongoing || inElma}
      <div class="states row">
        {#if status}<Badge label={status} {tone} />{/if}
        {#if drafted && status !== 'Draft'}<Badge label="Draft" />{/if}
        {#if unread}<Badge label="Unread" />{/if}
        {#if ongoing}<span class="small muted">Ongoing</span>{/if}
        {#if inElma}<span class="pill">Open in Elma</span>{/if}
      </div>
    {/if}
  </div>

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
    {#if failure}<p class="small error">{failure}</p>
    {:else if density === 'full' && preview}<p class="preview small muted">{preview}</p>{/if}
    {#if detail || activityAt}
      <div class="metadata small mono muted">
        {#if detail}<span>{detail}</span>{/if}
        {#if activityAt}<time datetime={activityAt}>{localTime.format(new Date(activityAt))}</time>{/if}
      </div>
    {/if}
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
</article>

<style>
  .station {
    --state-rail: transparent;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
    min-height: 142px;
    padding: 16px;
    border: 1px solid var(--border);
    border-inline-start: 4px solid var(--state-rail);
    border-radius: var(--radius-md);
    background: var(--panel);
    overflow-wrap: anywhere;
  }
  .station.has-draft { --state-rail: var(--muted); }
  .station.unread { --state-rail: var(--success); }
  .station.running {
    --state-rail: var(--accent);
    background: color-mix(in srgb, var(--accent) 6%, var(--panel));
  }
  .station.failed { --state-rail: var(--failure); }
  .station.in-elma {
    outline: 1px solid var(--accent);
    outline-offset: -1px;
    background: var(--selected);
  }
  .station.condensed {
    min-height: 100px;
    padding: 12px;
  }
  .station.compact {
    min-height: 0;
    gap: 6px;
    padding: 12px;
  }
  .station.minimal {
    min-height: 0;
    padding: 8px 12px;
  }
  .card-heading {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .compact .card-heading,
  .minimal .card-heading {
    flex-flow: row wrap;
    justify-content: space-between;
    align-items: baseline;
    column-gap: 12px;
  }
  h3 { line-height: 1.3; }
  .states { gap: 6px; }
  .metadata {
    display: flex;
    flex-wrap: wrap;
    column-gap: 12px;
  }
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
