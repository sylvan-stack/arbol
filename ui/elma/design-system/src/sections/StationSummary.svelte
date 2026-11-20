<script module lang="ts">
  export interface StationData {
    title: string;
    status?: string;
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
    title, status, unread = false, ongoing = false, inElma = false,
    density = 'full', failure, preview, detail, activityAt, usage, readOnly = false,
  }: StationData & { density?: string; readOnly?: boolean } = $props();
  let name = $state(untrack(() => title));
  let draft = $state(untrack(() => title));
  let editing = $state(false);
  let feedback = $state('');
</script>

<article class="station" class:compact={density !== 'full'}>
  <div class="stack" style="gap:10px">
    {#if status || unread || ongoing || inElma}
      <div class="row">
        {#if status}
          <Badge
            label={status}
            tone={status === 'Running' ? 'working'
              : status === 'Failed' ? 'failure'
              : status === 'Complete' ? 'success' : 'neutral'}
          />
        {/if}
        {#if unread}<Badge label="Unread" />{/if}
        {#if ongoing}<span class="small muted">Ongoing</span>{/if}
        {#if inElma}<span class="pill">Open in Elma</span>{/if}
      </div>
    {/if}

    {#if readOnly}
      <h3 class="title">{title}</h3>
    {:else if editing}
      <TextField label="Chat title" bind:value={draft} />
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
    {:else}
      <button class="title" onclick={() => (feedback = 'Opened in the local preview')}>{name}</button>
    {/if}

    {#if density !== 'minimal'}
      {#if failure || preview}<p class="small muted">{failure || preview}</p>{/if}
      {#if detail || activityAt}
        <span class="small mono muted">
          {detail ?? ''}{#if detail && activityAt}{' · '}{/if}
          {#if activityAt}<time datetime={activityAt}>{localTime.format(new Date(activityAt))}</time>{/if}
        </span>
      {/if}
    {/if}

    {#if density === 'full' && !readOnly}
      <hr class="rule" />
      <div class="row spread">
        {#if usage}<span class="small muted">{usage}</span>{/if}
        <div class="row">
          <Button
            label={failure ? 'Retry' : 'Open chat'}
            onclick={() =>
              (feedback = failure ? 'Retry queued locally' : 'Opened in the local preview')}
          />
          <Button label="Rename" tone="ghost" onclick={() => (editing = true)} />
        </div>
      </div>
    {/if}
    {#if feedback}<small role="status">{feedback}</small>{/if}
  </div>
</article>

<style>
  .station {
    padding: 20px;
    border: 1px solid var(--border);
    border-top: 2px solid var(--accent);
    border-radius: 12px;
    background: linear-gradient(130deg, var(--selected), transparent 55%), var(--panel);
    overflow-wrap: anywhere;
  }
  .station.compact {
    padding: 12px;
  }
  .title {
    font-weight: 600;
    font-size: 16px;
    background: none;
    border: 0;
    padding: 0;
    color: var(--text);
    text-align: left;
    min-height: 32px;
  }
</style>
