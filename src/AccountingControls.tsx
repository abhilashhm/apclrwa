import {FormEvent,useEffect,useMemo,useState} from 'react';
import {apiRequest,errorMessage,postJSON} from './api';
import type {AccountingAccount,AccountingPeriod,AuditEventRecord,JournalEntryRecord} from './portalTypes';
import {MutationNotice,useMutation} from './useMutation';

type AccountingTab='journal'|'periods'|'audit'|'accounts';
type AccountingState={accounts:AccountingAccount[];periods:AccountingPeriod[];entries:JournalEntryRecord[];audit:AuditEventRecord[]};

function currentFinancialYear(){
  const now=new Date();
  const start=now.getMonth()>=3?now.getFullYear():now.getFullYear()-1;
  return `${start}–${String(start+1).slice(-2)}`;
}

function isoDate(){return new Date().toISOString().slice(0,10)}
function rupees(paise:number){return '₹ '+(paise/100).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}
function paise(value:string){const amount=Number(value);return Number.isFinite(amount)&&amount>0?Math.round(amount*100):0}
function periodLabel(period:AccountingPeriod){return `FY ${period.financialYear} • ${period.status}`}

async function loadAccounting():Promise<AccountingState>{
  const [accounts,periods,entries,audit]=await Promise.all([
    apiRequest<{accounts:AccountingAccount[]}>('/api/admin/accounting/accounts'),
    apiRequest<{periods:AccountingPeriod[]}>('/api/admin/accounting/periods'),
    apiRequest<{entries:JournalEntryRecord[]}>('/api/admin/accounting/journal-entries'),
    apiRequest<{events:AuditEventRecord[]}>('/api/admin/accounting/audit-events?limit=100'),
  ]);
  return {accounts:accounts.accounts,periods:periods.periods,entries:entries.entries,audit:audit.events};
}

function JournalForm({accounts,onSaved}:{accounts:AccountingAccount[];onSaved:()=>Promise<void>}){
  const mutation=useMutation();
  const[date,setDate]=useState(isoDate());
  const[financialYear,setFinancialYear]=useState(currentFinancialYear());
  const[description,setDescription]=useState('');
  const[debitAccount,setDebitAccount]=useState('');
  const[creditAccount,setCreditAccount]=useState('');
  const[amount,setAmount]=useState('');
  const[error,setError]=useState('');
  const active=accounts.filter(account=>account.active);
  const submit=async(event:FormEvent)=>{
    event.preventDefault();setError('');
    const value=paise(amount);
    if(!description.trim()||!date||!financialYear||!debitAccount||!creditAccount||debitAccount===creditAccount||!value){setError('Enter a description, date, financial year, two different accounts and a positive amount.');return}
    if(await mutation.run(async()=>{await postJSON('/api/admin/accounting/journal-entries',{date,financialYear,description:description.trim(),lines:[{accountId:debitAccount,debitPaise:value,creditPaise:0},{accountId:creditAccount,debitPaise:0,creditPaise:value}]});await onSaved()})){
      setDescription('');setAmount('');
    }
  };
  return <section className="admin-panel accounting-entry-form"><div className="panel-head"><div><span>CONTROLLED POSTING</span><h3>Create draft journal</h3></div></div><p className="module-note">Entries are created as drafts, must balance exactly in paise, and can only be posted while their accounting period is open.</p><form onSubmit={submit}><fieldset className="portal-form-fields" disabled={mutation.saving}><div className="resident-form-grid"><label>Date<input type="date" value={date} onChange={event=>setDate(event.target.value)} required/></label><label>Financial year<input value={financialYear} onChange={event=>setFinancialYear(event.target.value)} placeholder="2026–27" required/></label><label>Description<input value={description} onChange={event=>setDescription(event.target.value)} placeholder="Bank receipt / expense / adjustment" required/></label><label>Amount (₹)<input type="number" min="0.01" step="0.01" value={amount} onChange={event=>setAmount(event.target.value)} required/></label><label>Debit account<select value={debitAccount} onChange={event=>setDebitAccount(event.target.value)} required><option value="">Select account</option>{active.map(account=><option key={account.id} value={account.id}>{account.code} — {account.name}</option>)}</select></label><label>Credit account<select value={creditAccount} onChange={event=>setCreditAccount(event.target.value)} required><option value="">Select account</option>{active.map(account=><option key={account.id} value={account.id}>{account.code} — {account.name}</option>)}</select></label></div>{error&&<div className="login-error" role="alert">{error}</div>}<MutationNotice {...mutation}/><div className="event-modal-actions"><button className="admin-primary" type="submit">Save draft journal</button></div></fieldset></form></section>;
}

