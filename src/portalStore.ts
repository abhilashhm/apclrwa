import {useSyncExternalStore} from 'react';
import {ApiError, apiRequest, errorMessage, onUnauthorized, postJSON} from './api';
import type {CollectionName,CollectionWrite,MigrationCollections,MigrationPreview,PortalCollections,PortalSnapshot,PublicContent,ResidentRecord} from './portalTypes';

type State = {snapshot:PortalSnapshot|null;loading:boolean;mutating:number;error:string;publicContent:PublicContent|null;publicLoading:boolean;publicError:string;expired:boolean};
let state:State={snapshot:null,loading:false,mutating:0,error:'',publicContent:null,publicLoading:false,publicError:'',expired:false};
const listeners=new Set<()=>void>();
let queue:Promise<void>=Promise.resolve();
let epoch=0;
let pendingLoads=0;
const changes:Partial<Record<CollectionName,string>>={residents:'residents',ledger:'ledger',payments:'payments',amcRates:'amc-rates',openingBalances:'ledger',fixedDeposits:'fd',events:'events',officeBearers:'ob',tallyReconciliation:'tally-import'};
function update(patch:Partial<State>) {state={...state,...patch};listeners.forEach(fn=>fn())}
function announce(previous:PortalSnapshot|null,next:PortalSnapshot) {
  const events=new Set<string>();
  (Object.entries(changes) as [CollectionName,string][]).forEach(([name,event])=>{if(JSON.stringify(previous?.collections[name])!==JSON.stringify(next.collections[name]))events.add(event)});
  events.forEach(name=>window.dispatchEvent(new Event(`apclrwa-${name}-change`)));
}
export function usePortalState() {return useSyncExternalStore(fn=>{listeners.add(fn);return()=>listeners.delete(fn)},()=>state)}
export function clearPrivateCache(expired=false) {
  epoch+=1;pendingLoads=0;
  update({snapshot:null,loading:false,mutating:0,error:'',expired});
}
onUnauthorized(expired=>clearPrivateCache(expired));
export function acknowledgeSession() {update({expired:false,error:''})}
export function getSnapshot() {
  if(!state.snapshot)throw new ApiError('Portal data is unavailable. Please sign in and load it again.',401);
  return state.snapshot;
}
export function getCollection<K extends CollectionName>(name:K):PortalCollections[K] {return getSnapshot().collections[name]}
export function getPortalRevision() {return getSnapshot().revision}
export function getSessionResident():ResidentRecord {
  const resident=getSnapshot().currentResident;
  if(!resident)throw new ApiError('This session has no linked resident. Contact the committee.',403);
  return resident;
}
function adopt(snapshot:PortalSnapshot, started:number):PortalSnapshot {
  if(started!==epoch)throw new ApiError('The session changed. Please sign in again.',401);
  if(!snapshot||!Number.isInteger(snapshot.revision)||!snapshot.collections||['residents','ledger','payments','amcRates','expenseTypes','fixedDeposits','events','officeBearers'].some(name=>!Array.isArray(snapshot.collections[name as CollectionName])))throw new ApiError('The server returned incomplete portal data.',502);
  // Defense in depth: only the server's password-free resident model enters memory.
  const stripPassword=(resident:ResidentRecord)=>Object.fromEntries(Object.entries(resident).filter(([key])=>!/password/i.test(key)||key==='tempPassword')) as ResidentRecord;
  const safe={...snapshot,collections:{...snapshot.collections,residents:snapshot.collections.residents.map(stripPassword)},currentResident:snapshot.currentResident?stripPassword(snapshot.currentResident):null};
  const previous=state.snapshot;
  update({snapshot:safe,error:'',expired:false});
  announce(previous,safe);
  return safe;
}
function serial<T>(job:(started:number)=>Promise<T>):Promise<T> {
  const started=epoch;
  const result=queue.then(()=>{
    if(started!==epoch)throw new ApiError('The session changed. Please sign in again.',401);
    return job(started);
  });
  // Keep the queue usable after a rejected request; callers still receive its rejection.
  queue=result.then(()=>undefined,()=>undefined);
  return result;
}
export async function loadPortal():Promise<void> {
  const started=epoch;
  pendingLoads+=1;
  update({loading:true,error:''});
  try {await serial(async token=>adopt(await apiRequest<PortalSnapshot>('/api/portal'),token))}
  catch(error) {if(started===epoch)update({error:errorMessage(error)});throw error}
  finally {if(started===epoch){pendingLoads=Math.max(0,pendingLoads-1);update({loading:pendingLoads>0})}}
}
async function mutation(action:(snapshot:PortalSnapshot)=>Promise<PortalSnapshot>):Promise<PortalSnapshot> {
  const started=epoch;
  update({mutating:state.mutating+1,error:''});
  try {
    return await serial(async token=>{
      const snapshot=getSnapshot();
      try {return adopt(await action(snapshot),token)}
      catch(error) {
        if(error instanceof ApiError&&error.status===409) {
          // Refresh for the next explicit attempt; never replay a conflicting write.
          try {adopt(await apiRequest<PortalSnapshot>('/api/portal'),token)}
          catch(refreshError) {throw new ApiError(`${errorMessage(error)} Refresh also failed: ${errorMessage(refreshError)}`,409)}
        }
        throw error;
      }
    });
  } catch(error) {if(started===epoch)update({error:errorMessage(error)});throw error}
  finally {if(started===epoch)update({mutating:Math.max(0,state.mutating-1)})}
}
export function saveCollection<K extends CollectionName>(name:K, change:(current:PortalCollections[K])=>CollectionWrite<K>, baseRevision?:number) {
  return mutation(snapshot=>{
    if(baseRevision!==undefined&&baseRevision!==snapshot.revision)throw new ApiError('Shared data changed while this form was open. Close and reopen it to review the latest data.',409);
    const value=change(snapshot.collections[name]);
    return postJSON<PortalSnapshot>(`/api/admin/collections/${name}`,{revision:snapshot.revision,value});
  });
}
export function submitResidentPayment(input:{type:string;numericAmount:number;mode:string;details:string;idempotencyKey:string}) {
  return mutation(()=>postJSON<PortalSnapshot>('/api/resident/payments',input));
}
export function reviewPayment(id:string,status:'Approved'|'Rejected') {
  return mutation(snapshot=>postJSON<PortalSnapshot>(`/api/admin/payments/${encodeURIComponent(id)}/review`,{revision:snapshot.revision,status}));
}
export function previewMigration(collections:MigrationCollections) {
  return serial(()=>postJSON<MigrationPreview>('/api/admin/migration/preview',{collections}));
}
export function importMigration(collections:MigrationCollections,revision:number) {
  return mutation(()=>postJSON<PortalSnapshot>('/api/admin/migration/import',{collections,revision}));
}
export type TallyImportEnvironment = 'local'|'cloudflare'|'unknown';
/**
 * Detect the server behind the current same-origin API without inferring from
 * hostnames. The local API exposes the private snapshot route (404 is still a
 * local capability response when no snapshot exists); the Worker deliberately
 * answers 501 because it cannot read the local filesystem.
 */
