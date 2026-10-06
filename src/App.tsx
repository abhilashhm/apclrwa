import {FormEvent, useState} from 'react';

type View = 'home' | 'login' | 'admin';
type LoginRole = 'resident' | 'committee';

const highlights=[
  {icon:'🏡',title:'A connected neighbourhood',text:'A common digital home for residents, families and the association committee.'},
  {icon:'📣',title:'Updates that matter',text:'Keep up with notices, community events, announcements and important dates.'},
  {icon:'🧾',title:'Clear & transparent',text:'Make association finances and resident records easier to understand and access.'}
];

const updates=[
  {tag:'COMMUNITY',title:'Welcome to the new APCLAYOUT community portal',text:'A digital space is being created to make everyday RWA communication and services simpler.',date:'Coming soon'},
  {tag:'EVENTS',title:'Community events & activities',text:'Festival celebrations, competitions and neighbourhood activities will have a dedicated home here.',date:'Stay tuned'},
  {tag:'TRANSPARENCY',title:'Association accounts',text:'Resident-facing financial information will be presented clearly as the accounting portal rolls out.',date:'In progress'}
];

const DEMO_ADMIN={username:'committee.admin',password:'APC@Admin2026'};

function Logo({className='' }:{className?:string}){return <img className={className} src="./logo.svg" alt="APC Layout Residents Welfare Association logo"/>}

