import type {MigrationCollections} from './portalTypes';

// These keys are read only in the committee's explicit preview/cleanup workflow.
const LEGACY_KEYS={
  residents:'apclrwa_residents',ledger:'apclrwa_admin_ledger',payments:'apclrwa_pending_payments',
  amcRates:'apclrwa_amc_rates',openingBalances:'apclrwa_opening_balances',expenseTypes:'apclrwa_expense_types',
  fixedDeposits:'apclrwa_fixed_deposits',events:'apclrwa_events',officeBearers:'apclrwa_office_bearers',
} as const;
const UNSUPPORTED_KEYS=['apclrwa_tally_reconciliation','apclrwa_tally_import_id'];
export type LegacySource={collections:MigrationCollections;fingerprints:Record<string,string>};
export function detectLegacyKeys() {
  const present=new Set<string>();
  try {for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(key)present.add(key)}}
  catch {return {supported:[],skipped:0,error:'Legacy browser storage is unavailable. Allow browser storage access to preview a migration.'}}
  return {
    supported:Object.entries(LEGACY_KEYS).filter(([,key])=>present.has(key)).map(([name])=>name),
    skipped:UNSUPPORTED_KEYS.filter(key=>present.has(key)).length,
    error:'',
  };
}
function stripPasswords(value:unknown):unknown {
  if(Array.isArray(value))return value.map(stripPasswords);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>!/password/i.test(key)).map(([key,child])=>[key,stripPasswords(child)]));
  return value;
}
async function fingerprint(value:string) {
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
}
export async function readLegacyForPreview():Promise<LegacySource> {
  const collections:Record<string,unknown>={};
  const fingerprints:Record<string,string>={};
  for(const[name,key]of Object.entries(LEGACY_KEYS)) {
    const raw=localStorage.getItem(key);
    if(raw===null)continue;
    let parsed:unknown;
    try {parsed=JSON.parse(raw)} catch {throw new Error(`Legacy ${name} data is not valid JSON. The original browser data has been preserved.`)}
    collections[name]=stripPasswords(parsed);
    fingerprints[key]=await fingerprint(raw);
  }
  return {collections:collections as MigrationCollections,fingerprints};
}
export async function cleanupImportedLegacy(source:LegacySource) {
  let removed=0,changed=0;
  for(const[key,original]of Object.entries(source.fingerprints)) {
    const value=localStorage.getItem(key);
    if(value===null)continue;
    if(await fingerprint(value)!==original){changed+=1;continue}
    localStorage.removeItem(key);removed+=1;
  }
  return {removed,changed};
}
