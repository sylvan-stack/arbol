declare const __ARBOL_BUILD__: string;
interface Window {
 webkit?: {messageHandlers?:{arbol?:{postMessage:(text:string)=>void};arbolApp?:{postMessage:(text:string)=>void}}};
 arbolBridge?: {receive:(text:string)=>void};
 arbolApp?: {receive:(text:string)=>void};
}