function CorrectionForm({entry,accounts,onClose,onSaved}:{entry:JournalEntryRecord;accounts:AccountingAccount[];onClose:()=>void;onSaved:()=>Promise<void>}){
  const mutation=useMutation();
  const originalDebit=entry.lines.find(line=>line.debitPaise>0)?.accountId||'';
  const originalCredit=entry.lines.find(line=>line.creditPaise>0)?.accountId||'';
  const[date,setDate]=useState(entry.date);const[financialYear,setFinancialYear]=useState(entry.financialYear);const[description,setDescription]=useState(`Correction of ${entry.id}`);const[reason,setReason]=useState('');const[authorization,setAuthorization]=useState('');const[debitAccount,setDebitAccount]=useState(originalDebit);const[creditAccount,setCreditAccount]=useState(originalCredit);const[amount,setAmount]=useState(String((entry.lines.reduce((total,line)=>total+line.debitPaise,0)/100).toFixed(2)));const[error,setError]=useState('');
  const submit=async(event:FormEvent)=>{event.preventDefault();setError('');const value=paise(amount);if(!date||!financialYear||!description.trim()||!reason.trim()||!authorization.trim()||!debitAccount||!creditAccount||debitAccount===creditAccount||!value){setError('Enter the corrected date, FY, description, reason, authorization, two accounts and a positive amount.');return}await mutation.run(async()=>{await postJSON(`/api/admin/accounting/journal-entries/${encodeURIComponent(entry.id)}/correct`,{date,financialYear,description:description.trim(),reason:reason.trim(),authorization:authorization.trim(),lines:[{accountId:debitAccount,debitPaise:value,creditPaise:0},{accountId:creditAccount,debitPaise:0,creditPaise:value}]});await onSaved();onClose()})};
  return <div className="resident-modal-backdrop"><form className="resident-modal" onSubmit={submit}><fieldset className="portal-form-fields" disabled={mutation.saving}><div className="event-modal-head"><div><div className="eyebrow">LINKED CORRECTION</div><h2>Correct {entry.id}</h2></div><button type="button" className="modal-close" onClick={onClose}>×</button></div><p className="module-note">The original posted entry remains immutable. This creates a new posted correction linked to it.</p><div className="resident-form-grid"><label>Date<input type="date" value={date} onChange={event=>setDate(event.target.value)} required/></label><label>Financial year<input value={financialYear} onChange={event=>setFinancialYear(event.target.value)} required/></label><label>Description<input value={description} onChange={event=>setDescription(event.target.value)} required/></label><label>Amount (₹)<input type="number" min="0.01" step="0.01" value={amount} onChange={event=>setAmount(event.target.value)} required/></label><label>Debit account<select value={debitAccount} onChange={event=>setDebitAccount(event.target.value)} required><option value="">Select account</option>{accounts.filter(account=>account.active).map(account=><option key={account.id} value={account.id}>{account.code} — {account.name}</option>)}</select></label><label>Credit account<select value={creditAccount} onChange={event=>setCreditAccount(event.target.value)} required><option value="">Select account</option>{accounts.filter(account=>account.active).map(account=><option key={account.id} value={account.id}>{account.code} — {account.name}</option>)}</select></label><label>Reason<textarea value={reason} onChange={event=>setReason(event.target.value)} required/></label><label>Authorization reference<input value={authorization} onChange={event=>setAuthorization(event.target.value)} placeholder="Minutes / approval reference" required/></label></div>{error&&<div className="login-error" role="alert">{error}</div>}<MutationNotice {...mutation}/><div className="event-modal-actions"><button type="button" onClick={onClose}>Cancel</button><button className="admin-primary" type="submit">Create linked correction</button></div></fieldset></form></div>;
}

