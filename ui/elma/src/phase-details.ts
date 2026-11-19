import { parse } from 'lossless-json';
import { phaseLabel, phaseOrder, type PhaseName } from '../design-system/src/sections/ExchangeDetails.svelte';
import type { Bridge } from './bridge';

type Fields = Record<string, unknown>;
type Fragment = { position: number; text: string; nextOffset?: number };
type Page = { entries: Fragment[] };
type Phase = { fields: Fields; commands: Fields[]; finished: boolean };

function object(value: unknown): Fields | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Fields : undefined;
}

export function isSteadyExchange(value: unknown): boolean {
  return object(value)?.trunk === 'steady';
}

export class PhaseDetailsReader {
  private after = 0;
  private offset = 0;
  private bufferedPosition = 0;
  private chunks: string[] = [];
  private publicData: Fields = {};
  private privateData = new Map<PhaseName, Phase>();
  currentPhase: PhaseName | null = null;

  constructor(private readonly bridge: Bridge, readonly exchange: string) {}

  get phases(): PhaseName[] {
    return phaseOrder.filter(phase => this.privateData.has(phase));
  }

  snapshot(phase: PhaseName, complete: boolean): Fields | null {
    const selected = this.privateData.get(phase);
    if (!selected) return null;
    return {
      publicExchange: { id: this.exchange, status: complete ? 'complete' : 'running',
        currentPhase: this.currentPhase, ...this.publicData },
      privatePhase: { phase: phaseLabel(phase),
        status: selected.finished ? 'finished' : complete ? 'interrupted' : 'running',
        ...selected.fields, commands: selected.commands },
    };
  }

  async read(isCurrent: () => boolean): Promise<void> {
    while (isCurrent()) {
      const page = await this.bridge.call<Page>('exchange.phaseDetails', {
        exchange: this.exchange, after: this.after, offset: this.offset,
      });
      if (!isCurrent()) return;
      if (!page || !Array.isArray(page.entries)) throw new Error('Invalid phase detail page.');
      if (!page.entries.length) {
        if (this.offset) throw new Error('A partial phase detail entry is unavailable.');
        return;
      }
      for (const fragment of page.entries) this.take(fragment);
    }
  }

  private take(fragment: Fragment): void {
    const { position, text, nextOffset } = fragment;
    if (!Number.isSafeInteger(position) || position <= this.after || typeof text !== 'string' || !text
      || (this.offset && this.bufferedPosition !== position)) {
      throw new Error('Invalid phase detail position.');
    }
    if (nextOffset !== undefined) {
      if (!Number.isSafeInteger(nextOffset) || nextOffset !== this.offset + Array.from(text).length) {
        throw new Error('Invalid phase detail offset.');
      }
      this.chunks.push(text);
      this.bufferedPosition = position;
      this.offset = nextOffset;
      return;
    }
    const detail = object(parse(this.offset ? this.chunks.join('') + text : text));
    const phase = phaseOrder.find(name => name === detail?.phase);
    if (!detail || !phase) throw new Error('Invalid phase detail entry.');
    this.project(phase, detail);
    this.after = position;
    this.offset = 0;
    this.bufferedPosition = 0;
    this.chunks = [];
  }

  private project(phase: PhaseName, detail: Fields): void {
    const selected = this.privateData.get(phase) ?? { fields: {}, commands: [], finished: false };
    if (typeof detail.startedAt === 'string') {
      this.currentPhase = phase;
      selected.fields.startedAt = detail.startedAt;
    }
    const command = object(detail.command);
    if (command) selected.commands.push(command);
    const fields = object(detail.privatePhase);
    if (fields) selected.fields = { ...selected.fields, ...fields };
    const publicData = object(detail.publicExchange);
    if (publicData) this.publicData = { ...this.publicData, ...publicData };
    if (typeof detail.finishedAt === 'string') {
      if (this.currentPhase === phase) this.currentPhase = null;
      selected.finished = true;
      selected.fields.finishedAt = detail.finishedAt;
    }
    this.privateData.set(phase, selected);
  }
}
