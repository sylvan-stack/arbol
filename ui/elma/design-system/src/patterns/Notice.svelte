<script lang="ts">
 import type {Snippet} from 'svelte';
 let {message,tone='info',role='status',identity,severity,children}:{message:string;tone?:'info'|'warning'|'urgent';role?:'status'|'alert';identity?:string;severity?:string;children?:Snippet}=$props();
</script>
<div class="notice-line {tone}" {role} data-notice-id={identity} data-severity={severity??tone}><span>{message}</span>{#if children}<div class="actions">{@render children()}</div>{/if}</div>
<style>
.notice-line{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px 16px;padding:8px 16px;background:var(--inset);border-bottom:1px solid var(--border);color:var(--text);min-width:0}.notice-line>span{min-width:0;overflow-wrap:anywhere;white-space:pre-wrap;flex:1 1 240px}.warning{color:var(--warning)}.urgent{color:var(--failure)}.actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
</style>