function JournalList({entries,accounts,onChanged}:{entries:JournalEntryRecord[];accounts:AccountingAccount[];onChanged:()=>Promise<void>}){
  const mutation=useMutation();
  const[correcting,setCorrecting]=useState<JournalEntryRecord|null>(null);
  const post=async(entry:JournalEntryRecord)=>{if(!window.confirm(`Post journal ${entry.id}? Posted entries cannot be edited.`))return;await mutation.run(async()=>{await postJSON(`/api/admin/accounting/journal-entries/${encodeURIComponent(entry.id)}/post`,{});await onChanged()})};
  const reverse=async(entry:JournalEntryRecord)=>{const reason=window.prompt('Reason for reversal:');if(!reason?.trim())return;const authorization=window.prompt('Authorization reference (minutes/approval):');if(!authorization?.trim())return;if(!window.confirm(`Create a linked reversal for ${entry.id}? The original will remain immutable.`))return;await mutation.run(async()=>{await postJSON(`/api/admin/accounting/journal-entries/${encodeURIComponent(entry.id)}/reverse`,{reason,authorization});await onChanged()})};
  return <><section className="admin-panel"><div className="panel-head"><div><span>NORMALIZED JOURNAL</span><h3>Journal entries</h3></div><strong>{entries.length} entries</strong></div><MutationNotice {...mutation}/><div className="admin-data-table-wrap"><table className="admin-data-table"><thead><tr><th>Date</th><th>Reference</th><th>Description</th><th>Lines</th><th>Total</th><th>Status</th><th>Action</th></tr></thead><tbody>{entries.length===0?<tr><td colSpan={7}>No normalized journal entries yet. Imported Tally history remains in the separate historic ledger.</td></tr>:entries.map(entry=><tr key={entry.id}><td>{entry.date}</td><td>{entry.id}</td><td>{entry.description}</td><td>{entry.lines.map(line=><div key={line.id}>{line.accountCode||line.accountId}: {line.debitPaise?`Dr ${rupees(line.debitPaise)}`:`Cr ${rupees(line.creditPaise)}`}</div>)}</td><td>{rupees(entry.lines.reduce((total,line)=>total+line.debitPaise,0))}</td><td><span className={entry.status==='Posted'?'status-pill paid':'status-pill pending'}>{entry.status}</span></td><td><span className="table-action-group">{entry.status==='Draft'&&<button className="table-link" onClick={()=>post(entry)}>Post</button>}{entry.status==='Posted'&&!entry.reversalOfEntryId&&!entry.correctionOfEntryId&&<><button className="table-link" onClick={()=>reverse(entry)}>Reverse</button><button className="table-link" onClick={()=>setCorrecting(entry)}>Correct</button></>}</span></td></tr>)}</tbody></table></div></section>{correcting&&<CorrectionForm entry={correcting} accounts={accounts} onClose={()=>setCorrecting(null)} onSaved={onChanged}/>}</>;
}

function PeriodList({periods,onChanged}:{periods:AccountingPeriod[];onChanged:()=>Promise<void>}){
  const mutation=useMutation();
  const createCurrent=async()=>{const fy=currentFinancialYear();const start=Number(fy.slice(0,4));await mutation.run(async()=>{await postJSON('/api/admin/accounting/periods',{financialYear:fy,startDate:`${start}-04-01`,endDate:`${start+1}-03-31`});await onChanged()})};
  const close=async(period:AccountingPeriod)=>{const reason=window.prompt(`Reason for closing ${periodLabel(period)}:`);if(!reason?.trim())return;const authorization=window.prompt('Authorization reference (minutes/approval):');if(!authorization?.trim())return;if(!window.confirm(`Close ${periodLabel(period)}? New entries and postings will be rejected until an authorized reopen.`))return;await mutation.run(async()=>{await postJSON(`/api/admin/accounting/periods/${encodeURIComponent(period.id)}/close`,{reason,authorization});await onChanged()})};
  const reopen=async(period:AccountingPeriod)=>{const reason=window.prompt(`Reason for reopening ${periodLabel(period)}:`);if(!reason?.trim())return;const authorization=window.prompt('Authorization reference (minutes/approval):');if(!authorization?.trim())return;if(!window.confirm(`Reopen ${periodLabel(period)}?`))return;await mutation.run(async()=>{await postJSON(`/api/admin/accounting/periods/${encodeURIComponent(period.id)}/reopen`,{reason,authorization});await onChanged()})};
  return <section className="admin-panel"><div className="panel-head"><div><span>PERIOD CONTROL</span><h3>Financial-year close</h3></div><button className="admin-primary" onClick={createCurrent}>+ Create current FY period</button></div><p className="module-note">Closing requires all journal entries to be posted and balanced. Reopening always records a reason and authorization reference in the append-only audit log.</p><MutationNotice {...mutation}/><div className="accounting-period-grid">{periods.length===0?<div className="public-empty-state">No accounting periods exist yet.</div>:periods.map(period=><article className="accounting-period-card" key={period.id}><div><span>{period.status}</span><h4>{periodLabel(period)}</h4><small>{period.startDate} → {period.endDate}</small></div><p>{period.status==='Closed'?period.closeReason||'Closed with recorded authorization.':'Open for controlled draft and posted journal activity.'}</p><div className="event-modal-actions">{period.status==='Open'?<button className="admin-primary" onClick={()=>close(period)}>Close period</button>:<button onClick={()=>reopen(period)}>Reopen with authorization</button>}</div></article>)}</div></section>;
}

