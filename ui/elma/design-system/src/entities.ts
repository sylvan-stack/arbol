/* @arbol/design-system — Entity kit data (ux-ui-guide.md §1.11). Framework-
 * agnostic: types + the ENTITIES registry + self-injecting chip styles. The
 * Svelte EntityChip/EntityCard render from this. (Ported from entities/index.tsx.) */

export type EntityKind =
  | 'ticket'
  | 'graft'
  | 'mr'
  | 'commit'
  | 'slack'
  | 'telegram'
  | 'telegram_conversation'
  | 'email'
  | 'confluence'
  | 'comunicado'
  | 'chat'
  | 'artifact'
  | 'requirement'
  | 'invariant'
  | 'glossary'
  | 'secret'
  | 'flyer'
  | 'branch'
  | 'hunk'
  | 'living_topic'
  | 'mandate'
  | 'prompt'
  | 'response';

export type EntityShape = 'span' | 'mark' | 'note';

export type EntityKindMeta = {
  tag: string;
  label: string;
  shape: EntityShape;
  hue: number;
  glyph: string;
};

export type Entity = {
  kind: EntityKind;
  title: string;
  meta?: string;
  state?: string;
  live?: boolean;
};

export const KINDS: Record<EntityKind, EntityKindMeta> = {
  ticket: { tag: 'tic', label: 'Ticket', shape: 'mark', hue: 256, glyph: '▣' },
  graft: { tag: 'grf', label: 'Graft', shape: 'note', hue: 84, glyph: '⋎' },
  mr: { tag: 'mr', label: 'Merge request', shape: 'mark', hue: 150, glyph: '⇄' },
  commit: { tag: 'cmt', label: 'Commit', shape: 'mark', hue: 200, glyph: '●' },
  slack: { tag: 'slk', label: 'Slack message', shape: 'mark', hue: 285, glyph: '#' },
  telegram_conversation: {
    tag: 'tlc',
    label: 'Telegram conversation',
    shape: 'mark',
    hue: 220,
    glyph: '➤',
  },
  telegram: { tag: 'tel', label: 'Telegram message', shape: 'mark', hue: 220, glyph: '➤' },
  email: { tag: 'eml', label: 'Email', shape: 'mark', hue: 180, glyph: '✉' },
  confluence: { tag: 'cnf', label: 'Confluence page', shape: 'note', hue: 215, glyph: '◧' },
  comunicado: { tag: 'com', label: 'Comunicado', shape: 'mark', hue: 45, glyph: '!' },
  chat: { tag: 'cht', label: 'Chat session', shape: 'span', hue: 34, glyph: '❝' },
  artifact: { tag: 'arf', label: 'Artifact', shape: 'note', hue: 210, glyph: '◫' },
  requirement: { tag: 'req', label: 'Requirement', shape: 'note', hue: 95, glyph: '§' },
  invariant: { tag: 'inv', label: 'Invariant', shape: 'note', hue: 322, glyph: '∎' },
  glossary: { tag: 'glo', label: 'Glossary term', shape: 'note', hue: 122, glyph: '≝' },
  secret: { tag: 'sec', label: 'Arbol secret', shape: 'note', hue: 0, glyph: '⚷' },
  flyer: { tag: 'fly', label: 'Flyer', shape: 'note', hue: 68, glyph: '▤' },
  branch: { tag: 'brn', label: 'Branch', shape: 'note', hue: 270, glyph: '⎇' },
  hunk: { tag: 'hun', label: 'Hunk', shape: 'note', hue: 12, glyph: '≋' },
  living_topic: { tag: 'liv', label: 'Living Topic', shape: 'note', hue: 172, glyph: '◉' },
  mandate: { tag: 'mnd', label: 'Mandate', shape: 'note', hue: 48, glyph: '✦' },
  prompt: { tag: 'pmt', label: 'Prompt', shape: 'mark', hue: 264, glyph: '›' },
  response: { tag: 'rsp', label: 'Response', shape: 'mark', hue: 156, glyph: '‹' },
};
