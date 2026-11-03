import {useEffect,useState} from 'react';
import {apiRequest,errorMessage} from './api';
import type {AuthSecuritySummary} from './portalTypes';

function formatTime(value:string|null){
  return value?new Date(value).toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'}):'None in the monitoring window';
}

function windowLabel(seconds:number){
  const minutes=Math.round(seconds/60);
  return minutes===1?'1 minute':`${minutes} minutes`;
}

export default function SecurityMonitor(){
  const[data,setData]=useState<AuthSecuritySummary|null>(null);
  const[loading,setLoading]=useState(true);
  const[error,setError]=useState('');
  const load=async()=>{
    setLoading(true);setError('');
    try{setData(await apiRequest<AuthSecuritySummary>('/api/admin/security/auth-attempts'))}
    catch(reason){setError(errorMessage(reason))}
    finally{setLoading(false)}
  };
  useEffect(()=>{
    void load();
    const timer=window.setInterval(()=>void load(),60_000);
    return()=>window.clearInterval(timer);
  },[]);
  return <section className="admin-module-stack security-monitor">
    <section className="admin-panel">
      <div className="panel-head"><div><span>SECURITY MONITORING</span><h3>Authentication activity</h3></div><button onClick={()=>void load()} disabled={loading}>{loading?'Refreshing…':'Refresh now'}</button></div>
      <p className="module-note">This view shows aggregate authentication activity for the last {data?windowLabel(data.windowSeconds):'configured monitoring window'}. It intentionally omits usernames, IP addresses, account keys and passwords.</p>
      {error&&<div className="login-error" role="alert">Authentication monitoring is unavailable. {error}</div>}
      {!error&&!data&&<div className="public-empty-state" role="status">{loading?'Loading authentication activity…':'No monitoring data returned.'}</div>}
      {data&&<>
        <div className="security-summary-grid">
          <div className="security-stat"><span>Failure checks</span><strong>{data.failureCount}</strong><small>Failed or later cleared</small></div>
          <div className="security-stat"><span>Active failures</span><strong>{data.activeFailureCount}</strong><small>Still counted against an account</small></div>
          <div className="security-stat"><span>Successful sign-ins</span><strong>{data.succeededCount}</strong><small>Within the same window</small></div>
          <div className="security-stat"><span>Alert threshold</span><strong>{data.failureAlertThreshold}</strong><small>Failure checks in {windowLabel(data.windowSeconds)}</small></div>
        </div>
        <div className={'security-alert'+(data.alert?' active':'')} role={data.alert?'alert':'status'}>
          <strong>{data.alert?'Review authentication activity':'No threshold alert'}</strong>
          <span>{data.alert?`${data.failureCount} failure checks reached the configured threshold. Review the deployment and account access if this was unexpected.`:`The failure count is below the configured threshold. Last failure: ${formatTime(data.lastFailureAt)}.`}</span>
        </div>
        <div className="security-recent">
          <div className="panel-head"><div><span>RECENT EVENTS</span><h3>Failure timestamps</h3></div><small>Last {data.recentFailures.length} recorded</small></div>
          {data.recentFailures.length?<div className="security-event-list">{data.recentFailures.map((event,index)=><div key={`${event.attemptedAt}-${index}`}><span className={'security-event-dot '+(event.outcome==='failed'?'active':'cleared')}/><div><strong>{event.outcome==='failed'?'Authentication failure':'Failure cleared after a successful sign-in'}</strong><small>{formatTime(event.attemptedAt)}</small></div></div>)}</div>:<p className="module-note">No failed authentication checks were recorded in the monitoring window.</p>}
        </div>
      </>}
    </section>
  </section>;
}
