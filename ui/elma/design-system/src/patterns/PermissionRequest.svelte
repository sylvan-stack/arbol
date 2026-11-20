<script lang="ts">
  import Button from '../components/Button.svelte';
  import Badge from '../components/Badge.svelte';
  let {
    tool = 'Read repository files',
    scope = 'sylvan-stack/arbol-design-system · src/**',
    session = 'Restore the design language',
    ondecision = () => {},
  }: {
    tool?: string;
    scope?: string;
    session?: string;
    ondecision?: (value: string) => void;
  } = $props();
  let decision = $state('');
  function decide(value: string) {
    decision = value;
    ondecision(value);
  }
</script>

<section class="panel stack" aria-label="Permission request">
  <div class="row spread">
    <h2>Permission needed</h2>
    <Badge label={decision || 'Waiting for you'} tone={decision ? 'success' : 'warning'} />
  </div>
  <p class="small muted">{session}</p>
  <strong>{tool}</strong>
  <p class="mono">{scope}</p>
  <details>
    <summary>Technical details</summary>
    <pre class="code">tool: read_files
scope: {scope}
source: active chat</pre>
  </details>
  {#if !decision}<div class="row">
      <Button label="Allow once" tone="primary" onclick={() => decide('Allowed once')} /><Button
        label="Always allow this scope"
        onclick={() => decide('Scope allowed')}
      /><Button label="Reject" onclick={() => decide('Rejected')} /><Button
        label="Stop run"
        tone="ghost"
        onclick={() => decide('Run stopped')}
      />
    </div>{:else}<p role="status">{decision}. This fixture updates locally.</p>{/if}
</section>
