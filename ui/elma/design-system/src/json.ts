import { stringify } from 'lossless-json';

/** JSON presentation also preserves bigint values supplied by a production adapter. */
export function stringifyJson(value:unknown,space=0):string {
 const encoded=stringify(value,undefined,space);
 if(encoded===undefined)throw new TypeError('The value has no JSON representation.');
 return encoded;
}