function ThemeToggle(){
  const[dark,setDark]=useState(()=>localStorage.getItem('apclrwa_theme')==='dark');
  useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light';localStorage.setItem('apclrwa_theme',dark?'dark':'light')},[dark]);
  return <button className="theme-toggle" onClick={()=>setDark(v=>!v)} aria-label={dark?'Switch to light mode':'Switch to dark mode'} title={dark?'Light mode':'Dark mode'}>{dark?'☀':'☾'}</button>;
}
function OfficeBearerPhoto({index}:{index:number}){return <div className="ob-photo-placeholder"><span>PHOTO</span><small>Image {index+1}</small></div>}
function OfficeBearers(){
  const[open,setOpen]=useState(false);
  return <section className="office-bearers"><div className="container">
    <div className="section-heading ob-heading"><div className="eyebrow">OUR ASSOCIATION</div><h2>APCLRWA <em>Office Bearers</em></h2><p>Meet the association office bearers serving APC Layout. The full list is available below.</p></div>
    <div className="ob-feature-grid">{officeBearers.slice(0,2).map(person=><article className="ob-card featured" key={person.name}><OfficeBearerPhoto index={person.photo}/><div className="ob-info"><h3>{person.display}</h3><p>{person.role}</p></div></article>)}</div>
    <button className="button primary ob-see-all" onClick={()=>setOpen(true)}>See the rest <span>→</span></button>
  </div>
  {open&&<div className="ob-modal-backdrop" role="dialog" aria-modal="true" onMouseDown={e=>{if(e.target===e.currentTarget)setOpen(false)}}><div className="ob-modal">
    <div className="ob-modal-head"><div><div className="eyebrow">APCLRWA 2025–2027</div><h2>Office Bearers</h2></div><button className="ob-close" onClick={()=>setOpen(false)}>×</button></div>
    <div className="ob-modal-grid">{officeBearers.map(person=><article className="ob-card" key={person.name}><OfficeBearerPhoto index={person.photo}/><div className="ob-info"><h3>{person.display}</h3><p>{person.role}</p></div></article>)}</div>
  </div></div>}
</section>;
}
function Home({go}:{go:(view:View)=>void}){
  const[menuOpen,setMenuOpen]=useState(false);
  const scrollTo=(id:string)=>{document.getElementById(id)?.scrollIntoView({behavior:'smooth'});setMenuOpen(false)};
  return <div className="site-shell">
    <div className="top-strip"><div className="container top-strip-inner"><span>APC Layout • Thindlu • Bengaluru – 560097</span><span className="top-strip-note">Building a better-connected community</span></div></div>
    <header className="navbar"><div className="container nav-inner">
      <button className="brand" onClick={()=>scrollTo('home')} aria-label="APC Layout home"><Logo/><span className="brand-copy"><strong>APC LAYOUT</strong><small>Residents Welfare Association</small></span></button>
      <button className="menu-toggle" aria-label={menuOpen?'Close navigation':'Open navigation'} aria-expanded={menuOpen} onClick={()=>setMenuOpen(!menuOpen)}><span/><span/><span/></button>
      <nav className={menuOpen?'nav-links open':'nav-links'} aria-label="Primary navigation">
        <button onClick={()=>scrollTo('home')}>Home</button><button onClick={()=>scrollTo('community')}>Our Community</button><button onClick={()=>scrollTo('updates')}>Updates</button><button onClick={()=>scrollTo('transparency')}>Transparency</button>
        <button className="nav-login" onClick={()=>go('login')}>Resident / Committee Login</button>
      </nav>
    </div></header>
    <main>
      <section id="home" className="hero"><div className="hero-glow glow-one"/><div className="hero-glow glow-two"/><div className="container hero-grid">
        <div className="hero-copy"><div className="eyebrow"><span className="eyebrow-dot"/> OUR COMMUNITY, OUR HOME</div><h1>One neighbourhood.<br/><em>One connected community.</em></h1>
          <p className="hero-lead">Welcome to the digital home of APC Layout Residents Welfare Association. Stay informed, participate in community life and access association services from one place.</p>
          <div className="hero-actions"><button className="button primary" onClick={()=>go('login')}>Open Portal <span>→</span></button><button className="button secondary" onClick={()=>scrollTo('community')}>Explore our community</button></div>
          <div className="trust-row"><span>✓ Community-first</span><span>✓ Transparent</span><span>✓ Resident-friendly</span></div>
        </div>
        <div className="hero-card-wrap" aria-label="Community welcome"><div className="hero-card"><div className="hero-card-art"><div className="sun"/><div className="cloud cloud-a"/><div className="cloud cloud-b"/><div className="hill hill-back"/><div className="hill hill-front"/><div className="road"/><div className="tree tree-left"><i/><b/><b/><b/></div><div className="tree tree-right"><i/><b/><b/><b/></div><div className="home-shape"><span className="roof"/><span className="house-body"/><span className="door"/><span className="window"/></div></div><div className="hero-card-caption"><span className="mini-mark">APC</span><div><strong>Welcome home.</strong><small>APC Layout, Thindlu</small></div></div></div><div className="floating-note note-one"><span>✦</span><div><strong>Community updates</strong><small>All in one place</small></div></div><div className="floating-note note-two"><span>₹</span><div><strong>Financial clarity</strong><small>Designed for trust</small></div></div></div>
      </div></section>
      <section id="community" className="section community"><div className="container"><div className="section-heading"><div className="eyebrow">WHY THIS PORTAL</div><h2>Made for the people<br/><em>who make APC Layout home.</em></h2><p>Simple, useful and community-focused — the portal will grow around the everyday needs of our residents.</p></div><div className="highlight-grid">{highlights.map(item=><article className="highlight-card" key={item.title}><div className="highlight-icon">{item.icon}</div><h3>{item.title}</h3><p>{item.text}</p><span className="card-arrow">↗</span></article>)}</div></div></section>
      <section id="updates" className="section updates"><div className="container"><div className="section-heading row-heading"><div><div className="eyebrow">FROM THE ASSOCIATION</div><h2>Latest <em>updates</em></h2></div><button className="text-button" onClick={()=>alert('Updates will be available through the resident portal.')}>View all updates <span>→</span></button></div><div className="updates-grid">{updates.map(item=><article className="update-card" key={item.title}><div className="update-meta"><span>{item.tag}</span><time>{item.date}</time></div><h3>{item.title}</h3><p>{item.text}</p><button className="read-more" onClick={()=>alert('Detailed community updates will be available soon.')}>Read more <span>→</span></button></article>)}</div></div></section>
      <section id="transparency" className="section transparency"><div className="container transparency-grid"><div><div className="eyebrow light">BUILT AROUND TRUST</div><h2>Association matters should be <em>clear.</em></h2><p>From maintenance collections to community expenses, the resident portal is designed to make association information easier to access, understand and audit.</p><div className="check-list"><div><span>✓</span> Resident payment history & receipts</div><div><span>✓</span> Maintenance outstanding visibility</div><div><span>✓</span> Community collection transparency</div><div><span>✓</span> Reports designed for annual audit</div></div></div><div className="ledger-card"><div className="ledger-head"><span>ASSOCIATION SNAPSHOT</span><span className="status-dot">● LIVE DESIGN</span></div><div className="ledger-row"><span>Maintenance</span><strong>Track collections</strong></div><div className="ledger-row"><span>Community funds</span><strong>Trace every rupee</strong></div><div className="ledger-row"><span>Expenses</span><strong>Record with vouchers</strong></div><div className="ledger-row"><span>Audit</span><strong>Ready when needed</strong></div><div className="ledger-foot">Transparency is a feature, not an afterthought.</div></div></div></section>
      <section className="portal-cta"><div className="container portal-card"><div className="portal-mark">APC</div><div><div className="eyebrow">PORTAL ACCESS</div><h2>Your community services, <em>one login away.</em></h2><p>Residents will be able to view payment history and receipts. Committee members can manage collections, expenses and reports.</p></div><button className="button dark" onClick={()=>go('login')}>Sign in <span>→</span></button></div></section>
    </main>
    <Footer go={go} scrollTo={scrollTo}/>
  </div>
}

