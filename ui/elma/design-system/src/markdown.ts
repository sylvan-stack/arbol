/** Safe CommonMark + GFM tables: parse structure, never render an HTML string. */
import { fromMarkdown } from 'mdast-util-from-markdown';
import { gfmTableFromMarkdown } from 'mdast-util-gfm-table';
import { gfmTable } from 'micromark-extension-gfm-table';
export type SafeTag='p'|'h1'|'h2'|'h3'|'h4'|'h5'|'h6'|'ul'|'ol'|'li'|'blockquote'|'strong'|'em'|'code';
export type MarkdownNode={kind:'text';value:string}|{kind:'tag';tag:SafeTag;children:MarkdownNode[];start?:number}|{kind:'code';value:string;lang?:string}|{kind:'link';url:string;children:MarkdownNode[]}|{kind:'table';rows:MarkdownNode[][][];align:('left'|'right'|'center'|null)[]}|{kind:'break'|'rule'};
interface Tree {type:string;value?:string;url?:string;identifier?:string;depth?:number;ordered?:boolean;start?:number;lang?:string;children?:Tree[];align?:('left'|'right'|'center'|null)[];position?:{start:{offset?:number};end:{offset?:number}}}
export function linkURL(value:string):string|null {try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:null;}catch{return null;}}
export function markdown(text:string):MarkdownNode[]{
 try{
  const root=fromMarkdown(text,{extensions:[gfmTable()],mdastExtensions:[gfmTableFromMarkdown()]}) as unknown as Tree;
  const definitions=new Map((root.children??[]).filter(n=>n.type==='definition').map(n=>[n.identifier,n.url??'']));let budget=200000;
  function raw(node:Tree):string{return node.position?text.slice(node.position.start.offset??0,node.position.end.offset??text.length):node.value??'';}
  function convert(node:Tree,depth=0,inline=false):MarkdownNode[]{
   if(--budget<0)throw new Error('Render budget');
   if(depth>16)throw new Error('Render depth');
   const children=()=> (node.children??[]).flatMap(n=>convert(n,depth+1,['paragraph','heading','strong','emphasis','link','linkReference','tableCell'].includes(node.type)));
   const tag=(tag:SafeTag):MarkdownNode[]=>[{kind:'tag',tag,children:children(),...(tag==='ol'&&typeof node.start==='number'?{start:node.start}:{})}];
   switch(node.type){
    case 'root':return children();case 'definition':return [];
    case 'text':return[{kind:'text',value:node.value??''}];case 'html':return inline?[{kind:'text',value:node.value??''}]:[{kind:'tag',tag:'p',children:[{kind:'text',value:node.value??''}]}];
    case 'paragraph':return tag('p');case 'heading':return tag(('h'+Math.max(1,Math.min(6,node.depth??1))) as SafeTag);
    case 'list':return tag(node.ordered?'ol':'ul');case 'listItem':return tag('li');case 'blockquote':return tag('blockquote');
    case 'strong':return tag('strong');case 'emphasis':return tag('em');case 'inlineCode':return[{kind:'tag',tag:'code',children:[{kind:'text',value:node.value??''}]}];
    case 'code':return[{kind:'code',value:node.value??'',lang:node.lang}];case 'break':return[{kind:'break'}];case 'thematicBreak':return[{kind:'rule'}];
    case 'link':case 'linkReference':{const target=node.url??definitions.get(node.identifier)??'',url=linkURL(target);return url?[{kind:'link',url,children:children()}]:[{kind:'text',value:raw(node)}];}
    case 'image':case 'imageReference':return[{kind:'text',value:raw(node)}];
    case 'table':return[{kind:'table',align:node.align??[],rows:(node.children??[]).map(row=>(row.children??[]).map(cell=>(cell.children??[]).flatMap(n=>convert(n,depth+1,true))))}];
    default:return[{kind:'text',value:raw(node)}];
   }
  }
  return convert(root);
 }catch{return[{kind:'text',value:text}];}
}
