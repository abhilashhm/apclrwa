import {useRef,useState} from 'react';
import {errorMessage} from './api';

export function useMutation() {
  const lock=useRef(false);
  const[saving,setSaving]=useState(false);
  const[error,setError]=useState('');
  const run=async(action:()=>Promise<unknown>):Promise<boolean>=>{
    if(lock.current)return false;
    lock.current=true;setSaving(true);setError('');
    try {await action();return true}
    catch(err) {setError(errorMessage(err));return false}
    finally {lock.current=false;setSaving(false)}
  };
  return {saving,error,run};
}

export function MutationNotice({saving,error}:{saving:boolean;error:string}) {
  return <>{saving&&<p className="module-note" role="status">Saving to the shared server…</p>}{error&&<div className="login-error" role="alert">{error}</div>}</>;
}
