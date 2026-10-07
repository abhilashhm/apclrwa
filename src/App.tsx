import {FormEvent, useEffect, useState, type CSSProperties, type ReactNode} from 'react';
import QRCode from 'qrcode';

type View = 'home' | 'login' | 'admin' | 'resident';
type LoginRole = 'resident' | 'committee';

type EventItem = {
  id: string;
  tag: string;
  title: string;
  text: string;
  date: string;
  location: string;
};

const highlights=[
  {icon:'🏡',title:'A connected neighbourhood',text:'A common digital home for residents, families and the association committee.'},
  {icon:'📣',title:'Updates that matter',text:'Keep up with notices, community events, announcements and important dates.'},
  {icon:'🧾',title:'Clear & transparent',text:'Make association finances and resident records easier to understand and access.'}
];

const defaultEvents:EventItem[]=[
  {id:'welcome',tag:'COMMUNITY',title:'Welcome to the new APCLAYOUT community portal',text:'A digital space is being created to make everyday RWA communication and services simpler.',date:'Coming soon',location:'APC Layout'},
  {id:'events',tag:'EVENTS',title:'Community events & activities',text:'Festival celebrations, competitions and neighbourhood activities will have a dedicated home here.',date:'Stay tuned',location:'APC Layout'},
  {id:'transparency',tag:'TRANSPARENCY',title:'Association accounts',text:'Resident-facing financial information will be presented clearly as the accounting portal rolls out.',date:'In progress',location:'APCLRWA'}
];

const DEMO_ADMIN={username:'committee.admin',password:'APC@Admin2026'};
const DEMO_RESIDENT={username:'9876543210',password:'APC@Resident2026'};
const WHATSAPP_CHANNEL='https://chat.whatsapp.com/CrlHi969JB80mL1Ap81b57?s=cl&p=a&mlu=4&iam=0';

const financialYears=['2026–27','2025–26','2024–25'];
const fyStats:Record<string,string[][]>={
  '2026–27':[['₹ 4.86L','Maintenance collected'],['₹ 1.24L','Outstanding maintenance'],['₹ 68,500','Festival collections'],['₹ 2.17L','Current bank balance']],
  '2025–26':[['₹ 5.42L','Maintenance collected'],['₹ 92,000','Outstanding maintenance'],['₹ 1.18L','Festival collections'],['₹ 1.94L','Closing bank balance']],
  '2024–25':[['₹ 4.97L','Maintenance collected'],['₹ 76,500','Outstanding maintenance'],['₹ 86,200','Festival collections'],['₹ 1.62L','Closing bank balance']]
};

const officeBearers=[
{name:'Sh. K Bhaskarachar',display:'Sri. K Bhaskarachar',role:'President',phone:''},
{name:'Sh. Mahesh Krishnamurthy',display:'Sri. Mahesh Krishnamurthy',role:'General Secretary',phone:''},
{name:'Sh. Krishna Rao',display:'Sri. Krishna Rao',role:'Vice President 1',phone:''},
{name:'Smt. Roopa Rakesh',display:'Smt. Roopa Rakesh',role:'Vice President 2',phone:''},
{name:'Sh. Elangovan',display:'Sri. Elangovan',role:'Joint Secretary 1',phone:''},
{name:'Sh. Sunil Ghorpade',display:'Sri. Sunil Ghorpade',role:'Joint Secretary 2',phone:''},
{name:'Sh. Manjunath B K',display:'Sri. Manjunath B K',role:'Organising Secretary',phone:''},
{name:'Smt. Sowjanya',display:'Smt. Sowjanya',role:'Assistant Secretary',phone:''},
{name:'Sh. Abhilash',display:'Sri. Abhilash',role:'Treasurer',phone:''},
{name:'Sh. Mahesh More',display:'Sri. Mahesh More',role:'Office Secretary',phone:''},
{name:'Sh. Srihari',display:'Sri. Srihari',role:'Executive Committee Member',phone:''},
{name:'Sh. Nagesh Kumble',display:'Sri. Nagesh Kumble',role:'Executive Committee Member',phone:''},
{name:'Sh. Vasudev',display:'Sri. Vasudev',role:'Executive Committee Member',phone:''},
{name:'Sh. Vikranth Gowda',display:'Sri. Vikranth Gowda',role:'Executive Committee Member',phone:''},
{name:'Sh. Rakesh Naidu',display:'Sri. Rakesh Naidu',role:'Executive Committee Member',phone:''}
];

function Logo({className='' }:{className?:string}){return <img className={className} src="./logo.svg" alt="APC Layout Residents Welfare Association logo"/>}

function ThemeToggle(){
  const[dark,setDark]=useState(()=>localStorage.getItem('apclrwa_theme')==='dark');
  useEffect(()=>{
    const apply=(value:boolean)=>{setDark(value);document.documentElement.dataset.theme=value?'dark':'light'};
    apply(localStorage.getItem('apclrwa_theme')==='dark');
    const sync=(e:Event)=>apply((e as CustomEvent<boolean>).detail);
    window.addEventListener('apclrwa-theme-change',sync);
    return()=>window.removeEventListener('apclrwa-theme-change',sync);
  },[]);
  const toggle=()=>{const next=!dark;localStorage.setItem('apclrwa_theme',next?'dark':'light');document.documentElement.dataset.theme=next?'dark':'light';window.dispatchEvent(new CustomEvent('apclrwa-theme-change',{detail:next}))};
  return <button className="theme-toggle" onClick={toggle} aria-label={dark?'Switch to light mode':'Switch to dark mode'} title={dark?'Light mode':'Dark mode'}>{dark?'☀':'☾'}</button>;
}

function OfficeBearerPhoto({index}:{index:number}){return <div className="ob-photo-placeholder"><span>PHOTO</span><small>Image {index+1}</small></div>}

function OfficeBearerContact({phone}:{phone:string}){
  return phone
    ? <a className="ob-phone" href={`tel:${phone.replace(/\\s/g,'')}`}>☎ {phone}</a>
    : <span className="ob-phone pending">Phone number to be added</span>;
}

function OfficeBearers(){
  const[open,setOpen]=useState(false);
  return <section className="office-bearers"><div className="container">
    <div className="section-heading ob-heading"><div className="eyebrow">OUR ASSOCIATION</div><h2>APCLRWA <em>Office Bearers</em></h2><p>Meet the association office bearers serving APC Layout. The complete list is available below.</p></div>
    <div className="ob-feature-grid">{officeBearers.slice(0,2).map((person,i)=><article className="ob-card featured" key={person.name}><OfficeBearerPhoto index={i}/><div className="ob-info"><h3>{person.display}</h3><p>{person.role}</p><OfficeBearerContact phone={person.phone}/></div></article>)}</div>
    <button className="button primary ob-see-all" onClick={()=>setOpen(true)}>View complete OB list <span>→</span></button>
  </div>
  {open&&<div className="ob-modal-backdrop" role="dialog" aria-modal="true" onMouseDown={e=>{if(e.target===e.currentTarget)setOpen(false)}}><div className="ob-modal">
    <div className="ob-modal-head"><div><div className="eyebrow">APCLRWA 2025–2027</div><h2>Office Bearers</h2></div><button className="ob-close" onClick={()=>setOpen(false)}>×</button></div>
    <div className="ob-modal-grid">{officeBearers.map((person,i)=><article className="ob-card" key={person.name}><OfficeBearerPhoto index={i}/><div className="ob-info"><h3>{person.display}</h3><p>{person.role}</p><OfficeBearerContact phone={person.phone}/></div></article>)}</div>
  </div></div>}
</section>;
}

function WhatsAppButton({className=''}:{className?:string}){
  return <a className={`whatsapp-button ${className}`} href={WHATSAPP_CHANNEL} target="_blank" rel="noreferrer"><span>◉</span> Join our WhatsApp channel <b>↗</b></a>;
}

