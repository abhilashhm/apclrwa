const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message:string, public readonly status:number) {super(message);this.name='ApiError'}
}

let unauthorized:(expired:boolean)=>void = ()=>{};
export function onUnauthorized(handler:(expired:boolean)=>void) {unauthorized=handler}

export async function apiRequest<T>(path:string, options:RequestInit={}, expireSession=true):Promise<T> {
  let response:Response;
  try {
    response=await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials:'include',
      headers:{...(options.body?{'Content-Type':'application/json'}:{}),...options.headers},
    });
  } catch {
    throw new ApiError('The server is unavailable. Check your connection and try again.',0);
  }
  if(response.status===401)unauthorized(expireSession);
  const text=await response.text();
  let body:any;
  try {body=text?JSON.parse(text):null} catch {throw new ApiError('The server returned an invalid response. Please try again.',response.status)}
  if(!response.ok) {
    const detail=typeof body?.detail==='string'?body.detail:response.status===409?'Shared data changed. Refresh the portal and reopen this form before trying again.':response.status===401?'Your session has expired. Please sign in again.':`The server request failed (${response.status}). Please try again.`;
    throw new ApiError(detail,response.status);
  }
  return body as T;
}

export function postJSON<T>(path:string, body:unknown, expireSession=true) {
  return apiRequest<T>(path,{method:'POST',body:JSON.stringify(body)},expireSession);
}

export function errorMessage(error:unknown) {return error instanceof Error?error.message:'The request failed. Please try again.'}
