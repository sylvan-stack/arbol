<script lang="ts">
  import { onMount } from 'svelte';
  import WilloStation, { type ChatSessionRow } from '../../design-system/src/pages/WilloStation.svelte';
  import { Bridge } from '../bridge';

  interface Summary {
    chat: string;
    title: string | null;
    firstMessage?: string;
    activityAt: string;
  }

  const pageSize = 50;
  let rows = $state<ChatSessionRow[]>([]);
  let loading = $state(true);
  let more = $state(false);
  let problem = $state('');
  let read: ((older: boolean) => Promise<void>) | undefined;
  let retryOlder = false;

  function toRow(summary: Summary): ChatSessionRow {
    const firstLine = summary.firstMessage?.split('\n', 1)[0].trim() ?? '';
    return {
      id: summary.chat,
      title: summary.title?.trim() || Array.from(firstLine).slice(0, 80).join('') || 'Untitled Chat Session',
      activityAt: summary.activityAt,
    };
  }

  onMount(() => {
    let cursor: { activityAt: string; chat: string } | undefined;
    let generation = 0;
    let greeted = false;
    const bridge = new Bridge({
      onhello: () => {
        greeted = true;
        void read?.(false);
      },
      onstate: (state) => {
        if (state === 'Reconnecting…') {
          generation++;
          greeted = false;
          loading = true;
          problem = '';
        } else if (!greeted && state !== 'Connected') {
          problem = state;
          loading = false;
        }
      },
    });

    read = async (older) => {
      if (older && (!cursor || !more || loading)) return;
      const request = ++generation;
      retryOlder = older;
      loading = true;
      problem = '';
      try {
        const before = older ? cursor : undefined;
        const reply = await bridge.call<{ chats: Summary[] }>('chats.page', {
          limit: pageSize + 1, ...(before && { before }),
        });
        if (request !== generation) return;
        if (!Array.isArray(reply?.chats) || reply.chats.some(row =>
          typeof row?.chat !== 'string' || !row.chat ||
          typeof row.activityAt !== 'string' || !Number.isFinite(Date.parse(row.activityAt)) ||
          (row.title !== null && typeof row.title !== 'string') ||
          (row.firstMessage !== undefined && typeof row.firstMessage !== 'string')
        )) throw new Error('Arbol returned an invalid Chat Session list.');

        const page = reply.chats.slice(0, pageSize);
        const last = page.at(-1);
        const displayed = new Set(older ? rows.map(row => row.id) : []);
        const appended = page.filter(({ chat }) => {
          if (displayed.has(chat)) return false;
          displayed.add(chat);
          return true;
        }).map(toRow);
        rows = older ? [...rows, ...appended] : appended;
        cursor = last && { activityAt: last.activityAt, chat: last.chat };
        more = reply.chats.length > pageSize;
      } catch (error) {
        if (request === generation) {
          const label = older ? 'Could not load older Chat Sessions.' : 'Could not load recent Chat Sessions.';
          problem = error instanceof Error ? label + ' ' + error.message : label;
        }
      } finally {
        if (request === generation) loading = false;
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
  {rows}
  {loading}
  {problem}
  {more}
  onRetry={() => void read?.(retryOlder)}
  onLoadOlder={() => void read?.(true)}
/>