function Footer({go,scrollTo}:{go:(v:View)=>void;scrollTo:(id:string)=>void}){
 return <footer className="footer"><div className="container footer-grid"><div className="footer-brand"><Logo/><div><strong>APC LAYOUT RESIDENTS<br/>WELFARE ASSOCIATION</strong><p>APC Layout, Thindlu<br/>Bengaluru – 560097</p></div></div><div className="footer-links"><strong>Community</strong><button onClick={()=>scrollTo('community')}>Our Community</button><button onClick={()=>scrollTo('updates')}>Updates</button><button onClick={()=>scrollTo('transparency')}>Transparency</button></div><div className="footer-links"><strong>Portal</strong><button onClick={()=>go('login')}>Resident Login</button><button onClick={()=>go('login')}>Committee Login</button><button onClick={()=>go('login')}>Help & Support</button></div></div><div className="container footer-bottom"><span>© {new Date().getFullYear()} APC Layout Residents Welfare Association</span><span>Built for our community, with care.</span></div></footer>
}

function Login({onBack,onLogin}:{onBack:()=>void;onLogin:()=>void}){
 const[role,setRole]=useState<LoginRole>('committee');
 const[username,setUsername]=useState('');
 const[password,setPassword]=useState('');
 const[showPassword,setShowPassword]=useState(false);
 const[error,setError]=useState('');
 const submit=(e:FormEvent)=>{e.preventDefault();setError('');if(role==='committee'&&username===DEMO_ADMIN.username&&password===DEMO_ADMIN.password){localStorage.setItem('apclrwa_admin_session','true');onLogin();return}setError(role==='committee'?'Invalid committee admin credentials.':'Resident login will be enabled when resident accounts are connected.')};
 return <div className="auth-page"><div className="auth-decoration auth-left"/><div className="auth-decoration auth-right"/><button className="auth-back" onClick={onBack}>← Back to website</button><div className="auth-card">
   <div className="auth-brand"><Logo/><div><strong>APC LAYOUT</strong><span>Residents Welfare Association</span></div></div>
   <div className="auth-heading"><div className="eyebrow">SECURE PORTAL ACCESS</div><h1>Welcome <em>back.</em></h1><p>Sign in to access your APC Layout community portal.</p></div>
   <div className="role-switch"><button className={role==='resident'?'active':''} onClick={()=>{setRole('resident');setError('')}}>Resident</button><button className={role==='committee'?'active':''} onClick={()=>{setRole('committee');setError('')}}>Committee</button></div>
   <form className="login-form" onSubmit={submit}>
     <label>{role==='committee'?'Committee username':'Resident email'}<input value={username} onChange={e=>setUsername(e.target.value)} placeholder={role==='committee'?'committee.admin':'your@email.com'} autoComplete="username" required/></label>
     <label>Password<div className="password-wrap"><input type={showPassword?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password" autoComplete="current-password" required/><button type="button" onClick={()=>setShowPassword(!showPassword)}>{showPassword?'Hide':'Show'}</button></div></label>
     {error&&<div className="login-error">{error}</div>}
     <button className="login-submit" type="submit">Sign in as {role==='committee'?'Committee Admin':'Resident'} <span>→</span></button>
   </form>
   {role==='committee'&&<div className="demo-credentials"><strong>Demo committee admin</strong><span>Username: <b>committee.admin</b></span><span>Password: <b>APC@Admin2026</b></span></div>}
   <div className="auth-footer">APC Layout, Thindlu • Bengaluru – 560097</div>
 </div></div>
}

function AdminDashboard({onLogout}:{onLogout:()=>void}){
 const[section,setSection]=useState('Overview');
 const nav=['Overview','Residents','Maintenance','Collections','Expenses','Bank & Cash','Reports','Audit Trail'];
 const stats=[['₹ 4.86L','Maintenance collected'],['₹ 1.24L','Outstanding maintenance'],['₹ 68,500','Festival collections'],['₹ 2.17L','Current bank balance']];
 return <div className="admin-shell">
   <aside className="admin-sidebar"><div className="admin-brand"><Logo/><div><strong>APC LAYOUT</strong><span>Committee Portal</span></div></div><div className="admin-user"><div className="admin-avatar">CA</div><div><strong>Committee Admin</strong><span>Administrator</span></div></div><nav className="admin-nav">{nav.map(item=><button key={item} className={section===item?'active':''} onClick={()=>setSection(item)}><span className="nav-icon">{({Overview:'⌂',Residents:'♙',Maintenance:'₹',Collections:'▣',Expenses:'↘','Bank & Cash':'▤',Reports:'▥','Audit Trail':'✓'} as Record<string,string>)[item]}</span>{item}</button>)}</nav><button className="admin-logout" onClick={onLogout}>↪ Sign out</button></aside>
   <main className="admin-main"><header className="admin-topbar"><button className="mobile-admin-brand" onClick={()=>setSection('Overview')}><Logo/></button><div><div className="eyebrow">APC LAYOUT • COMMITTEE PORTAL</div><h1>{section}</h1></div><div className="admin-top-actions"><span className="fy-pill">FY 2026–27</span><div className="admin-profile">CA</div></div></header>
   {section==='Overview'?<><div className="admin-welcome"><div><span className="welcome-kicker">GOOD AFTERNOON</span><h2>Welcome back, Committee Admin.</h2><p>Here's the association's financial and community snapshot.</p></div><button className="admin-primary">+ Record transaction</button></div>
   <div className="admin-stats">{stats.map(([value,label])=><div className="admin-stat" key={label}><span>{label}</span><strong>{value}</strong><small>Demo data • will come from database</small></div>)}</div>
   <div className="admin-grid"><section className="admin-panel"><div className="panel-head"><div><span>FINANCIAL ACTIVITY</span><h3>Recent transactions</h3></div><button>View ledger →</button></div><div className="transaction-list"><div><span className="txn-icon income">↓</span><div><strong>Maintenance payment</strong><small>House 24 • Receipt #REC-00124</small></div><b className="amount-positive">+ ₹8,500</b></div><div><span className="txn-icon expense">↑</span><div><strong>Garden maintenance</strong><small>Voucher #EXP-00031 • Bank</small></div><b className="amount-negative">− ₹4,200</b></div><div><span className="txn-icon income">↓</span><div><strong>Ganesha festival donation</strong><small>House 67 • Receipt #REC-00119</small></div><b className="amount-positive">+ ₹2,000</b></div><div><span className="txn-icon expense">↑</span><div><strong>Electricity bill</strong><small>Voucher #EXP-00030 • Bank</small></div><b className="amount-negative">− ₹3,840</b></div></div></section>
   <section className="admin-panel"><div className="panel-head"><div><span>ATTENTION</span><h3>Tasks to review</h3></div></div><div className="task-list"><div><i className="task-dot red"/>12 residents have maintenance outstanding</div><div><i className="task-dot gold"/>5 bank transactions need reconciliation</div><div><i className="task-dot green"/>FY 2025–26 audit pack is ready</div><div><i className="task-dot blue"/>3 new resident records to verify</div></div></section></div>
   <section className="admin-panel quick-panel"><div className="panel-head"><div><span>QUICK ACTIONS</span><h3>Common committee tasks</h3></div></div><div className="quick-actions"><button>+ Add resident</button><button>₹ Record maintenance</button><button>↓ Record collection</button><button>↗ Record expense</button><button>▣ Import bank statement</button><button>▥ Generate audit pack</button></div></section>
   </>:<section className="admin-placeholder"><div className="placeholder-icon">✦</div><div className="eyebrow">COMMITTEE MODULE</div><h2>{section}</h2><p>The {section.toLowerCase()} module is scaffolded into the committee portal. The next phase will connect this screen to the FastAPI + SQLite accounting backend.</p><button className="admin-primary" onClick={()=>setSection('Overview')}>← Back to overview</button></section>}
   <footer className="admin-footer">APC Layout Residents Welfare Association • Committee access • <button onClick={onLogout}>Sign out</button></footer>
   </main>
 </div>
}

export default function App(){
 const[signedIn,setSignedIn]=useState(()=>localStorage.getItem('apclrwa_admin_session')==='true');
 const[view,setView]=useState<View>(()=>localStorage.getItem('apclrwa_admin_session')==='true'?'admin':'home');
 const go=(next:View)=>{setView(next);window.scrollTo(0,0)};
 const login=()=>{setSignedIn(true);setView('admin');window.scrollTo(0,0)};
 const logout=()=>{localStorage.removeItem('apclrwa_admin_session');setSignedIn(false);setView('home');};
 if(signedIn&&view==='admin')return <AdminDashboard onLogout={logout}/>;
 if(view==='login')return <Login onBack={()=>go('home')} onLogin={login}/>;
 return <Home go={go}/>;
}
