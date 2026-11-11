<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceHeader from './WorkspaceHeader.svelte';
  import type { WorkspaceTrunkSelector } from '../types';
  let {
    workspace = 'Seqoya',
    current = 'Dashboard',
    destinations = [
      'Dashboard',
      'Intelligence Providers',
      'Brain Recipes',
      'Organizations',
      'Repos',
      'Quick Text',
      'Living Topics',
      'Blueprints',
      'Stewardship',
      'Artifacts',
      'Monitoring',
    ],
    children,
    headerTitle, headerTitleDetail, headerTitleEditor, headerBusy,
    headerContent, headerLead, headerExtras, headerWindowControls, trunk, trunkSelector, navigation, status,
    navigationFooter = true, fitted = false, elma = false,
    onnavigate = () => {},
  }: {
    workspace?: string;
    current?: string;
    destinations?: string[];
    children?: Snippet;
    headerTitle?: string;
    headerTitleDetail?: Snippet;
    headerTitleEditor?: Snippet;
    headerBusy?: boolean;
    headerContent?: Snippet;
    headerLead?: Snippet;
    headerExtras?: Snippet;
    headerWindowControls?: Snippet;
    trunk?: string;
    trunkSelector?: WorkspaceTrunkSelector;
    navigation?: Snippet; status?: Snippet | null; navigationFooter?: boolean; fitted?: boolean; elma?: boolean;
    onnavigate?: (page: string) => void;
  } = $props();
  let expanded = $state(false);
</script>

<div class="workspace" class:fitted class:elma>
  <WorkspaceHeader {workspace} title={headerTitle} titleDetail={headerTitleDetail} titleEditor={headerTitleEditor}
    busy={headerBusy} content={headerContent} lead={headerLead} extras={headerExtras}
    windowControls={headerWindowControls} {trunk} {trunkSelector} onToggleNavigation={() => (expanded = !expanded)} />
  <div class="layout" class:expanded>
    <nav aria-label={workspace + ' navigation'}>
      {#if navigation}{@render navigation()}{:else}
      <p class="eyebrow">Workspace</p>
      {#each destinations as destination}<button
          aria-current={current === destination ? 'page' : undefined}
          onclick={() => {
            onnavigate(destination);
            expanded = false;
          }}>{destination}</button
        >{/each}
      {#if navigationFooter}<div class="nav-foot">
        <span class="small muted">Connected knowledge.<br />Thoughtful work.</span>
      </div>{/if}
      {/if}
    </nav>
    <main>
      {#if children}{@render children()}{:else}<div class="page-content">
          <h1>{current}</h1>
          <p class="muted">
            The shared shell provides navigation, main content and persistent status.
          </p>
        </div>{/if}
    </main>
  </div>
  {#if status !== null}<footer>{#if status}{@render status()}{:else}<span>● Fixture mode</span><span>Local sample data · No native services</span>{/if}</footer>{/if}
</div>

<style>
  .fitted { height: 100dvh; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; border: 0; border-radius: 0; }
  .fitted .layout { min-height: 0; }
  .fitted main { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
  .fitted nav { min-height: 0; overflow: auto; }
  .elma nav { padding: 12px; }
  .elma footer { min-height: 40px; padding: 6px 12px; }
  .elma .layout { grid-template-columns: 248px minmax(0, 1fr); }
  @media (max-width: 800px) { .elma .layout { grid-template-columns: 1fr; } }

  .workspace {
    min-height: 720px;
    background: var(--canvas);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .layout {
    display: grid;
    grid-template-columns: 248px minmax(0, 1fr);
    min-height: 624px;
  }
  nav {
    padding: 24px 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--panel);
    border-right: 1px solid var(--border);
  }
  nav p {
    padding: 0 12px 12px;
  }
  nav button {
    color: var(--muted);
    background: none;
    border: 1px solid transparent;
    border-radius: 9px;
    text-align: left;
    padding: 8px 12px;
    min-height: 36px;
  }
  nav button[aria-current='page'] {
    background: var(--selected);
    border-color: var(--border);
    color: var(--text);
    font-weight: 600;
  }
  .nav-foot {
    margin-top: auto;
    padding: 32px 12px 0;
  }
  main {
    min-width: 0;
  }
  footer {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    min-height: 40px;
    padding: 10px 20px;
    border-top: 1px solid var(--border);
    font: 11px var(--font-mono);
    color: var(--muted);
  }
  @media (max-width: 1100px) {
    .layout {
      grid-template-columns: 208px minmax(0, 1fr);
    }
  }
  @media (max-width: 800px) {
    .layout {
      grid-template-columns: 1fr;
    }
    nav {
      display: none;
    }
    .expanded nav {
      display: flex;
    }
    .workspace {
      border-radius: 0;
    }
    .expanded main {
      display: none;
    }
  }
</style>