export async function detectTallyImportEnvironment():Promise<TallyImportEnvironment> {
  try {
    await apiRequest<unknown>('/api/admin/tally-import',{},false);
    return 'local';
  } catch(error) {
    if(error instanceof ApiError&&error.status===501)return 'cloudflare';
    if(error instanceof ApiError&&error.status!==0)return 'local';
    return 'unknown';
  }
}
export function applyTallyImport() {
  return mutation(snapshot=>postJSON<PortalSnapshot>('/api/admin/tally-import/apply',{revision:snapshot.revision}));
}
const REMOTE_TALLY_IMPORT_ENDPOINT='/api/admin/tally-import/upload';
export function uploadTallyImport(snapshot:unknown) {
  return mutation(current=>postJSON<PortalSnapshot>(REMOTE_TALLY_IMPORT_ENDPOINT,{revision:current.revision,snapshot}).catch(error=>{
    if(error instanceof ApiError&&error.status===501)throw new ApiError('Cloudflare Tally upload is not supported by this server yet (501).',501);
    throw error;
  }));
}
// Public content is a distinct cache populated exclusively by the public endpoint.
export async function loadPublicContent():Promise<void> {
  if(state.publicLoading)return;
  update({publicLoading:true,publicError:''});
  try {
    const content=await apiRequest<PublicContent>('/api/public/content',{},false);
    if(!Array.isArray(content?.events)||!Array.isArray(content?.officeBearers)||!Array.isArray(content?.professionals)||!Array.isArray(content?.contacts))throw new Error('The server returned incomplete public content.');
    update({publicContent:{events:content.events.filter(event=>!event.residentsOnly),officeBearers:content.officeBearers,professionals:content.professionals,contacts:content.contacts}});
  } catch(error) {update({publicContent:null,publicError:errorMessage(error)})}
  finally {update({publicLoading:false})}
}
