import { isLosslessNumber,parse } from 'lossless-json';
import { stringifyJson } from '../design-system/src/json';

export type Revision=number|bigint;
export function validRevision(value:unknown):value is Revision {
 return typeof value==='bigint'?value>0n&&value<=9223372036854775807n:typeof value==='number'&&Number.isSafeInteger(value)&&value>0;
}
export function sameRevision(a:Revision|null,b:Revision|null):boolean {
 return a===null||b===null?a===b:validRevision(a)&&validRevision(b)&&BigInt(a)===BigInt(b);
}
/** The server's bigint wire integers must never pass through an unsafe JS number. */
export function parseWire(text:string):unknown {
 return parse(text,(key,value)=>{
  if(!isLosslessNumber(value))return value;
  const raw=value.value,numeric=Number(raw);
  if((key==='revision'||key==='baseRevision')&&/^-?\d+$/.test(raw)&&!Number.isSafeInteger(numeric))return BigInt(raw);
  if(!Number.isFinite(numeric))throw new SyntaxError('The JSON number is not finite.');
  return numeric;
 });
}
export const stringifyWire=stringifyJson;