function Home({go}:{go:(view:View)=>void}){
  const[menuOpen,setMenuOpen]=useState(false);
  const[events,setEvents]=useState<EventItem[]>(()=>{try{return JSON.parse(localStorage.getItem('apclrwa_events')||'')||defaultEvents}catch{return defaultEvents}});
  const scrollTo=(id:string)=>{document.getElementById(id)?.scrollIntoView({behavior:'smooth'});setMenuOpen(false)};
  useEffect(()=>{const onStorage=()=>{try{const saved=JSON.parse(localStorage.getItem('apclrwa_events')||'');if(Array.isArray(saved))setEvents(saved)}catch{}};window.addEventListener('storage',onStorage);return()=>window.removeEventListener('storage',onStorage)},[]);
  return <div className="site-shell">
    <div className="top-strip"><div className="container top-strip-inner"><span>APC Layout • Thindlu • Bengaluru – 560097</span><span className="top-strip-note">Building a better-connected community</span></div></div>
    <header className="navbar"><div className="container nav-inner">
      <button className="brand" onClick={()=>scrollTo('home')} aria-label="APC Layout home"><Logo/><span className="brand-copy"><strong>APC LAYOUT</strong><small>Residents Welfare Association</small></span></button>
      <button className="menu-toggle" aria-label={menuOpen?'Close navigation':'Open navigation'} aria-expanded={menuOpen} onClick={()=>setMenuOpen(!menuOpen)}><span/><span/><span/></button>
      <nav className={menuOpen?'nav-links open':'nav-links'} aria-label="Primary navigation">
        <button onClick={()=>scrollTo('home')}>Home</button><button onClick={()=>scrollTo('community')}>Our Community</button><button onClick={()=>scrollTo('updates')}>Updates</button><button onClick={()=>scrollTo('transparency')}>Transparency</button>
        <ThemeToggle/><a href={WHATSAPP_CHANNEL} target="_blank" rel="noreferrer" className="nav-whatsapp">WhatsApp</a><button className="nav-login" onClick={()=>go('login')}>Resident / Committee Login</button>
      </nav>
    </div></header>
    <main>
      <section id="home" className="hero"><div className="hero-glow glow-one"/><div className="hero-glow glow-two"/><div className="container hero-grid">
        <div className="hero-copy"><div className="eyebrow"><span className="eyebrow-dot"/> OUR COMMUNITY, OUR HOME</div><h1>One neighbourhood.<br/><em>One connected community.</em></h1>
          <p className="hero-lead">Welcome to the digital home of APC Layout Residents Welfare Association. Stay informed, participate in community life and access association services from one place.</p>
          <div className="hero-actions"><button className="button primary" onClick={()=>go('login')}>Open Portal <span>→</span></button><WhatsAppButton/><button className="button secondary" onClick={()=>scrollTo('community')}>Explore our community</button></div>
          <div className="trust-row"><span>✓ Community-first</span><span>✓ Transparent</span><span>✓ Resident-friendly</span></div>
        </div>
        <div className="hero-card-wrap" aria-label="Community welcome"><div className="hero-card"><div className="hero-card-art"><div className="sun"/><div className="cloud cloud-a"/><div className="cloud cloud-b"/><div className="hill hill-back"/><div className="hill hill-front"/><div className="road"/><div className="tree tree-left"><i/><b/><b/><b/></div><div className="tree tree-right"><i/><b/><b/><b/></div><div className="home-shape"><span className="roof"/><span className="house-body"/><span className="door"/><span className="window"/></div></div><div className="hero-card-caption"><span className="mini-mark">APC</span><div><strong>Welcome home.</strong><small>APC Layout, Thindlu</small></div></div></div><div className="floating-note note-one"><span>✦</span><div><strong>Community updates</strong><small>All in one place</small></div></div><div className="floating-note note-two"><span>₹</span><div><strong>Financial clarity</strong><small>Designed for trust</small></div></div></div>
      </div></section>

      <OfficeBearers/>

      <section id="community" className="section community"><div className="container"><div className="section-heading"><div className="eyebrow">WHY THIS PORTAL</div><h2>Made for the people<br/><em>who make APC Layout home.</em></h2><p>Simple, useful and community-focused — the portal will grow around the everyday needs of our residents.</p></div><div className="highlight-grid">{highlights.map(item=><article className="highlight-card" key={item.title}><div className="highlight-icon">{item.icon}</div><h3>{item.title}</h3><p>{item.text}</p><span className="card-arrow">↗</span></article>)}</div></div></section>

      <section id="updates" className="section updates"><div className="container"><div className="section-heading row-heading"><div><div className="eyebrow">FROM THE ASSOCIATION</div><h2>Latest <em>updates</em></h2></div><WhatsAppButton/></div><EventMarquee events={events}/></div></section>

      <section id="transparency" className="section transparency"><div className="container transparency-grid"><div><div className="eyebrow light">BUILT AROUND TRUST</div><h2>Association matters should be <em>clear.</em></h2><p>From maintenance collections to community expenses, the resident portal is designed to make association information easier to access, understand and audit.</p><div className="check-list"><div><span>✓</span> Resident payment history & receipts</div><div><span>✓</span> Maintenance outstanding visibility</div><div><span>✓</span> Community collection transparency</div><div><span>✓</span> Reports designed for annual audit</div></div></div><div className="ledger-card"><div className="ledger-head"><span>ASSOCIATION SNAPSHOT</span><span className="status-dot">● LIVE DESIGN</span></div><div className="ledger-row"><span>Maintenance</span><strong>Track collections</strong></div><div className="ledger-row"><span>Community funds</span><strong>Trace every rupee</strong></div><div className="ledger-row"><span>Expenses</span><strong>Record with vouchers</strong></div><div className="ledger-row"><span>Audit</span><strong>Ready when needed</strong></div><div className="ledger-foot">Transparency is a feature, not an afterthought.</div></div></div></section>
      <section className="portal-cta"><div className="container portal-card"><div className="portal-mark">APC</div><div><div className="eyebrow">PORTAL ACCESS</div><h2>Your community services, <em>one login away.</em></h2><p>Residents can view their association information and receipts. Committee members can manage collections, expenses, events and reports.</p></div><button className="button dark" onClick={()=>go('login')}>Sign in <span>→</span></button></div></section>
      <section className="office-map"><div className="container">
        <div className="section-heading map-heading"><div className="eyebrow">VISIT US</div><h2>APCLRWA <em>Office</em></h2><p>Find the RWA office on the map.</p></div>
        <div className="map-card"><iframe title="APCLRWA Office location" src="https://www.google.com/maps?q=13.067835919104075,77.56607799194407&z=17&output=embed" loading="lazy" referrerPolicy="no-referrer-when-downgrade"></iframe><div className="map-caption"><div><strong>APC Layout Residents Welfare Association</strong><span>APC Layout, Thindlu, Bengaluru – 560097</span></div><a className="directions-button" href="https://www.google.com/maps/dir/?api=1&destination=13.067835919104075,77.56607799194407" target="_blank" rel="noreferrer">Get directions <b>↗</b></a></div></div>
      </div></section>
    </main>
    <Footer go={go} scrollTo={scrollTo}/>
  </div>
}

function EventMarquee({events}:{events:EventItem[]}){
  const[count,setCount]=useState(0);
  const total=events.length;
  useEffect(()=>{
    if(total<=3){setCount(0);return}
    const timer=window.setInterval(()=>setCount(v=>(v+1)%total),4200);
    return()=>window.clearInterval(timer);
  },[total]);
  if(!total)return <div className="events-empty">No updates published yet.</div>;
  const looped=[...events,...events.slice(0,2)];
  return <div className="event-marquee">
    <div className="event-marquee-window">
      <div className="event-marquee-track" style={{'--event-total':looped.length,'--event-index':count} as CSSProperties}>
        {looped.map((item,i)=><article className="update-card event-slide" key={item.id+'-'+i}><div className="update-meta"><span>{item.tag}</span><time>{item.date}</time></div><h3>{item.title}</h3><p>{item.text}</p><div className="event-location">⌖ {item.location}</div></article>)}
      </div>
    </div>
    {total>3&&<div className="event-marquee-dots">{events.map((item,i)=><button key={item.id} className={i===count?'active':''} onClick={()=>setCount(i)} aria-label={`Show event ${i+1}`}/>)}</div>}
  </div>
}

function Footer({go,scrollTo}:{go:(v:View)=>void;scrollTo:(id:string)=>void}){
 return <footer className="footer"><div className="container footer-grid"><div className="footer-brand"><Logo/><div><strong>APC LAYOUT RESIDENTS<br/>WELFARE ASSOCIATION</strong><p>APC Layout, Thindlu<br/>Bengaluru – 560097</p><WhatsAppButton/></div></div><div className="footer-links"><strong>Community</strong><button onClick={()=>scrollTo('community')}>Our Community</button><button onClick={()=>scrollTo('updates')}>Updates</button><button onClick={()=>scrollTo('transparency')}>Transparency</button></div><div className="footer-links"><strong>Portal</strong><button onClick={()=>go('login')}>Resident Login</button><button onClick={()=>go('login')}>Committee Login</button><button onClick={()=>go('login')}>Help & Support</button></div></div><div className="container footer-bottom"><span>© {new Date().getFullYear()} APC Layout Residents Welfare Association</span><span>Built for our community, with care.</span></div></footer>
}

