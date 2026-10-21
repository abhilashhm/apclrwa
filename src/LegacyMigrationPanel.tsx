import {useEffect,useRef,useState,type ChangeEvent} from 'react';
import {cleanupImportedLegacy,detectLegacyKeys,readLegacyForPreview,type LegacySource} from './legacyMigration';
import {applyTallyImport,importMigration,previewMigration,uploadTallyImport} from './portalStore';
import type {MigrationPreview} from './portalTypes';
import {MutationNotice,useMutation} from './useMutation';

export default function LegacyMigrationPanel() {
  const[detection,setDetection]=useState(()=>detectLegacyKeys());
  const[source,setSource]=useState<LegacySource|null>(null);
  const[preview,setPreview]=useState<MigrationPreview|null>(null);
  const[imported,setImported]=useState(false);
  const[message,setMessage]=useState('');
  const[messageTone,setMessageTone]=useState<'success'|'info'|'error'>('success');
  const tallyFileInput=useRef<HTMLInputElement>(null);
  const mutation=useMutation();
  const notify=(text:string,tone:'success'|'info'|'error'='success')=>{setMessage(text);setMessageTone(tone)};
  const inspect=async()=>{
    setPreview(null);setSource(null);setImported(false);notify('');
    await mutation.run(async()=>{
      const data=await readLegacyForPreview();
      if(!Object.keys(data.collections).length)throw new Error('No supported legacy collections were found in this browser.');
      const result=await previewMigration(data.collections);
      setSource(data);setPreview(result);
    });
  };
  const confirmImport=async()=>{
    if(!source||!preview||!window.confirm('Import these validated collections into the shared server? Existing records are preserved and conflicts are rejected. Browser originals will remain until you explicitly clean them up.'))return;
    if(await mutation.run(()=>importMigration(source.collections,preview.revision))) {
       setImported(true);notify('Import persisted successfully. The server created a backup; the browser originals have been preserved.');
    }
  };
  const cleanup=async()=>{
    if(!source||!imported||!window.confirm('PERMANENTLY DELETE the imported legacy collections from this browser, including any legacy plaintext passwords? Verify the shared server data first. A server backup was created during import. This cleanup cannot be undone in this browser. Changed data will be retained.'))return;
    await mutation.run(async()=>{
      const result=await cleanupImportedLegacy(source);
       notify(`Removed ${result.removed} imported browser collections. ${result.changed?`${result.changed} changed collections were retained; preview and import them separately.`:'The shared server data and its backup are retained.'}`);
      setDetection(detectLegacyKeys());setSource(null);setPreview(null);setImported(false);
    });
  };
  const tally=async()=>{
    if(!window.confirm('Apply the configured Tally snapshot to the shared server now? The server will validate and deduplicate the import.'))return;
    notify('');
    if(await mutation.run(()=>applyTallyImport()))notify('Tally import persisted successfully on the shared server.');
  };
  const cancelTallyUpload=()=>{if(!mutation.saving)notify('Tally upload cancelled. No file was sent.','info')};
  useEffect(()=>{
    const input=tallyFileInput.current;
    if(!input)return;
    input.addEventListener('cancel',cancelTallyUpload);
    return()=>input.removeEventListener('cancel',cancelTallyUpload);
  },[mutation.saving]);
  const uploadTallyFile=async(event:ChangeEvent<HTMLInputElement>)=>{
    const file=event.target.files?.[0];
    event.target.value='';
    if(!file){cancelTallyUpload();return}
    notify('');
    let parsed:unknown;
    try {parsed=JSON.parse((await file.text()).replace(/^\uFEFF/,''))}
    catch {notify('The selected Tally file is not valid JSON. Choose the existing JSON snapshot and try again.','error');return}
    let returnedRevision:number|undefined;
    if(await mutation.run(async()=>{const returned=await uploadTallyImport(parsed);returnedRevision=returned.revision}))notify(`Tally snapshot uploaded successfully to Cloudflare. Shared portal revision: ${returnedRevision}.`);
  };
  return <section className="admin-module-stack">
    <section className="admin-panel"><div className="panel-head"><div><span>EXPLICIT DATA MIGRATION</span><h3>Legacy browser data</h3></div></div>
      <p className="module-note">The portal now uses shared server data. Detection checks key names only. Preview explicitly reads the legacy collections, strips all password fields, and sends the remaining data to the server for validation. Legacy passwords are never copied into accounts; the committee must provision or reset resident logins.</p>
      <p>{detection.supported.length?`Detected collections: ${detection.supported.join(', ')}.`:'No supported legacy keys detected in this browser.'}</p>
      {detection.error&&<div className="login-error" role="alert">{detection.error}</div>}
      {detection.skipped>0&&<p className="module-note">Legacy Tally reconciliation metadata is retained locally and excluded from migration. Use the explicit server Tally import below.</p>}
      {preview&&<><h4>Validated preview</h4><ul>{Object.entries(preview.counts).map(([name,count])=><li key={name}>{name}: {count}</li>)}</ul>{preview.warnings.length>0&&<div className="login-error" role="status"><strong>Validation warnings</strong><ul>{preview.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></div>}<p className="module-note">Server revision: {preview.revision}. Review the counts and warnings before confirming.</p></>}
       <MutationNotice {...mutation}/>{message&&<p className={messageTone==='error'?'login-error':messageTone==='info'?'module-note':'account-good'} role={messageTone==='error'?'alert':'status'}>{message}</p>}
      <div className="event-modal-actions"><button disabled={mutation.saving} onClick={()=>setDetection(detectLegacyKeys())}>Check legacy keys</button><button className="admin-primary" disabled={mutation.saving||!detection.supported.length} onClick={inspect}>Preview legacy import</button>{preview&&!imported&&<button className="admin-primary" disabled={mutation.saving} onClick={confirmImport}>Confirm server import</button>}</div>
      {imported&&<div className="legacy-cleanup-warning"><p><strong>Permanent browser cleanup</strong> — verify the imported server records before deleting originals. The import created a server backup. This removes the imported legacy collections, including any old passwords, from this browser only.</p><button className="danger-link" disabled={mutation.saving} onClick={cleanup}>Permanently remove imported browser originals</button></div>}
    </section>
      <section className="admin-panel"><div className="panel-head"><div><span>SERVER IMPORT</span><h3>Tally snapshot</h3></div><div style={{display:'flex',gap:'8px',flexWrap:'wrap',justifyContent:'flex-end'}}><button type="button" className="admin-primary" disabled={mutation.saving} onClick={tally}>Apply Tally import</button><button type="button" className="admin-primary" disabled={mutation.saving} onClick={()=>tallyFileInput.current?.click()}>Upload JSON to Cloudflare</button><input ref={tallyFileInput} type="file" accept="application/json,.json" aria-label="Choose Tally JSON snapshot" hidden disabled={mutation.saving} onChange={uploadTallyFile}/></div></div><p className="module-note">Apply Tally import uses the configured local-server snapshot. Upload JSON to Cloudflare sends the selected snapshot as application/json with the current portal revision. To reach Cloudflare, use this action from the deployed Worker URL; localhost targets the local API.</p></section>
  </section>;
}