function AuditList({events}:{events:AuditEventRecord[]}){
  return <section className="admin-panel"><div className="panel-head"><div><span>APPEND-ONLY AUDIT LOG</span><h3>Accounting actions</h3></div><strong>{events.length} recent events</strong></div><p className="module-note">This log records normalized accounting actions, actors, reasons and authorization references. It is separate from the historic Tally ledger activity view.</p><div className="admin-data-table-wrap"><table className="admin-data-table"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Reason</th><th>Authorization</th></tr></thead><tbody>{events.length===0?<tr><td colSpan={6}>No normalized accounting actions recorded yet.</td></tr>:events.map(event=><tr key={event.id}><td>{new Date(event.occurredAt).toLocaleString('en-IN')}</td><td>{event.actorUsername}</td><td>{event.action}</td><td>{event.entityType} • {event.entityId}</td><td>{event.reason||'—'}</td><td>{event.authorization||'—'}</td></tr>)}</tbody></table></div></section>;
}

function AccountList({accounts}:{accounts:AccountingAccount[]}){
  return <section className="admin-panel"><div className="panel-head"><div><span>CHART OF ACCOUNTS</span><h3>Posting accounts</h3></div><strong>{accounts.length} accounts</strong></div><p className="module-note">The chart of accounts is the controlled target for future balanced journal posting. Existing Tally collection rows are not silently converted.</p><div className="admin-data-table-wrap"><table className="admin-data-table"><thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Status</th></tr></thead><tbody>{accounts.map(account=><tr key={account.id}><td>{account.code}</td><td>{account.name}</td><td>{account.accountType}</td><td>{account.active?'Active':'Inactive'}</td></tr>)}</tbody></table></div></section>;
}

export default function AccountingControls(){
  const[tab,setTab]=useState<AccountingTab>('journal');
  const[data,setData]=useState<AccountingState>({accounts:[],periods:[],entries:[],audit:[]});
  const[loading,setLoading]=useState(true);
  const[error,setError]=useState('');
  const load=async()=>{setLoading(true);setError('');try{setData(await loadAccounting())}catch(error){setError(errorMessage(error))}finally{setLoading(false)}};
  useEffect(()=>{void load()},[]);
  const content=useMemo(()=>{
    if(tab==='periods')return <PeriodList periods={data.periods} onChanged={load}/>;
    if(tab==='audit')return <AuditList events={data.audit}/>;
    if(tab==='accounts')return <AccountList accounts={data.accounts}/>;
    return <><JournalForm accounts={data.accounts} onSaved={load}/><JournalList entries={data.entries} accounts={data.accounts} onChanged={load}/></>;
  },[data,tab]);
  return <section className="admin-module-stack accounting-controls"><section className="admin-panel"><div className="panel-head"><div><span>NORMALIZED ACCOUNTING</span><h3>Journal, audit & period controls</h3></div><button onClick={()=>void load()} disabled={loading}>{loading?'Refreshing…':'Refresh accounting data'}</button></div><p className="module-note">This controlled accounting layer is separate from the imported Tally history. Use it for new verified postings and corrections; do not fabricate journals for historic rows without committee approval.</p><div className="accounting-tabs" role="tablist"><button className={tab==='journal'?'active':''} onClick={()=>setTab('journal')}>Journal</button><button className={tab==='periods'?'active':''} onClick={()=>setTab('periods')}>Periods</button><button className={tab==='audit'?'active':''} onClick={()=>setTab('audit')}>Audit log</button><button className={tab==='accounts'?'active':''} onClick={()=>setTab('accounts')}>Chart of accounts</button></div>{error&&<div className="login-error" role="alert">Accounting controls are unavailable. {error}<br/><small>Apply the accounting migration before using this panel in Cloudflare.</small></div>}</section>{!error&&content}</section>;
}
