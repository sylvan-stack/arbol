<script lang="ts">
 import { markdown, type MarkdownNode } from '../markdown';
 let {text='',onopenLink}: {text?:string;onopenLink?:(url:string)=>Promise<unknown>}=$props();
 const nodes=$derived(markdown(text));let feedback=$state('');
 async function open(url:string){try{if(onopenLink)await onopenLink(url);else feedback='Link selected in fixture: '+url;}catch(error){feedback=error instanceof Error?error.message:'The link could not be opened.';}}
</script>
{#snippet render(nodes:MarkdownNode[])}
 {#each nodes as node}
  {#if node.kind==='text'}{node.value}
  {:else if node.kind==='tag'}{#if node.tag==='ol'}<ol start={node.start}>{@render render(node.children)}</ol>{:else}<svelte:element this={node.tag}>{@render render(node.children)}</svelte:element>{/if}
  {:else if node.kind==='code'}<!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable code stays keyboard reachable.) --><pre tabindex="0" role="region" aria-label={node.lang?'Code: '+node.lang:'Code'}><code>{node.value}</code></pre>
  {:else if node.kind==='link'}<button type="button" role="link" class="md-link" title={node.url} onclick={()=>void open(node.url)}>{@render render(node.children)}</button>
  {:else if node.kind==='table'}<!-- svelte-ignore a11y_no_noninteractive_tabindex (Scrollable table stays keyboard reachable.) --><div class="table-scroll" tabindex="0" role="region" aria-label="Table"><table><thead>{#each node.rows.slice(0,1) as row}<tr>{#each row as cell,i}<th style:text-align={node.align[i]??undefined}>{@render render(cell)}</th>{/each}</tr>{/each}</thead><tbody>{#each node.rows.slice(1) as row}<tr>{#each row as cell,i}<td style:text-align={node.align[i]??undefined}>{@render render(cell)}</td>{/each}</tr>{/each}</tbody></table></div>
  {:else if node.kind==='break'}<br/>{:else}<hr/>{/if}
 {/each}
{/snippet}
<div class="markdown">{@render render(nodes)}{#if feedback}<p class="link-feedback" role="status">{feedback}</p>{/if}</div>
<style>
.markdown{min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}.markdown :global(p){margin:0 0 .85em}.markdown :global(h1),.markdown :global(h2),.markdown :global(h3),.markdown :global(h4),.markdown :global(h5),.markdown :global(h6){margin:1em 0 .5em;line-height:1.3;font-size:1.15em}.markdown :global(h1){font-size:1.5em}.markdown :global(h2){font-size:1.3em}.markdown :global(ul),.markdown :global(ol){white-space:normal;margin:.5em 0 1em;padding-left:1.6em}.markdown :global(li p){margin:.15em 0}.markdown :global(blockquote){border-left:3px solid var(--border);margin:1em 0;padding-left:16px;color:var(--muted)}.markdown :global(code){font-family:var(--font-mono);font-size:.9em}.markdown :global(pre){max-width:100%;overflow:auto;white-space:pre;background:var(--inset);border:1px solid var(--border);border-radius:5px;padding:12px;margin:.75em 0}.md-link{display:inline;background:none;border:0;color:var(--link);font:inherit;text-decoration:underline;padding:0;cursor:pointer;text-align:inherit;overflow-wrap:anywhere}.table-scroll{overflow:auto;max-width:100%;margin:.75em 0}table{border-collapse:collapse;width:100%;white-space:normal}th,td{border:1px solid var(--border);padding:6px 10px;vertical-align:top}.link-feedback{font-size:.85em;color:var(--muted)}
</style>
