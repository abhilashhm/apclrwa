import {FormEvent, useEffect, useState, type CSSProperties, type ReactNode} from 'react';

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
const DEMO_RESIDENT={username:'resident@apclayout.in',password:'APC@Resident2026'};
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

function Login({onBack,onLogin,onResidentLogin}:{onBack:()=>void;onLogin:()=>void;onResidentLogin:()=>void}){
 const[role,setRole]=useState<LoginRole>('resident');
 const[username,setUsername]=useState('');
 const[password,setPassword]=useState('');
 const[showPassword,setShowPassword]=useState(false);
 const[error,setError]=useState('');
 const submit=(e:FormEvent)=>{e.preventDefault();setError('');
   if(role==='committee'&&username===DEMO_ADMIN.username&&password===DEMO_ADMIN.password){localStorage.setItem('apclrwa_admin_session','true');onLogin();return}
   if(role==='resident'&&username===DEMO_RESIDENT.username&&password===DEMO_RESIDENT.password){localStorage.setItem('apclrwa_resident_session','true');onResidentLogin();return}
   setError('Invalid credentials. Please check your details and try again.');
 };
 return <div className="auth-page"><div className="auth-decoration auth-left"/><div className="auth-decoration auth-right"/><button className="auth-back" onClick={onBack}>← Back to website</button><div className="auth-card resident-auth-card">
   <div className="auth-brand"><Logo/><div><strong>APC LAYOUT</strong><span>Residents Welfare Association</span></div></div>
   <div className="auth-heading"><div className="eyebrow">SECURE COMMUNITY PORTAL</div><h1>Welcome <em>home.</em></h1><p>Sign in to view your association information, payment history, receipts and community updates.</p></div>
   <div className="role-switch"><button className={role==='resident'?'active':''} onClick={()=>{setRole('resident');setError('')}}>Resident</button><button className={role==='committee'?'active':''} onClick={()=>{setRole('committee');setError('')}}>Committee</button></div>
   {role==='resident'&&<div className="resident-login-intro"><span>🏠</span><div><strong>Resident access</strong><small>Use your registered email/mobile and password.</small></div></div>}
   <form className="login-form" onSubmit={submit}>
     <label>{role==='committee'?'Committee username':'Registered email or mobile'}<input value={username} onChange={e=>setUsername(e.target.value)} placeholder={role==='committee'?'committee.admin':'you@example.com or 98XXXXXXXX'} autoComplete="username" required/></label>
     <label>Password<div className="password-wrap"><input type={showPassword?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password" autoComplete="current-password" required/><button type="button" onClick={()=>setShowPassword(!showPassword)}>{showPassword?'Hide':'Show'}</button></div></label>
     <div className="login-options"><label className="remember-option"><input type="checkbox"/> <span>Remember me</span></label><button type="button" onClick={()=>alert('Password reset will be connected to the backend authentication service.')}>Forgot password?</button></div>
     {error&&<div className="login-error">{error}</div>}
     <button className="login-submit" type="submit">Sign in as {role==='committee'?'Committee Admin':'Resident'} <span>→</span></button>
   </form>
   {role==='resident'?<div className="resident-help"><strong>New resident?</strong><span>Contact the association committee to have your account created.</span></div>:<div className="demo-credentials"><strong>Demo committee admin</strong><span>Username: <b>committee.admin</b></span><span>Password: <b>APC@Admin2026</b></span></div>}
   <div className="auth-footer">APC Layout, Thindlu • Bengaluru – 560097</div>
 </div></div>
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
 return <ResidentSection kicker="MAINTENANCE" title="FY 2026–27 statement" action={<span className="resident-count">6 months shown</span>}>
   <div className="resident-table-wrap"><table className="resident-table"><thead><tr><th>Month</th><th>Charge</th><th>Paid</th><th>Balance</th></tr></thead><tbody>{residentStatement.map(item=><tr key={item.month}><td>{item.month}</td><td>{item.charge}</td><td>{item.paid}</td><td className={item.balance==='₹ 0'?'balance-zero':'balance-due'}><strong>{item.balance}</strong></td></tr>)}</tbody></table></div>
   <div className="resident-summary-row"><div><span>Total charges</span><strong>₹ 51,000</strong></div><div><span>Total paid</span><strong>₹ 34,000</strong></div><div className="due"><span>Outstanding</span><strong>₹ 17,000</strong></div></div>
 </ResidentSection>
}

function ResidentContributions(){
 return <ResidentSection kicker="COMMUNITY FUNDS" title="Festival & community contributions" action={<span className="resident-count">{residentContributions.length} contributions</span>}>
   <div className="resident-contribution-list">{residentContributions.map(item=><div className="resident-contribution" key={item.name}><div><strong>{item.name}</strong><small>{item.date}</small></div><div><b>{item.amount}</b><span className="status-pill paid">{item.status}</span></div></div>)}</div>
 </ResidentSection>
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

function AdminResidents(){
 return <section className="admin-module-stack"><section className="admin-panel"><div className="panel-head"><div><span>RESIDENT DIRECTORY</span><h3>Residents</h3></div><button className="admin-primary">+ Add resident</button></div><p className="module-note">Demo records. In the production backend, resident accounts, property records and contacts will be maintained here with role-based access.</p><div className="resident-admin-table"><div className="resident-admin-head"><span>House</span><span>Resident</span><span>Contact</span><span>Status</span><span>Outstanding</span></div>{[['24','Demo Resident','••••••••••','Active','₹ 17,000'],['31','A. Kumar','••••••••••','Active','₹ 8,500'],['67','R. Shetty','••••••••••','Active','₹ 0'],['72','S. Rao','••••••••••','Pending','₹ 12,000']].map(row=><div className="resident-admin-row" key={row[0]}>{row.map((v,i)=><span key={i} className={i===3&&v==='Active'?'good':''}>{v}</span>)}</div>)}</div></section></section>
}

function AdminFinancialTable({kind}:{kind:'Maintenance'|'Collections'|'Expenses'|'Bank & Cash'|'Reports'|'Audit Trail'}){
 const data=kind==='Maintenance'?[['24','FY 2026–27','₹ 51,000','₹ 34,000','₹ 17,000','Due'],['31','FY 2026–27','₹ 51,000','₹ 42,500','₹ 8,500','Due'],['67','FY 2026–27','₹ 51,000','₹ 51,000','₹ 0','Clear'],['72','FY 2026–27','₹ 51,000','₹ 39,000','₹ 12,000','Due']]
 :kind==='Collections'?[['REC-00124','28 Sep 2026','House 24','Maintenance','₹ 8,500','Bank transfer'],['REC-00119','02 Aug 2026','House 67','Festival donation','₹ 2,000','UPI'],['REC-00111','30 Aug 2026','House 31','Maintenance','₹ 8,500','UPI']]
 :kind==='Expenses'?[['EXP-00031','Garden maintenance','30 Sep 2026','Bank','₹ 4,200','Approved'],['EXP-00030','Electricity bill','27 Sep 2026','Bank','₹ 3,840','Approved'],['EXP-00029','Festival decoration','18 Sep 2026','Cash','₹ 6,500','Approved']]
 :kind==='Bank & Cash'?[['30 Sep 2026','Bank – RWA A/c','Opening + receipts - expenses','₹ 2,17,000','Reconciled'],['30 Sep 2026','Cash in hand','Opening + cash receipts - cash expenses','₹ 18,500','Reconciled'],['29 Sep 2026','Bank – RWA A/c','UPI settlement','₹ 12,400','Pending reconciliation']]
 :kind==='Reports'?[['Maintenance collection report','FY 2026–27','Collections, outstanding & defaulters','Ready'],['Income & expenditure','FY 2026–27','Income and expenses by account','Ready'],['Cash & bank book','FY 2026–27','Ledger-based cash and bank movement','Ready'],['Audit pack','FY 2025–26','Receipts, vouchers, ledger and reconciliation','Ready']]
 :[['06 Oct 2026 21:04','committee.admin','CREATE','Maintenance receipt REC-00124'],['06 Oct 2026 20:58','committee.admin','POST','Expense voucher EXP-00031'],['06 Oct 2026 20:42','committee.admin','RECONCILE','Bank transaction #BT-00118'],['06 Oct 2026 20:15','committee.admin','LOGIN','Committee portal']];
 const headers=kind==='Maintenance'?['House','FY','Charge','Paid','Outstanding','Status']:kind==='Collections'?['Receipt','Date','House','Type','Amount','Mode']:kind==='Expenses'?['Voucher','Description','Date','Mode','Amount','Status']:kind==='Bank & Cash'?['Date','Account','Narration','Balance','Status']:kind==='Reports'?['Report','FY','Coverage','Status']:['Timestamp','User','Action','Entity'];
 return <section className="admin-module-stack"><section className="admin-panel"><div className="panel-head"><div><span>{kind.toUpperCase()}</span><h3>{kind}</h3></div><DemoBadge/></div><p className="module-note">{kind==='Reports'?'Reports will be generated from the immutable accounting ledger.':'Demo records shown for UI validation; production values will come from the FastAPI + SQLite backend.'}</p><div className="admin-data-table-wrap"><table className="admin-data-table"><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{data.map((row,i)=><tr key={i}>{row.map((v,j)=><td key={j} className={(v==='Clear'||v==='Reconciled'||v==='Ready'||v==='Approved')?'good-cell':(v==='Due'||v==='Pending reconciliation')?'warn-cell':''}>{v}</td>)}</tr>)}</tbody></table></div>{kind==='Reports'&&<div className="report-actions"><button>Export CSV</button><button>Export PDF</button><button className="admin-primary">Generate audit pack</button></div>}</section></section>
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
 const residentLogin=()=>{setResidentSignedIn(true);setView('resident');window.scrollTo(0,0)};
 const logout=()=>{localStorage.removeItem('apclrwa_admin_session');setSignedIn(false);setView('home')};
 const residentLogout=()=>{localStorage.removeItem('apclrwa_resident_session');setResidentSignedIn(false);setView('home')};
 if(signedIn&&view==='admin')return <AdminDashboard onLogout={logout}/>;
 if(residentSignedIn&&view==='resident')return <ResidentDashboard onLogout={residentLogout}/>;
 if(view==='login')return <Login onBack={()=>go('home')} onLogin={login} onResidentLogin={residentLogin}/>;
 return <Home go={go}/>;
}