function Login({onBack,onLogin,onResidentLogin}:{onBack:()=>void;onLogin:()=>void;onResidentLogin:(username:string)=>void}){const[role,setRole]=useState<LoginRole>('resident');const[username,setUsername]=useState('');const[password,setPassword]=useState('');const[show,setShow]=useState(false);const[error,setError]=useState('');const submit=(e:FormEvent)=>{e.preventDefault();setError('');if(role==='committee'&&username===DEMO_ADMIN.username&&password===DEMO_ADMIN.password){localStorage.setItem('apclrwa_admin_session','true');onLogin();return}if(role==='resident'){const r=getResidents().find(x=>x.mobile===username.trim()&&x.password===password&&x.active!==false);if(r){localStorage.setItem('apclrwa_resident_session','true');onResidentLogin(r.mobile);return}}setError('Invalid credentials. Use your registered phone number and password.')};return <div className="auth-page"><button className="auth-back" onClick={onBack}>← Back to website</button><div className="auth-card resident-auth-card"><div className="auth-brand"><Logo/><div><strong>APC LAYOUT</strong><span>Residents Welfare Association</span></div></div><div className="auth-heading"><div className="eyebrow">SECURE COMMUNITY PORTAL</div><h1>Welcome <em>home.</em></h1><p>Sign in to view your association information, payment history, receipts and community updates.</p></div><div className="role-switch"><button type="button" className={role==='resident'?'active':''} onClick={()=>setRole('resident')}>Resident</button><button type="button" className={role==='committee'?'active':''} onClick={()=>setRole('committee')}>Committee</button></div><form className="login-form" onSubmit={submit}><label>{role==='committee'?'Committee username':'Registered phone number'}<input value={username} onChange={e=>setUsername(e.target.value)} placeholder={role==='committee'?'committee.admin':'98XXXXXXXX'} required/></label><label>Password<div className="password-wrap"><input type={show?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} required/><button type="button" onClick={()=>setShow(!show)}>{show?'Hide':'Show'}</button></div></label>{error&&<div className="login-error">{error}</div>}<button className="login-submit" type="submit">Sign in as {role==='committee'?'Committee Admin':'Resident'} <span>→</span></button></form>{role==='committee'?<div className="demo-credentials"><strong>Demo committee admin</strong><span>Username: <b>committee.admin</b></span><span>Password: <b>APC@Admin2026</b></span></div>:<div className="demo-credentials"><strong>Demo resident</strong><span>Phone: <b>{DEMO_RESIDENT.username}</b></span><span>Password: <b>{DEMO_RESIDENT.password}</b></span></div>}<div className="auth-footer">APC Layout, Thindlu • Bengaluru – 560097</div></div></div>}

const UPI_1000='upi://pay?pa=1584602006555@cnrb&pn=A P C LAYOUT RESIDENTS WELFARE ASSN&mc=8699&tr=1234567887654321&tn=Pay to Merchant&am=1000&mam=0&cu=INR&refUrl=http://npci.org/upi/schema/';
const UPI_500='upi://pay?pa=1584602006555@cnrb&pn=A P C LAYOUT RESIDENTS WELFARE ASSN&mc=8699&tr=1234567887654321&tn=Pay to Merchant&am=500&mam=0&cu=INR&refUrl=http://npci.org/upi/schema/';
const UPI_CUSTOM='upi://pay?pa=1584602006555@cnrb&pn=A P C LAYOUT RESIDENTS WELFARE ASSN&mc=8699&tr=1234567887654321&tn=Pay to Merchant&am=0&mam=0&cu=INR&refUrl=http://npci.org/upi/schema/';
function getPendingPayments():any[]{try{return JSON.parse(localStorage.getItem('apclrwa_pending_payments')||'[]')}catch{return[]}}
function savePendingPayments(items:any[]){localStorage.setItem('apclrwa_pending_payments',JSON.stringify(items));window.dispatchEvent(new Event('apclrwa-payments-change'))}
function PaymentQR({type,amount,onClose}:{type:'membership'|'amc'|'contribution';amount:number;onClose:()=>void}){
 const[qr,setQr]=useState('');const[submitted,setSubmitted]=useState(false);
 const upi=type==='membership'?UPI_500:type==='amc'?UPI_1000:UPI_CUSTOM.replace('&am=0&','&am='+amount+'&');
 useEffect(()=>{QRCode.toDataURL(upi,{width:280,margin:2,errorCorrectionLevel:'M'}).then(setQr)},[upi]);
 const title=type==='membership'?'One-time membership fee':type==='amc'?'Annual maintenance charge':'Festival / community contribution';
 const submit=()=>{if(type!=='contribution')return;const items=getPendingPayments();items.push({id:'PAY-'+Date.now(),resident:'Demo Resident',house:'24',type:'Contribution',amount:'₹ '+amount.toLocaleString('en-IN'),date:new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}),status:'Pending verification'});savePendingPayments(items);setSubmitted(true)};
 return <div className="receipt-modal-backdrop"><div className="payment-qr-modal"><div className="receipt-head"><div><span>UPI PAYMENT</span><h3>{title}</h3></div><button onClick={onClose}>×</button></div><div className="payment-qr-body">{qr?<img className="upi-qr" src={qr} alt="UPI payment QR code"/>:<div>Generating QR…</div>}<strong>₹ {amount.toLocaleString('en-IN')}</strong><small>Scan with any UPI app</small><div className="upi-id">1584602006555@cnrb</div><p>Once the payment is done, <b>post the payment screenshot in the WhatsApp group.</b></p>{type==='contribution'&&!submitted&&<button className="admin-primary" onClick={submit}>I have made the payment</button>}{submitted&&<div className="payment-pending-note">Payment marked <b>Pending verification</b>.</div>}<WhatsAppButton/></div></div></div>
}

const residentPayments=[
  {date:'28 Sep 2026',description:'Maintenance payment',receipt:'REC-00124',mode:'Bank transfer',amount:'₹ 8,500',status:'Paid'},
  {date:'30 Aug 2026',description:'Maintenance payment',receipt:'REC-00111',mode:'UPI',amount:'₹ 8,500',status:'Paid'},
  {date:'02 Aug 2026',description:'Ganesha festival donation',receipt:'REC-00119',mode:'UPI',amount:'₹ 2,000',status:'Paid'},
  {date:'05 Jul 2026',description:'Maintenance payment',receipt:'REC-00098',mode:'Cash',amount:'₹ 8,500',status:'Paid'}
];

const residentStatement=[
  {month:'Apr 2026',charge:'₹ 8,500',paid:'₹ 8,500',balance:'₹ 0'},
  {month:'May 2026',charge:'₹ 8,500',paid:'₹ 8,500',balance:'₹ 0'},
  {month:'Jun 2026',charge:'₹ 8,500',paid:'₹ 8,500',balance:'₹ 0'},
  {month:'Jul 2026',charge:'₹ 8,500',paid:'₹ 8,500',balance:'₹ 0'},
  {month:'Aug 2026',charge:'₹ 8,500',paid:'₹ 0',balance:'₹ 8,500'},
  {month:'Sep 2026',charge:'₹ 8,500',paid:'₹ 0',balance:'₹ 8,500'}
];

const residentContributions=[
  {name:'Gowri Ganesha Festival 2026',date:'18 Sep 2026',amount:'₹ 2,000',status:'Contributed'},
  {name:'Community Development Fund',date:'10 Apr 2026',amount:'₹ 1,500',status:'Contributed'}
];

const residentUpdates=[
  {tag:'EVENTS',title:'Gowri Ganesha Festival',text:'Festival celebrations, competitions, procession and maha prasada.',date:'18–20 Sep 2026'},
  {tag:'NOTICE',title:'Association office hours',text:'Committee support is available for resident account queries and receipts.',date:'Ongoing'},
  {tag:'COMMUNITY',title:'WhatsApp community channel',text:'Follow the association channel for timely updates and announcements.',date:'Ongoing'}
];

function DemoBadge(){return <span className="demo-badge">DEMO DATA</span>}

function ResidentSection({title,kicker,children,action}:{title:string;kicker:string;children:ReactNode;action?:ReactNode}){
 return <section className="resident-panel resident-section"><div className="panel-head"><div><span>{kicker}</span><h3>{title}</h3></div>{action}</div>{children}</section>
}

