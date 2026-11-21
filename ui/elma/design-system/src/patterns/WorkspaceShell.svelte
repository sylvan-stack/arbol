<script lang="ts">
  import type { Snippet } from 'svelte';
  import WorkspaceGlyph from '../components/WorkspaceGlyph.svelte';
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
      'Artifacts',
      'Monitoring',
    ],
    children,
    disabledDestinations = [],
    headerTitle, headerTitleDetail, headerTitleEditor, headerBusy,
    headerContent, headerLead, headerExtras, headerWindowControls, trunk, trunkSelector, navigation, status,
    headerAppearance, onAppearanceChange, insignia,
    theme = $bindable(''), uiScale = $bindable(0), contentScale = $bindable<number>(),
    navigationFooter = true, showNavigation = true, fitted = false, elma = false,
    onnavigate = () => {},
  }: {
    workspace?: string;
    current?: string;
    destinations?: string[];
    disabledDestinations?: string[];
    children?: Snippet;
    headerTitle?: string;
    headerTitleDetail?: Snippet;
    headerTitleEditor?: Snippet;
    headerBusy?: boolean;
    headerContent?: Snippet;
    headerLead?: Snippet;
    headerExtras?: Snippet;
    headerWindowControls?: Snippet;
    headerAppearance?: 'enabled' | 'disabled';
    insignia?: { label: string; hue?: number; compact?: boolean };
    theme?: string;
    uiScale?: number;
    contentScale?: number;
    onAppearanceChange?: () => void;
    trunk?: string;
    trunkSelector?: WorkspaceTrunkSelector;
    navigation?: Snippet; status?: Snippet | null; navigationFooter?: boolean; showNavigation?: boolean; fitted?: boolean; elma?: boolean;
    onnavigate?: (page: string) => void;
  } = $props();
  let expanded = $state(false);
</script>

<div class="workspace" class:fitted class:elma class:single-pane={!showNavigation} class:appearance={!!headerAppearance}
  data-theme={theme || undefined} style:--font-scale={uiScale || undefined}>
  <WorkspaceHeader {workspace} title={headerTitle} titleDetail={headerTitleDetail} titleEditor={headerTitleEditor}
    busy={headerBusy} content={headerContent} lead={headerLead} extras={headerExtras}
    windowControls={headerWindowControls} {trunk} {trunkSelector} onToggleNavigation={showNavigation ? () => (expanded = !expanded) : undefined}
    appearance={headerAppearance} bind:theme bind:uiScale bind:contentScale {onAppearanceChange} />
  <div class="layout" class:expanded>
    {#if showNavigation}<nav aria-label={workspace + ' navigation'}>
      {#if navigation}{@render navigation()}{:else}
      {#if insignia}
        <div class="insignia" class:compact-insignia={insignia.compact}
          style:--insignia-hue={(insignia.hue ?? 0) + 'deg'}>
          <span class="insignia-watermark" aria-hidden="true">
            <WorkspaceGlyph {workspace} size={132} />
          </span>
          <span class="insignia-workspace">
            <span aria-hidden="true"><WorkspaceGlyph {workspace} size={16} /></span>
            {workspace}
          </span>
          <span class="insignia-title">{insignia.label}</span>
        </div>
      {:else}
        <p class="eyebrow">Workspace</p>
      {/if}
      {#each destinations as destination}<button
          aria-current={current === destination ? 'page' : undefined}
          disabled={disabledDestinations.includes(destination)}
          onclick={() => {
            onnavigate(destination);
            expanded = false;
          }}>{destination}</button
        >{/each}
      {#if navigationFooter}<div class="nav-foot">
        <span class="small muted">Connected knowledge.<br />Thoughtful work.</span>
      </div>{/if}
      {/if}
    </nav>{/if}
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
  .appearance { color: var(--text); font: calc(13.5px * var(--font-scale))/1.5 var(--font-ui); }
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
  .single-pane.fitted { min-height: 0; }
  .single-pane .layout { grid-template-columns: minmax(0, 1fr); }
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
  .insignia {
    position: relative;
    isolation: isolate;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    gap: 4px;
    flex-shrink: 0;
    min-height: 104px;
    margin-bottom: 12px;
    padding: var(--space-4);
    border-radius: var(--radius-lg);
    color: var(--arbol-brief-pane-fg);
    box-shadow: var(--arbol-shadow-1);
  }
  .insignia::before {
    content: '';
    position: absolute;
    inset: 0;
    z-index: -2;
    background: var(--arbol-brief-pane-bg-silver);
    filter: hue-rotate(var(--insignia-hue));
  }
  .insignia-watermark {
    position: absolute;
    z-index: -1;
    top: -22px;
    right: -20px;
    opacity: 0.46;
    color: var(--arbol-brief-ring);
    pointer-events: none;
  }
  .insignia-workspace {
    display: flex;
    align-items: center;
    gap: 8px;
    font: 600 calc(12px * var(--font-scale))/1 var(--font-mono);
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  .insignia-workspace > span { display: flex; }
  .insignia-title {
    font-size: calc(22px * var(--font-scale));
    font-weight: 700;
    line-height: 1.15;
    overflow-wrap: anywhere;
  }
  .compact-insignia { gap: 7px; }
  .compact-insignia .insignia-title {
    font: 600 calc(16px * var(--font-scale))/1.2 ui-serif, Georgia, serif;
    text-wrap: balance;
  }
  .compact-insignia .insignia-workspace::after {
    content: '';
    inline-size: 22px;
    block-size: 1px;
    background: currentColor;
    opacity: 0.38;
  }
  .compact-insignia .insignia-watermark { opacity: 0.28; }
  nav button {
    color: var(--muted);
    background: none;
    border: 1px solid transparent;
    border-radius: 9px;
    text-align: left;
    padding: 8px 12px;
    min-height: 36px;
  }
  nav button:disabled {
    color: var(--disabled);
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
