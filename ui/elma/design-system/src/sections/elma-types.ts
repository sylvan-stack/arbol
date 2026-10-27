/** Public presentation inputs. Production adapters supply state; stories use fictional data. */
export interface ElmaRoute {driver?:string;subscription?:string;model?:string;effort?:string}
export interface ElmaMessage {position:number;kind:'message';role:'user'|'assistant';text:string}
export interface ElmaTool {position:number;kind:'tool';name:string;input:unknown;ok:boolean;result?:unknown;error?:string;truncated:boolean;interrupted:boolean;cut?:boolean;ask?:unknown;answer?:unknown}
export interface ElmaExchange {exchange:string;number:number;state:string;route:ElmaRoute;workingFolder:string;acceptedAt:string;endedAt?:string;items:(ElmaMessage|ElmaTool)[];runs:{kind:string;outcome:string;usage:Record<string,unknown>;started?:Record<string,unknown>}[];error?:{code:string;message:string;retryAfterSeconds?:number};note?:{kind:string;at:string}}