function ResidentPayments(){
 const[receipt,setReceipt]=useState<typeof residentPayments[number]|null>(null);
 return <ResidentSection kicker="PAYMENT HISTORY" title="Recent payments" action={<span className="resident-count">{residentPayments.length} records</span>}>
   <div className="resident-table-wrap"><table className="resident-table"><thead><tr><th>Date</th><th>Description</th><th>Receipt</th><th>Mode</th><th>Amount</th><th>Status</th><th/></tr></thead><tbody>{residentPayments.map(item=><tr key={item.receipt}><td>{item.date}</td><td><strong>{item.description}</strong></td><td>{item.receipt}</td><td>{item.mode}</td><td><strong>{item.amount}</strong></td><td><span className="status-pill paid">{item.status}</span></td><td><button className="table-link" onClick={()=>setReceipt(item)}>Receipt</button></td></tr>)}</tbody></table></div>
   {receipt&&<div className="receipt-modal-backdrop"><div className="receipt-card"><div className="receipt-head"><div><span>APCLRWA RECEIPT</span><h3>Payment receipt</h3></div><button onClick={()=>setReceipt(null)}>×</button></div><div className="receipt-logo"><Logo/><div><strong>APC Layout Residents Welfare Association</strong><small>APC Layout, Thindlu, Bengaluru – 560097</small></div></div><div className="receipt-number"><span>Receipt no.</span><strong>#{receipt.receipt}</strong></div><div className="receipt-details"><div><small>Resident</small><strong>Demo Resident</strong></div><div><small>Date</small><strong>{receipt.date}</strong></div><div><small>Payment for</small><strong>{receipt.description}</strong></div><div><small>Mode</small><strong>{receipt.mode}</strong></div><div><small>Amount</small><strong>{receipt.amount}</strong></div><div><small>Status</small><strong className="account-good">Paid</strong></div></div><div className="receipt-foot">This is a demonstration receipt. Final receipts will be generated from the accounting system.</div><div className="receipt-actions"><button onClick={()=>window.print()}>Print / Save PDF</button><button className="admin-primary" onClick={()=>setReceipt(null)}>Close</button></div></div></div>}
 </ResidentSection>
}

function ResidentStatement(){
 const[qr,setQr]=useState(false);
 return <ResidentSection kicker="ANNUAL MAINTENANCE" title="AMC • FY 2026–27" action={<span className="resident-count">₹ 1,000 once a year</span>}><div className="payment-due-card"><div><span>ANNUAL MAINTENANCE CHARGE</span><strong>₹ 1,000</strong><small>Due for FY 2026–27 • payable once per year</small></div><button className="admin-primary" onClick={()=>setQr(true)}>Pay AMC ₹1,000</button></div><div className="resident-summary-row"><div><span>AMC</span><strong>₹ 1,000</strong></div><div><span>Payment status</span><strong className="balance-due">Not paid</strong></div><div><span>Financial year</span><strong>FY 2026–27</strong></div></div>{qr&&<PaymentQR type="amc" amount={1000} onClose={()=>setQr(false)}/>}</ResidentSection>
}

function ResidentContributions(){
 const[amount,setAmount]=useState('');const[qr,setQr]=useState(false);const value=Number(amount);
 return <ResidentSection kicker="COMMUNITY FUNDS" title="Festival & community contributions" action={<span className="resident-count">Optional • any amount</span>}><div className="contribution-pay-card"><div><span>MAKE A CONTRIBUTION</span><h4>Support community activities</h4><p>Enter any amount you wish to contribute. After payment, the contribution is marked <b>Pending verification</b> until the committee reviews it.</p></div><div className="contribution-input-row"><label><span>Amount (₹)</span><input type="number" min="1" value={amount} onChange={e=>setAmount(e.target.value)} placeholder="Enter amount"/></label><button className="admin-primary" disabled={!value||value<1} onClick={()=>setQr(true)}>Pay contribution</button></div></div><div className="resident-contribution-list">{residentContributions.map(item=><div className="resident-contribution" key={item.name}><div><strong>{item.name}</strong><small>{item.date}</small></div><div><b>{item.amount}</b><span className="status-pill paid">{item.status}</span></div></div>)}</div>{qr&&<PaymentQR type="contribution" amount={value} onClose={()=>setQr(false)}/>}</ResidentSection>
}

function ResidentUpdates(){
 return <ResidentSection kicker="FROM THE ASSOCIATION" title="Community updates" action={<WhatsAppButton/>}>
   <div className="resident-update-grid">{residentUpdates.map(item=><article key={item.title}><div><span>{item.tag}</span><small>{item.date}</small></div><h4>{item.title}</h4><p>{item.text}</p></article>)}</div>
 </ResidentSection>
}

function ResidentDashboard({onLogout}:{onLogout:()=>void}){
 const[section,setSection]=useState<'Overview'|'Payments'|'Maintenance'|'Contributions'|'Updates'>('Overview');
 const navigate=(next:typeof section)=>{setSection(next);window.scrollTo(0,0)};
 return <div className="resident-shell"><header className="resident-topbar"><div className="resident-brand"><Logo/><div><strong>APC LAYOUT</strong><span>Resident Portal</span></div></div><nav className="resident-nav">{(['Overview','Payments','Maintenance','Contributions','Updates'] as const).map(item=><button key={item} className={section===item?'active':''} onClick={()=>navigate(item)}>{item}</button>)}</nav><div className="resident-actions"><ThemeToggle/><button onClick={onLogout}>Sign out</button></div></header>
 <main className="resident-main">
   <section className="resident-welcome"><div><span className="welcome-kicker">MY COMMUNITY PORTAL</span><h1>Welcome home, Resident.</h1><p>Your association information, payments and community updates in one place.</p></div><div className="resident-welcome-actions"><DemoBadge/><WhatsAppButton/></div></section>
   {section==='Overview'&&<><div className="resident-cards"><article><span>MAINTENANCE</span><strong>₹ 17,000</strong><small>Outstanding • FY 2026–27</small><button onClick={()=>navigate('Maintenance')}>View statement →</button></article><article><span>LAST PAYMENT</span><strong>₹ 8,500</strong><small>Receipt #REC-00124</small><button onClick={()=>navigate('Payments')}>View payment history →</button></article><article><span>COMMUNITY</span><strong>3 updates</strong><small>Latest notices & events</small><button onClick={()=>navigate('Updates')}>View updates →</button></article></div><ResidentSection kicker="MY ACCOUNT" title="Resident account"><div className="resident-account-grid"><div><small>House / Flat</small><strong>Demo Resident</strong></div><div><small>Account status</small><strong className="account-good">Active</strong></div><div><small>Registered contact</small><strong>••••••••••</strong></div><div><small>Financial year</small><strong>FY 2026–27</strong></div><div><small>Membership</small><strong>Active</strong></div><div><small>Last receipt</small><strong>#REC-00124</strong></div></div></ResidentSection><ResidentUpdates/></>}
   {section==='Payments'&&<ResidentPayments/>}
   {section==='Maintenance'&&<ResidentStatement/>}
   {section==='Contributions'&&<ResidentContributions/>}
   {section==='Updates'&&<ResidentUpdates/>}
 </main></div>
}



type PaymentDetails={date:string;mode:string;details:string};
type ResidentRecord={id:string;house:string;cross:string;name:string;mobile:string;password:string;initialCharge:number;initialChargePaid:boolean;membershipPayment?:PaymentDetails;active:boolean;createdAt:string};
type LedgerEntry={id:string;kind:string;amount:number;house?:string;description:string;mode:string;date:string;financialYear:string;status:string;expenseType?:string;direction?:string;donorName?:string;donationType?:string};
type OpeningBalances={bank:number;cash:number;financialYear:string;date:string};

const EXPENSE_TYPES_KEY='apclrwa_expense_types';
const OPENING_BALANCES_KEY='apclrwa_opening_balances';
const DONATION_TYPES=['Ganesha Festival','Sri Rama Navami'];
const demoResident:ResidentRecord={id:'RES-DEMO',house:'24',cross:'2nd Cross',name:'Demo Resident',mobile:'9876543210',password:'APC@Resident2026',initialCharge:500,initialChargePaid:true,membershipPayment:{date:'2026-09-01',mode:'UPI',details:'Demo membership payment'},active:true,createdAt:'2026-09-01T00:00:00.000Z'};
const defaultExpenseTypes=['Electricity','Garden maintenance','Security','Cleaning','Repairs & maintenance','Festival decoration','Office expenses','Water / utility','Other'];
function getResidents():ResidentRecord[]{try{const x=JSON.parse(localStorage.getItem('apclrwa_residents')||'[]');if(!Array.isArray(x)||!x.length)return[demoResident];return x.map((r:any)=>({...r,cross:r.cross||'',active:r.active!==false}))}catch{return[demoResident]}}
function saveResidents(x:ResidentRecord[]){localStorage.setItem('apclrwa_residents',JSON.stringify(x));window.dispatchEvent(new Event('apclrwa-residents-change'))}
function getLedger():LedgerEntry[]{try{const x=JSON.parse(localStorage.getItem('apclrwa_admin_ledger')||'[]');return Array.isArray(x)?x:[]}catch{return[]}}
function saveLedger(x:LedgerEntry[]){localStorage.setItem('apclrwa_admin_ledger',JSON.stringify(x));window.dispatchEvent(new Event('apclrwa-ledger-change'))}
function getExpenseTypes():string[]{try{const x=JSON.parse(localStorage.getItem(EXPENSE_TYPES_KEY)||'null');return Array.isArray(x)&&x.length?x:defaultExpenseTypes}catch{return defaultExpenseTypes}}
function saveExpenseTypes(x:string[]){localStorage.setItem(EXPENSE_TYPES_KEY,JSON.stringify(x))}
function getOpeningBalances():OpeningBalances{try{return JSON.parse(localStorage.getItem(OPENING_BALANCES_KEY)||'null')||{bank:217000,cash:18500,financialYear:'2026–27',date:'2026-04-01'}}catch{return{bank:217000,cash:18500,financialYear:'2026–27',date:'2026-04-01'}}}
function saveOpeningBalances(x:OpeningBalances){localStorage.setItem(OPENING_BALANCES_KEY,JSON.stringify(x));window.dispatchEvent(new Event('apclrwa-ledger-change'))}

function AddResidentForm({onClose,onSaved,editing}:{onClose:()=>void;onSaved:()=>void;editing?:ResidentRecord|null}){
 const[form,setForm]=useState<ResidentRecord>(editing?{...editing}:{...demoResident,id:'RES-'+Date.now(),house:'',cross:'',name:'',mobile:'',password:'',initialCharge:500,initialChargePaid:false,membershipPayment:undefined,active:true,createdAt:new Date().toISOString()});
 const[paid,setPaid]=useState(form.initialChargePaid);const[p,setP]=useState<PaymentDetails>(form.membershipPayment||{date:new Date().toISOString().slice(0,10),mode:'UPI',details:''});const[error,setError]=useState('');
 const update=(k:keyof ResidentRecord,v:string|boolean)=>setForm({...form,[k]:v});
 const save=(e:FormEvent)=>{e.preventDefault();const a=getResidents();if(!form.name||!form.house||!form.cross||!form.mobile||!form.password){setError('Name, house, cross, phone and password are required.');return}if(a.some(x=>x.id!==form.id&&(x.house===form.house||x.mobile===form.mobile))){setError('House or phone number already exists.');return}if(paid&&(!p.date||!p.mode||!p.details)){setError('Payment date, mode and transaction details are required.');return}const next={...form,initialCharge:500,initialChargePaid:paid,membershipPayment:paid?p:undefined,active:form.active};saveResidents(editing?a.map(x=>x.id===form.id?next:x):[...a,next]);onSaved();onClose()};
 return <div className="resident-modal-backdrop"><form className="resident-modal" onSubmit={save}><div className="event-modal-head"><div><div className="eyebrow">{editing?'EDIT RESIDENT':'RESIDENT REGISTRATION'}</div><h2>{editing?'Edit resident':'Add resident'}</h2></div><button type="button" className="modal-close" onClick={onClose}>×</button></div>
 <div className="resident-form-grid"><label>Resident name<input value={form.name} onChange={e=>update('name',e.target.value)} required/></label><label>House / Flat<input value={form.house} onChange={e=>update('house',e.target.value)} required/></label><label>Cross<input value={form.cross} onChange={e=>update('cross',e.target.value)} placeholder="2nd Cross" required/></label><label>Phone number<input value={form.mobile} onChange={e=>update('mobile',e.target.value)} required/></label><label>Password<input value={form.password} onChange={e=>update('password',e.target.value)} required/></label>{editing&&<label>Status<select value={form.active?'Active':'Inactive'} onChange={e=>update('active',e.target.value==='Active')}><option>Active</option><option>Inactive</option></select></label>}</div>
 <div className="resident-charge-option"><strong>Membership fee: ₹500</strong><small>One-time charge.</small><label><input type="checkbox" checked={paid} onChange={e=>setPaid(e.target.checked)}/> Mark as paid</label>{paid&&<div className="resident-form-grid"><label>Payment date<input type="date" value={p.date} onChange={e=>setP({...p,date:e.target.value})} required/></label><label>Payment mode<select value={p.mode} onChange={e=>setP({...p,mode:e.target.value})} required><option>UPI</option><option>Bank transfer</option><option>Cash</option><option>Cheque</option></select></label><label>Transaction details<input value={p.details} onChange={e=>setP({...p,details:e.target.value})} required/></label></div>}</div>
 {error&&<div className="login-error">{error}</div>}<div className="event-modal-actions"><button type="button" onClick={onClose}>Cancel</button><button className="admin-primary">{editing?'Save changes':'Create resident'}</button></div></form></div>
}

function AdminResidents(){
 const[residents,setResidents]=useState<ResidentRecord[]>(getResidents());const[open,setOpen]=useState(false);const[editing,setEditing]=useState<ResidentRecord|null>(null);
 useEffect(()=>{const sync=()=>setResidents(getResidents());window.addEventListener('apclrwa-residents-change',sync);return()=>window.removeEventListener('apclrwa-residents-change',sync)},[]);
 const edit=(r:ResidentRecord)=>{setEditing(r);setOpen(true)};
 return <section className="admin-module-stack"><section className="admin-panel"><div className="panel-head"><div><span>RESIDENT DIRECTORY</span><h3>Residents</h3></div><button className="admin-primary" onClick={()=>{setEditing(null);setOpen(true)}}>+ Add resident</button></div><p className="module-note">Residents use their phone number and password to sign in. Inactive residents are treated as moved out and are excluded from resident payment selection lists.</p>
 <div className="resident-admin-table"><div className="resident-admin-head"><span>House</span><span>Cross</span><span>Resident</span><span>Phone</span><span>Initial ₹500</span><span>Status</span><span>Action</span></div>{residents.map(r=><div className="resident-admin-row" key={r.id}><span>{r.house}</span><span>{r.cross||'—'}</span><span>{r.name}</span><span>{r.mobile}</span><span className={r.initialChargePaid?'good':'warn-cell'}>{r.initialChargePaid?'Paid':'Due'}</span><span className={r.active?'good':'warn-cell'}>{r.active?'Active':'Inactive'}</span><button className="table-link" onClick={()=>edit(r)}>Edit</button></div>)}</div></section>{open&&<AddResidentForm editing={editing} onClose={()=>{setOpen(false);setEditing(null)}} onSaved={()=>setResidents(getResidents())}/>}</section>
}

function AdminEntryForm({kind,onClose,editing}:{kind:'Maintenance'|'Collections'|'Expenses'|'Bank & Cash';onClose:()=>void;editing?:LedgerEntry|null}){
 const[amount,setAmount]=useState(editing?String(editing.amount):kind==='Maintenance'?'1000':'');const[house,setHouse]=useState(editing?.house||'');const[details,setDetails]=useState(editing?.description||'');const[mode,setMode]=useState(editing?.mode||(kind==='Bank & Cash'?'Contra (Bank → Cash)':'UPI'));const[date,setDate]=useState(editing?.date||new Date().toISOString().slice(0,10));const[fy,setFy]=useState(editing?.financialYear||'2026–27');const[type,setType]=useState(editing?.expenseType||'');const[types,setTypes]=useState(getExpenseTypes());const[donor,setDonor]=useState(editing?.donorName||'');const[donationType,setDonationType]=useState(editing?.donationType||'');const[donorResident,setDonorResident]=useState(()=>{const r=getResidents().find(x=>x.active&&x.name===editing?.donorName);return r?.id||(editing?'other':'')});const[error,setError]=useState('');
 const activeResidents=getResidents().filter(r=>r.active);const unpaid=activeResidents.filter(r=>r.house===editing?.house||!getLedger().some(x=>x.kind==='Maintenance'&&x.house===r.house&&x.financialYear===fy&&x.status==='Posted'));
 const addType=()=>{const x=prompt('New expense type');if(x?.trim()&&!types.includes(x.trim())){const n=[...types,x.trim()];saveExpenseTypes(n);setTypes(n);setType(x.trim())}};
 const submit=(e:FormEvent)=>{e.preventDefault();const n=Number(amount);if(n<=0){setError('Enter a valid amount.');return}if(!details||!mode||!date||!fy){setError('All transaction fields are mandatory.');return}if(kind==='Maintenance'&&!house){setError('Select an active resident who has not paid.');return}if(kind==='Expenses'&&!type){setError('Select an expense type.');return}if(kind==='Collections'&&(!donationType||!donor||!donorResident)){setError('Donation type, donor selection and donor name are required.');return}
 const id=editing?.id||(kind==='Expenses'?'EXP-':kind==='Maintenance'?'REC-':kind==='Bank & Cash'?'CONTRA-':'DON-')+Date.now();const x:LedgerEntry={id,kind,amount:n,house:kind==='Maintenance'?house:undefined,description:details,mode,date,financialYear:fy,status:'Posted',expenseType:type,donorName:donor,donationType};if(kind==='Bank & Cash')x.direction=mode.includes('Bank → Cash')?'Bank → Cash':'Cash → Bank';
 const all=getLedger();saveLedger(editing?all.map(v=>v.id===editing.id?x:v):[...all,x]);onClose()};
 return <div className="resident-modal-backdrop"><form className="resident-modal" onSubmit={submit}><div className="event-modal-head"><div><div className="eyebrow">{editing?'UPDATE':'NEW'} {kind==='Collections'?'DONATION':kind.toUpperCase()}</div><h2>{editing?'View / update':kind==='Collections'?'Record donation':'Record '+kind.toLowerCase()}</h2></div><button type="button" className="modal-close" onClick={onClose}>×</button></div>
 <div className="resident-form-grid">{kind==='Maintenance'&&<label>Resident who has not paid<select value={house} onChange={e=>setHouse(e.target.value)} required><option value="">Select resident</option>{unpaid.map(r=><option key={r.id} value={r.house}>{r.house} — {r.name} • {r.mobile}</option>)}</select></label>}
 {kind==='Collections'&&<><label>Donation type<select value={donationType} onChange={e=>setDonationType(e.target.value)} required><option value="">Select donation type</option>{DONATION_TYPES.map(x=><option key={x}>{x}</option>)}</select></label><label>Donor name<input value={donor} onChange={e=>setDonor(e.target.value)} required placeholder="Enter donor name"/></label><label>Resident donor<select value={donorResident} onChange={e=>{const v=e.target.value;setDonorResident(v);const r=activeResidents.find(x=>x.id===v);if(r)setDonor(r.name)}} required><option value="">Select resident / other</option>{activeResidents.map(r=><option key={r.id} value={r.id}>{r.house} — {r.name}</option>)}<option value="other">Other / external donor</option></select></label></>}
 {kind==='Expenses'&&<label>Expense type<div className="inline-field"><select value={type} onChange={e=>setType(e.target.value)} required><option value="">Select type</option>{types.map(x=><option key={x}>{x}</option>)}</select><button type="button" className="small-action" onClick={addType}>+ New type</button></div></label>}
 <label>Amount (₹)<input type="number" min="1" value={amount} onChange={e=>setAmount(e.target.value)} required/></label><label>Transaction details<input value={details} onChange={e=>setDetails(e.target.value)} required/></label><label>Payment method<select value={mode} onChange={e=>setMode(e.target.value)} required>{kind==='Bank & Cash'?<><option>Contra (Bank → Cash)</option><option>Contra (Cash → Bank)</option></>:<><option>UPI</option><option>Bank transfer</option><option>Cash</option><option>Cheque</option></>}</select></label><label>Date<input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label><label>Financial year<select value={fy} onChange={e=>setFy(e.target.value)} required>{financialYears.map(x=><option key={x}>{x}</option>)}</select></label></div>
 {error&&<div className="login-error">{error}</div>}<div className="event-modal-actions"><button type="button" onClick={onClose}>Cancel</button><button className="admin-primary" type="submit">{editing?'Update entry':'Post entry'}</button></div></form></div>
}

function PaymentReviewModal({item,onClose,onSave,onReview}:{item:any;onClose:()=>void;onSave:(p:any)=>void;onReview:(s:'Approved'|'Rejected')=>void}){
 const[date,setDate]=useState(item.transactionDate||item.date||'');const[mode,setMode]=useState(item.mode||'UPI');const[details,setDetails]=useState(item.details||'');
 return <div className="resident-modal-backdrop"><div className="resident-modal"><div className="event-modal-head"><div><div className="eyebrow">DONATION REVIEW</div><h2>{item.type} • {item.amount}</h2><p className="module-note">{item.resident||item.donorName||'Donor'}{item.house?' • House '+item.house:''}</p></div><button className="modal-close" onClick={onClose}>×</button></div>
 <div className="resident-form-grid"><label>Payment date<input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label><label>Payment method<select value={mode} onChange={e=>setMode(e.target.value)} required><option>UPI</option><option>Bank transfer</option><option>Cash</option><option>Cheque</option></select></label><label>Transaction details<input value={details} onChange={e=>setDetails(e.target.value)} required/></label></div><div className="event-modal-actions"><button onClick={()=>onSave({transactionDate:date,mode,details})}>Save details</button>{item.status==='Pending verification'&&<><button onClick={()=>onReview('Rejected')}>Reject</button><button className="admin-primary" onClick={()=>onReview('Approved')}>Approve</button></>}</div></div></div>
}

function AdminPaymentVerification(){
 const[items,setItems]=useState<any[]>(getPendingPayments());const[editing,setEditing]=useState<any|null>(null);
 useEffect(()=>{const f=()=>setItems(getPendingPayments());window.addEventListener('apclrwa-payments-change',f);return()=>window.removeEventListener('apclrwa-payments-change',f)},[]);
 const update=(id:string,p:any)=>{savePendingPayments(getPendingPayments().map(x=>x.id===id?{...x,...p}:x));setItems(getPendingPayments());setEditing(null)};
 const review=(id:string,status:'Approved'|'Rejected')=>{const p=getPendingPayments().find(x=>x.id===id);if(status==='Approved'&&p?.type==='Membership')saveResidents(getResidents().map(r=>r.house===p.house?{...r,initialChargePaid:true}:r));if(status==='Approved'&&(p?.type==='Contribution'||p?.type==='Donation')){const amount=Number(String(p.amount||'').replace(/[^0-9.]/g,''));if(amount>0&&!getLedger().some(x=>x.id==='DON-'+p.id)){saveLedger([...getLedger(),{id:'DON-'+p.id,kind:'Collections',amount,house:p.house,description:p.details||'Resident donation approved',mode:p.mode||'UPI',date:p.transactionDate||p.date,financialYear:p.financialYear||'2026–27',status:'Posted',donorName:p.donorName||p.resident||'Donor',donationType:p.donationType||'Ganesha Festival'}])}}update(id,{status,reviewedAt:new Date().toISOString(),reviewedBy:'committee.admin'})};
 return <><div className="verification-list">{items.length===0?<div className="verification-empty">No donations awaiting verification.</div>:items.map(p=><div className="verification-item" key={p.id}><div><span>{p.type==='Contribution'?'DONATION':p.type}</span><strong>{p.resident||p.donorName||'Donor'}{p.house?' • House '+p.house:''}</strong><small>{p.transactionDate||p.date} • {p.amount} • {p.id}</small></div><span className={p.status==='Pending verification'?'status-pill pending':p.status==='Approved'?'status-pill paid':'status-pill rejected'}>{p.status}</span><div className="verification-actions"><button onClick={()=>setEditing(p)}>{p.status==='Pending verification'?'View':'View & update'}</button>{p.status==='Pending verification'&&<><button onClick={()=>review(p.id,'Rejected')}>Reject</button><button className="admin-primary" onClick={()=>review(p.id,'Approved')}>Approve</button></>}</div></div>)}</div>{editing&&<PaymentReviewModal item={editing} onClose={()=>setEditing(null)} onSave={p=>update(editing.id,p)} onReview={s=>review(editing.id,s)}/>}</>
}

function OpeningBalanceForm({onClose}:{onClose:()=>void}){
 const current=getOpeningBalances();const[bank,setBank]=useState(String(current.bank));const[cash,setCash]=useState(String(current.cash));const[date,setDate]=useState(current.date);const[fy,setFy]=useState(current.financialYear);const[error,setError]=useState('');
 const save=(e:FormEvent)=>{e.preventDefault();if(Number(bank)<0||Number(cash)<0||!date||!fy){setError('Opening balances, date and financial year are required.');return}saveOpeningBalances({bank:Number(bank),cash:Number(cash),date,financialYear:fy});onClose()};
 return <div className="resident-modal-backdrop"><form className="resident-modal" onSubmit={save}><div className="event-modal-head"><div><div className="eyebrow">OPENING BALANCE</div><h2>Set bank & cash opening balances</h2></div><button type="button" className="modal-close" onClick={onClose}>×</button></div><div className="resident-form-grid"><label>Bank opening balance (₹)<input type="number" min="0" value={bank} onChange={e=>setBank(e.target.value)} required/></label><label>Cash opening balance (₹)<input type="number" min="0" value={cash} onChange={e=>setCash(e.target.value)} required/></label><label>Opening date<input type="date" value={date} onChange={e=>setDate(e.target.value)} required/></label><label>Financial year<select value={fy} onChange={e=>setFy(e.target.value)} required>{financialYears.map(x=><option key={x}>{x}</option>)}</select></label></div><p className="entry-help">These are book opening balances, similar to Tally's Cash/Bank ledger opening balances. Transactions entered after the opening point change the running balances.</p><div className="event-modal-actions"><button type="button" onClick={onClose}>Cancel</button><button className="admin-primary">Save opening balances</button></div></form></div>
}

function AdminFinancialTable({kind}:{kind:'Maintenance'|'Collections'|'Expenses'|'Bank & Cash'|'Reports'|'Audit Trail'}){
 const[open,setOpen]=useState(false);const[openingOpen,setOpeningOpen]=useState(false);const[editing,setEditing]=useState<LedgerEntry|null>(null);const[ledger,setLedger]=useState<LedgerEntry[]>(getLedger());const[balances,setBalances]=useState({bank:0,cash:0});const[report,setReport]=useState('');const fy=localStorage.getItem('apclrwa_selected_fy')||'2026–27';
 const sync=()=>{const a=getLedger();setLedger(a);const o=getOpeningBalances();let bank=o.bank,cash=o.cash;a.forEach(x=>{if(x.status!=='Posted')return;if(x.kind==='Bank & Cash'){if(x.direction==='Bank → Cash'){bank-=x.amount;cash+=x.amount}else{bank+=x.amount;cash-=x.amount}}else if(x.kind==='Collections'||x.kind==='Maintenance'){if(x.mode==='Cash')cash+=x.amount;else bank+=x.amount}else if(x.kind==='Expenses'){if(x.mode==='Cash')cash-=x.amount;else bank-=x.amount}});setBalances({bank,cash})};
 useEffect(()=>{sync();window.addEventListener('apclrwa-ledger-change',sync);return()=>window.removeEventListener('apclrwa-ledger-change',sync)},[]);
 const fmt=(n:number)=>'₹ '+n.toLocaleString('en-IN');const remove=(id:string)=>{if(window.confirm('Delete this entry? This is the demo equivalent of deleting a Tally voucher.'))saveLedger(getLedger().filter(x=>x.id!==id))};
 const rows=kind==='Maintenance'?ledger.filter(x=>x.kind==='Maintenance').map(x=>[x.house||'—',x.financialYear,fmt(x.amount),x.status,x.id]):kind==='Collections'?ledger.filter(x=>x.kind==='Collections').map(x=>[x.id,x.date,x.donorName||'—',x.donationType||'—',fmt(x.amount),x.mode,x.id]):kind==='Expenses'?ledger.filter(x=>x.kind==='Expenses').map(x=>[x.id,x.expenseType||x.description,x.date,x.mode,fmt(x.amount),x.status,x.id]):kind==='Bank & Cash'?ledger.filter(x=>x.kind==='Bank & Cash').map(x=>[x.date,x.direction||'',x.description,fmt(x.amount),x.status,x.id]):[];
 const headers=kind==='Maintenance'?['House','FY','Amount','Status','Action']:kind==='Collections'?['Receipt','Date','Donor','Donation type','Amount','Mode','Action']:kind==='Expenses'?['Voucher','Expense type','Date','Mode','Amount','Status','Action']:kind==='Bank & Cash'?['Date','Entry','Transaction details','Amount','Status','Action']:[];
 const edit=(id:string)=>{const x=ledger.find(v=>v.id===id);if(x){setEditing(x);setOpen(true)}};
 const download=(name:string,body:string,type='text/csv')=>{const url=URL.createObjectURL(new Blob([body],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),500)};
 const csv=(name:string)=>{const a=ledger.filter(x=>x.financialYear===fy);const rows=name==='Maintenance collection report'?[['House','FY','Amount','Status'],...a.filter(x=>x.kind==='Maintenance').map(x=>[x.house||'',x.financialYear,String(x.amount),x.status])]:name==='Income & expenditure'?[['Type','Amount','Details'],...a.map(x=>[x.kind,String(x.amount),x.description])]:name==='Cash & bank book'?[['Date','Entry','Amount','Details'],...a.filter(x=>x.kind==='Bank & Cash').map(x=>[x.date,x.direction||'',String(x.amount),x.description])]:[['ID','Date','Kind','Amount','Details'],...a.map(x=>[x.id,x.date,x.kind,String(x.amount),x.description])];return rows.map(r=>r.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\\n')};
 const reports=['Maintenance collection report','Income & expenditure','Cash & bank book','General ledger','Trial balance','Audit register'];const auditPack=()=>{const html='<html><body><h1>APCLRWA Audit Pack — FY '+fy+'</h1><p>Bank: '+fmt(balances.bank)+' | Cash: '+fmt(balances.cash)+'</p><table border="1" cellpadding="6"><tr><th>ID</th><th>Date</th><th>Type</th><th>Amount</th><th>Mode</th><th>Details</th></tr>'+ledger.filter(x=>x.financialYear===fy).map(x=>'<tr><td>'+x.id+'</td><td>'+x.date+'</td><td>'+x.kind+'</td><td>'+fmt(x.amount)+'</td><td>'+x.mode+'</td><td>'+x.description+'</td></tr>').join('')+'</table></body></html>';download('APCLRWA_Audit_Pack_FY_'+fy+'.html',html,'text/html')};
 return <section className="admin-module-stack">{kind==='Bank & Cash'&&<><div className="balance-strip"><div><span>BANK BALANCE</span><strong>{fmt(balances.bank)}</strong></div><div><span>CASH IN HAND</span><strong>{fmt(balances.cash)}</strong></div><div><span>TOTAL LIQUID FUNDS</span><strong>{fmt(balances.bank+balances.cash)}</strong></div></div><section className="admin-panel"><div className="panel-head"><div><span>BOOK SETUP</span><h3>Opening balances</h3></div><button className="admin-primary" onClick={()=>setOpeningOpen(true)}>Set opening balance</button></div></section></section></>}
 <section className="admin-panel"><div className="panel-head"><div><span>{kind==='Collections'?'DONATIONS':kind.toUpperCase()}</span><h3>{kind==='Collections'?'Donations':kind}</h3></div>{['Maintenance','Collections','Expenses','Bank & Cash'].includes(kind)?<button className="admin-primary" onClick={()=>{setEditing(null);setOpen(true)}}>+ Add {kind==='Collections'?'donation':kind==='Bank & Cash'?'transaction':kind.toLowerCase()}</button>:<DemoBadge/>}</div>{kind==='Collections'&&<AdminPaymentVerification/>}{kind==='Reports'?<><div className="report-grid">{reports.map(n=><div className="report-card" key={n}><div><strong>{n}</strong><small>FY {fy}</small></div><div><button onClick={()=>setReport(n)}>View / generate</button><button onClick={()=>download(n.replace(/[^a-z0-9]+/gi,'_')+'.csv',csv(n))}>Export CSV</button></div></div>)}</div><div className="report-actions"><button className="admin-primary" onClick={auditPack}>Generate audit pack</button></div>{report&&<div className="report-preview"><h4>{report}</h4><p>Generated for FY {fy}. Export CSV or use Print / Save as PDF.</p><button onClick={()=>download(report.replace(/[^a-z0-9]+/gi,'_')+'.csv',csv(report))}>Download CSV</button> <button onClick={()=>window.print()}>Print / Save as PDF</button></div>}</>:<div className="admin-data-table-wrap"><table className="admin-data-table"><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row:any[],i)=><tr key={i}>{row.map((v,j)=><td key={j}>{j===row.length-1?<span className="table-action-group"><button className="table-link" onClick={()=>edit(v)}>View & update</button>{['Maintenance','Collections','Expenses'].includes(kind)&&<button className="danger-link" onClick={()=>remove(v)}>Delete</button>}</span>:v}</td>)}</tr>)}</tbody></table></div>}{open&&<AdminEntryForm kind={kind as any} editing={editing} onClose={()=>{setOpen(false);setEditing(null)}}/>}{openingOpen&&<OpeningBalanceForm onClose={()=>setOpeningOpen(false)}/>}</section></section>
}
function EventManager(){
 const[events,setEvents]=useState<EventItem[]>(()=>{try{return JSON.parse(localStorage.getItem('apclrwa_events')||'')||defaultEvents}catch{return defaultEvents}});
 const[modalOpen,setModalOpen]=useState(false);
 const[editing,setEditing]=useState<EventItem|null>(null);
 const[form,setForm]=useState<EventItem>({id:'',tag:'EVENTS',title:'',text:'',date:'',location:'APC Layout'});
 const startAdd=()=>{setEditing(null);setForm({id:crypto.randomUUID(),tag:'EVENTS',title:'',text:'',date:'',location:'APC Layout'});setModalOpen(true)};
 const startEdit=(item:EventItem)=>{setEditing(item);setForm(item);setModalOpen(true)};
 const close=()=>{setModalOpen(false);setEditing(null)};
 const save=(e:FormEvent)=>{e.preventDefault();const next=editing?events.map(x=>x.id===form.id?form:x):[...events,form];setEvents(next);localStorage.setItem('apclrwa_events',JSON.stringify(next));close()};
 const remove=(id:string)=>{const next=events.filter(x=>x.id!==id);setEvents(next);localStorage.setItem('apclrwa_events',JSON.stringify(next))};
 return <section className="admin-events-panel"><div className="panel-head"><div><span>HOMEPAGE CONTENT</span><h3>Events & announcements</h3></div><button className="admin-primary" onClick={startAdd}>+ Add event</button></div>
   <p className="module-note">Events added here appear on the public homepage under Latest Updates.</p>
   <div className="event-admin-list">{events.map(item=><div className="event-admin-row" key={item.id}><div><span>{item.tag}</span><strong>{item.title}</strong><small>{item.date} • {item.location}</small></div><div><button onClick={()=>startEdit(item)}>Edit</button><button className="danger-link" onClick={()=>remove(item.id)}>Delete</button></div></div>)}</div>
   {modalOpen&&<div className="event-modal-backdrop"><form className="event-modal" onSubmit={save}><div className="event-modal-head"><div><div className="eyebrow">{editing?'EDIT HOMEPAGE ITEM':'NEW HOMEPAGE ITEM'}</div><h2>{editing?'Edit event / announcement':'Add event / announcement'}</h2></div><button type="button" onClick={close}>×</button></div><EventForm form={form} setForm={setForm}/><div className="event-modal-actions"><button type="button" onClick={close}>Cancel</button><button className="admin-primary" type="submit">{editing?'Save changes':'Publish to homepage'}</button></div></form></div>}
 </section>
}
function EventForm({form,setForm}:{form:EventItem;setForm:(v:EventItem)=>void}){
 const update=(key:keyof EventItem,value:string)=>setForm({...form,[key]:value});
 return <div className="event-form"><label>Category<input value={form.tag} onChange={e=>update('tag',e.target.value)} placeholder="EVENTS"/></label><label>Title<input value={form.title} onChange={e=>update('title',e.target.value)} placeholder="Community event title" required/></label><label>Description<textarea value={form.text} onChange={e=>update('text',e.target.value)} placeholder="What should residents know?" required/></label><div className="event-form-grid"><label>Date / time<input value={form.date} onChange={e=>update('date',e.target.value)} placeholder="18 October 2026"/></label><label>Location<input value={form.location} onChange={e=>update('location',e.target.value)} placeholder="APC Layout"/></label></div></div>
}

function AdminDashboard({onLogout}:{onLogout:()=>void}){
 const[section,setSection]=useState('Overview');
 const[selectedFY,setSelectedFY]=useState(()=>localStorage.getItem('apclrwa_selected_fy')||'2026–27');
 const nav=['Overview','Residents','Maintenance','Collections','Expenses','Bank & Cash','Reports','Events','Audit Trail'];
 const stats=fyStats[selectedFY]||fyStats['2026–27'];
 const switchFY=(fy:string)=>{setSelectedFY(fy);localStorage.setItem('apclrwa_selected_fy',fy)};
 const renderModule=()=>{
   if(section==='Residents')return <AdminResidents/>;
   if(['Maintenance','Collections','Expenses','Bank & Cash','Reports','Audit Trail'].includes(section))return <AdminFinancialTable kind={section as 'Maintenance'|'Collections'|'Expenses'|'Bank & Cash'|'Reports'|'Audit Trail'}/>;
   if(section==='Events')return <EventManager/>;
   return null;
 };
 return <div className="admin-shell">
   <aside className="admin-sidebar"><div className="admin-brand"><Logo/><div><strong>APC LAYOUT</strong><span>Committee Portal</span></div></div><div className="admin-user"><div className="admin-avatar">CA</div><div><strong>Committee Admin</strong><span>Administrator</span></div></div><nav className="admin-nav">{nav.map(item=><button key={item} className={section===item?'active':''} onClick={()=>setSection(item)}><span className="nav-icon">{({Overview:'⌂',Residents:'♙',Maintenance:'₹',Collections:'▣',Expenses:'↘','Bank & Cash':'▤',Reports:'▥',Events:'✦','Audit Trail':'✓'} as Record<string,string>)[item]}</span>{item}</button>)}</nav><button className="admin-logout" onClick={onLogout}>↪ Sign out</button></aside>
   <main className="admin-main"><header className="admin-topbar"><button className="mobile-admin-brand" onClick={()=>setSection('Overview')}><Logo/></button><div><div className="eyebrow">APC LAYOUT • COMMITTEE PORTAL</div><h1>{section}</h1></div><div className="admin-top-actions"><ThemeToggle/><label className="fy-switch"><span>Financial year</span><select value={selectedFY} onChange={e=>switchFY(e.target.value)}>{financialYears.map(fy=><option key={fy} value={fy}>FY {fy}</option>)}</select></label><div className="admin-profile">CA</div></div></header>
   {section==='Overview'?<><div className="admin-welcome"><div><span className="welcome-kicker">GOOD AFTERNOON</span><h2>Welcome back, Committee Admin.</h2><p>Association snapshot for <strong>FY {selectedFY}</strong>.</p></div><button className="admin-primary" onClick={()=>setSection('Events')}>+ Add homepage event</button></div>
   <div className="admin-stats">{stats.map(([value,label])=><div className="admin-stat" key={label}><span>{label}</span><strong>{value}</strong><small>Demo data • FY {selectedFY}</small></div>)}</div>
   <div className="admin-grid"><section className="admin-panel"><div className="panel-head"><div><span>FINANCIAL ACTIVITY</span><h3>Recent transactions</h3></div><button onClick={()=>setSection('Reports')}>View reports →</button></div><div className="transaction-list"><div><span className="txn-icon income">↓</span><div><strong>Maintenance payment</strong><small>House 24 • Receipt #REC-00124</small></div><b className="amount-positive">+ ₹8,500</b></div><div><span className="txn-icon expense">↑</span><div><strong>Garden maintenance</strong><small>Voucher #EXP-00031 • Bank</small></div><b className="amount-negative">− ₹4,200</b></div><div><span className="txn-icon income">↓</span><div><strong>Ganesha festival donation</strong><small>House 67 • Receipt #REC-00119</small></div><b className="amount-positive">+ ₹2,000</b></div><div><span className="txn-icon expense">↑</span><div><strong>Electricity bill</strong><small>Voucher #EXP-00030 • Bank</small></div><b className="amount-negative">− ₹3,840</b></div></div></section>
   <section className="admin-panel"><div className="panel-head"><div><span>ATTENTION</span><h3>Tasks to review</h3></div></div><div className="task-list"><div><i className="task-dot red"/>12 residents have maintenance outstanding</div><div><i className="task-dot gold"/>5 bank transactions need reconciliation</div><div><i className="task-dot green"/>FY 2025–26 audit pack is ready</div><div><i className="task-dot blue"/>3 new resident records to verify</div></div></section></div>
   <section className="admin-panel quick-panel"><div className="panel-head"><div><span>QUICK ACTIONS</span><h3>Common committee tasks</h3></div></div><div className="quick-actions"><button onClick={()=>setSection('Residents')}>+ Add resident</button><button onClick={()=>setSection('Maintenance')}>₹ Record maintenance</button><button onClick={()=>setSection('Collections')}>↓ Record collection</button><button onClick={()=>setSection('Expenses')}>↗ Record expense</button><button onClick={()=>setSection('Bank & Cash')}>▣ Bank & cash</button><button onClick={()=>setSection('Events')}>✦ Add homepage event</button></div></section>
   </>:renderModule()}
   <footer className="admin-footer">APC Layout Residents Welfare Association • FY {selectedFY} • Committee access • <button onClick={onLogout}>Sign out</button></footer>
   </main>
 </div>
}

export default function App(){
 const[signedIn,setSignedIn]=useState(()=>localStorage.getItem('apclrwa_admin_session')==='true');
 const[residentSignedIn,setResidentSignedIn]=useState(()=>localStorage.getItem('apclrwa_resident_session')==='true');
 const[view,setView]=useState<View>(()=>localStorage.getItem('apclrwa_admin_session')==='true'?'admin':localStorage.getItem('apclrwa_resident_session')==='true'?'resident':'home');
 const go=(next:View)=>{setView(next);window.scrollTo(0,0)};
 const login=()=>{setSignedIn(true);setView('admin');window.scrollTo(0,0)};
 const residentLogin=(username:string)=>{localStorage.setItem('apclrwa_resident_username',username);setResidentSignedIn(true);setView('resident');window.scrollTo(0,0)};
 const logout=()=>{localStorage.removeItem('apclrwa_admin_session');setSignedIn(false);setView('home')};
 const residentLogout=()=>{localStorage.removeItem('apclrwa_resident_session');localStorage.removeItem('apclrwa_resident_username');setResidentSignedIn(false);setView('home')};
 if(signedIn&&view==='admin')return <AdminDashboard onLogout={logout}/>;
 if(residentSignedIn&&view==='resident')return <ResidentDashboard onLogout={residentLogout}/>;
 if(view==='login')return <Login onBack={()=>go('home')} onLogin={login} onResidentLogin={residentLogin}/>;
 return <Home go={go}/>;
}
