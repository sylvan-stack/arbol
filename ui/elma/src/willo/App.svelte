<script lang="ts">
  import { onMount } from 'svelte';
  import WilloStation, { type ChatSessionRow, type WilloTab } from '../../design-system/src/pages/WilloStation.svelte';
  import { Bridge } from '../bridge';

  type Cursor = { activityAt: string; chat: string };
  interface Summary extends Cursor {
    title: string | null;
    firstMessage?: string;
    ongoing?: boolean;
    hasDraft?: boolean;
    last?: { state?: string; error?: { message?: string } };
    workingFolder?: string;
    route?: { driver?: string; model?: string };
    imported?: { tool: string };
  }

  interface Page {
    rows: ChatSessionRow[];
    cursor?: Cursor;
    more: boolean;
    loading: boolean;
    problem: string;
    retryOlder: boolean;
  }

  const liveTab = 'Live Stations';
  const importedTab = 'Imported Chat Sessions';
  const pageSize = 50;
  const scanSize = 100;
  const stationStatuses = new Map([
    ['accepting', 'Running'], ['running', 'Running'], ['stopping', 'Running'], ['ending', 'Running'],
    ['completed', 'Complete'], ['failed', 'Failed'], ['cancelled', 'Cancelled'], ['interrupted', 'Interrupted'],
  ]);
  const harnessLabels = new Map([
    ['claude-code', 'Claude Code'], ['codex', 'Codex'], ['kimi-code', 'Kimi Code'],
    ['pi', 'Pi'], ['mimo', 'MiMo'],
  ]);

  function emptyPage(): Page {
    return { rows: [], more: false, loading: true, problem: '', retryOlder: false };
  }

  const pages = $state<Record<WilloTab, Page>>({ [liveTab]: emptyPage(), [importedTab]: emptyPage() });
  const live = pages[liveTab];
  const imported = pages[importedTab];
  let active: WilloTab = liveTab;
  let generation = 0;
  let greeted = false;
  let connectionProblem = '';
  let read: ((tab: WilloTab, older: boolean) => Promise<void>) | undefined;

  function cursorOf(row: Cursor): Cursor {
    return { activityAt: row.activityAt, chat: row.chat };
  }

  function compareNewest(left: Cursor, right: Cursor): number {
    const sameTime = left.activityAt === right.activityAt;
    const leftKey = sameTime ? left.chat : left.activityAt;
    const rightKey = sameTime ? right.chat : right.activityAt;
    return leftKey < rightKey ? 1 : leftKey > rightKey ? -1 : 0;
  }

  async function scan(bridge: Bridge, archived: boolean, before?: Cursor): Promise<Summary[]> {
    const reply = await bridge.call<{ chats: Summary[] }>('chats.page', {
      limit: scanSize + 1, ...(archived && { archived }), ...(before && { before }),
    });
    if (!Array.isArray(reply?.chats) || reply.chats.some(row =>
      typeof row?.chat !== 'string' || !row.chat ||
      typeof row.activityAt !== 'string' || !Number.isFinite(Date.parse(row.activityAt)) ||
      (row.title !== null && typeof row.title !== 'string') ||
      (row.firstMessage !== undefined && typeof row.firstMessage !== 'string') ||
      (row.imported !== undefined && (typeof row.imported?.tool !== 'string' || !row.imported.tool)) ||
      (before && compareNewest(row, before) <= 0)
    )) throw new Error('Arbol returned an invalid Chat Session list.');
    return reply.chats;
  }

  function toRow(summary: Summary): ChatSessionRow {
    const firstLine = summary.firstMessage?.trim().split('\n', 1)[0].trim() ?? '';
    const title = summary.title?.trim() || Array.from(firstLine).slice(0, 80).join('') || 'Untitled Chat Session';
    const status = stationStatuses.get(summary.last?.state ?? '');
    const tool = summary.imported?.tool;
    const folder = typeof summary.workingFolder === 'string'
      ? summary.workingFolder.split('/').filter(Boolean).at(-1)
      : undefined;
    const detail = [folder, tool ? undefined : summary.route?.driver, summary.route?.model]
      .filter(value => typeof value === 'string' && value).join(' · ');
    const error = summary.last?.error?.message;
    const drafted = !tool && summary.hasDraft === true;
    return {
      id: summary.chat,
      title,
      activityAt: summary.activityAt,
      status: status ?? (drafted && !summary.last ? 'Draft' : undefined),
      ongoing: !tool && summary.ongoing === true,
      drafted,
      failure: status === 'Failed' && typeof error === 'string' ? error : undefined,
      harness: tool ? harnessLabels.get(tool) ?? tool : undefined,
      detail,
    };
  }

  function select(tab: WilloTab) {
    generation++;
    pages[active].loading = false;
    active = tab;
    if (greeted) void read?.(tab, false);
    else {
      pages[tab].loading = !connectionProblem;
      pages[tab].problem = connectionProblem;
    }
  }

  onMount(() => {
    const bridge = new Bridge({
      onhello: () => {
        greeted = true;
        connectionProblem = '';
        void read?.(active, false);
      },
      onstate: (state) => {
        if (state === 'Reconnecting…') {
          generation++;
          greeted = false;
          connectionProblem = '';
          pages[active].loading = true;
          pages[active].problem = '';
        } else if (!greeted && state !== 'Connected') {
          connectionProblem = state;
          pages[active].problem = state;
          pages[active].loading = false;
        }
      },
    });

    read = async (tab, older) => {
      const page = pages[tab];
      if (tab !== active || (older && (!page.cursor || !page.more || page.loading))) return;
      const request = ++generation;
      const wantImports = tab === importedTab;
      page.retryOlder = older;
      page.loading = true;
      page.problem = '';
      try {
        const matches: Summary[] = [];
        let before = older ? page.cursor : undefined;
        while (matches.length <= pageSize) {
          const sources = await Promise.all(wantImports
            ? [scan(bridge, false, before), scan(bridge, true, before)]
            : [scan(bridge, false, before)]);
          if (request !== generation) return;

          // Both sources are bounded by the same cursor. Only consume the
          // merged prefix that every source has fetched far enough to cover.
          const unique = new Map(sources.flat().map(row => [row.chat, row]));
          const batch = [...unique.values()].sort(compareNewest);
          const prefix = batch.slice(0, scanSize);
          matches.push(...prefix.filter(row => Boolean(row.imported) === wantImports));
          if (batch.length <= scanSize) break;
          before = cursorOf(prefix[scanSize - 1]);
        }

        const visible = matches.slice(0, pageSize);
        const last = visible.at(-1);
        const displayed = new Set(older ? page.rows.map(row => row.id) : []);
        const appended = visible.filter(({ chat }) => !displayed.has(chat)).map(toRow);
        page.rows = older ? [...page.rows, ...appended] : appended;
        page.cursor = last && cursorOf(last);
        page.more = matches.length > pageSize;
      } catch (error) {
        if (request === generation) {
          const label = older ? 'Could not load older Chat Sessions.'
            : wantImports ? 'Could not load imported Chat Sessions.' : 'Could not load live Chat Sessions.';
          page.problem = error instanceof Error ? label + ' ' + error.message : label;
        }
      } finally {
        if (request === generation) page.loading = false;
      }
    };

    return () => {
      generation++;
      read = undefined;
      bridge.close();
    };
  });
</script>

<WilloStation
  rows={live.rows}
  loading={live.loading}
  problem={live.problem}
  more={live.more}
  onRetry={() => void read?.(liveTab, live.retryOlder)}
  onLoadOlder={() => void read?.(liveTab, true)}
  importedView={{
    rows: imported.rows,
    loading: imported.loading,
    problem: imported.problem,
    more: imported.more,
    onRetry: () => void read?.(importedTab, imported.retryOlder),
    onLoadOlder: () => void read?.(importedTab, true),
  }}
  onTabChange={select}
/>
