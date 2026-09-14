import React from 'react'
import { AppProvider, useApp } from './AppContext'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import SkillsRolesPage from './pages/SkillsRolesPage'
import LearningPage from './pages/LearningPage'
import ScenariosPage from './pages/ScenariosPage'
import AssessmentsPage from './pages/AssessmentsPage'
import UniversityPage from './pages/UniversityPage'
import PublicProfilePage from './pages/PublicProfilePage'
import { api } from './lib/api'
import { IconDashboard, IconRoles, IconLearning, IconAssessment, IconUniversity, IconLogout, IconAlert, IconTarget, IconBell, IconChevron, IconBolt, IconSparkles } from './components/Icons'
import SuccessAnimationOverlay from './components/SuccessAnimationOverlay'
import ErrorBoundary from './components/ErrorBoundary'
import { CopilotPanel } from './components/CopilotPanel'
import CopilotOnboarding from './components/CopilotOnboarding'
import CopilotSettingsModal from './components/CopilotSettingsModal'

type Section = 'dashboard' | 'skills' | 'learning' | 'scenarios' | 'assessments' | 'university'

function avatarInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  const first = parts[0][0]
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

function NotFound() {
  return (
    <div className="app-shell">
      <main className="content notfound-wrap">
        <div className="notfound">
          <div className="nf-code">404</div>
          <h1>Page not found</h1>
          <p>The page you're looking for doesn't exist or was moved.</p>
          <button className="btn btn-primary" onClick={() => { window.location.href = '/' }}>Back to SkillBridge</button>
        </div>
      </main>
    </div>
  )
}

function Shell() {
  const { session, me, logout, authBanner, clearAuthBanner, assessmentActive } = useApp()
  const [section, setSection] = React.useState<Section>('dashboard')
  const [navOpen, setNavOpen] = React.useState(false)
  const [notifOpen, setNotifOpen] = React.useState(false)
  const [userMenuOpen, setUserMenuOpen] = React.useState(false)
  const [learningFocus, setLearningFocus] = React.useState<{ skillId: number; roleTitle: string } | null>(null)
  const [prevSection, setPrevSection] = React.useState<Section | null>(null)
  const [demo, setDemo] = React.useState<{ genai_enabled: boolean; email_configured: boolean } | null>(null)
  const [copilotSettingsOpen, setCopilotSettingsOpen] = React.useState(false)
  const [copilotOnboardingForce, setCopilotOnboardingForce] = React.useState(false)

  React.useEffect(() => {
    api.demoMode().then(setDemo).catch((e) => console.error('[app] demo-mode config failed:', e))
  }, [])

  React.useEffect(() => {
    const close = () => { setNotifOpen(false); setUserMenuOpen(false) }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [])

  const titles: Record<Section, string> = {
    dashboard: 'Dashboard', skills: 'Skills & Roles', learning: 'Learning', scenarios: 'Practice Scenarios',
    assessments: 'Assessments', university: 'University Dashboard',
  }
  React.useEffect(() => {
    document.title = `${titles[section]} · SkillBridge`
  }, [section])

  if (!session) return <LoginPage />

  const role = session.role
  const studentId = role === 'Student' ? (session.student?.id ?? 0) : 0
  const nav: { key: Section; label: string; icon: React.ReactNode; show: boolean; href?: string }[] = [
    { key: 'dashboard', label: 'Dashboard', icon: <IconDashboard size={18} />, show: true },
    { key: 'skills', label: 'Skills & Roles', icon: <IconRoles size={18} />, show: true },
    { key: 'learning', label: 'Learning', icon: <IconLearning size={18} />, show: role === 'Student' },
    { key: 'scenarios', label: 'Practice', icon: <IconBolt size={18} />, show: role === 'Student' },
    { key: 'assessments', label: 'Assessments', icon: <IconAssessment size={18} />, show: role === 'Student' },
    { key: 'university', label: 'University Dashboard', icon: <IconUniversity size={18} />, show: role === 'University Admin' },
  ]
  const visibleNav = nav.filter((n) => n.show)
  if (!visibleNav.some((n) => n.key === section)) setSection(visibleNav[0]?.key || 'dashboard')

  const goTo = (key: Section) => { setPrevSection(section); setSection(key); setNavOpen(false) }

  // Cross-page deep link: Skills & Roles / Dashboard / scenario results ask the
  // destination page to open a specific skill, with the role that motivated it
  // as context. The previous section is kept so every page can offer a
  // predictable "Back to ..." action (browser Back still behaves normally).
  //
  // Phase 5 contract: the focus object is consumed by whichever page mounts,
  // then cleared via onFocusConsumed — no URL params, no navigation loops.
  const navigate = (dest: string, focus?: { skillId: number; roleTitle: string }) => {
    // A journey roots itself at the hub it started from (Skills & Roles or the
    // Dashboard). Moves between deep-link pages (learning <-> scenarios ->
    // assessments) keep that back-context, so breadcrumbs never spiral into a
    // learning<->scenarios loop. The navbar uses goTo() and resets the target.
    if (section === 'skills' || section === 'dashboard') setPrevSection(section)
    setSection(dest as Section)
    setNavOpen(false)
    if (focus) setLearningFocus(focus)
  }

  const roleLabel =
    role === 'Student'
      ? me?.student?.target_role ? `Target · ${me.student.target_role.title}` : 'Set your target role'
      : role === 'Company'
        ? me?.company ? `Hiring at ${me.company.name}` : 'Company account'
        : 'Administrator'
  const roleClass = role === 'Student' ? 'student' : role === 'Company' ? 'company' : 'university'

  const backTo = prevSection ? { key: prevSection, label: titles[prevSection] } : null

  return (
    <>
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className={`sidebar ${navOpen ? 'nav-open' : ''}`}>
        <div className="brand-block" onClick={() => goTo('dashboard')} role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') goTo('dashboard') }}>
          <div className="brand-mark">S</div>
          <div>
            <div className="eyebrow">Career Intelligence</div>
            <span className="sidebar-wordmark">SkillBridge</span>
          </div>
        </div>
        <button className="nav-close" aria-label="Close menu" onClick={() => setNavOpen(false)}>✕</button>
        <nav className="main-nav">
          {visibleNav.map((n) => (
            n.href ? (
              <a
                key={n.key}
                className="nav-item"
                href={n.href}
                onClick={() => setNavOpen(false)}
              >
                {n.icon} {n.label}
              </a>
            ) : (
            <button
              key={n.key}
              className={`nav-item ${section === n.key ? 'active' : ''}`}
              aria-current={section === n.key ? 'page' : undefined}
              onClick={() => goTo(n.key)}
            >
              {n.icon} {n.label}
            </button>
            )
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="role-badge">
          <div>
            <span className="rb-label">Signed in as</span>
            <strong style={{ fontSize: 12.5 }}>{me?.display_name || session.display_name}</strong>
            <div style={{ fontSize: 11, opacity: 0.7 }}>{session.role}</div>
          </div>
        </div>
      </aside>
      <div className={`nav-backdrop ${navOpen ? 'visible' : ''}`} onClick={() => setNavOpen(false)} />
        <main className="content" id="main-content">
          {demo && (!demo.genai_enabled || !demo.email_configured) && (
            <div className="demo-banner">
              <IconAlert size={15} />
              <span>
                {!demo.genai_enabled && !demo.email_configured
                  ? 'Demo mode: no GenAI API key or email (SMTP) configured — AI output uses the deterministic fallback and reset links are not emailed.'
                  : !demo.genai_enabled
                    ? 'Demo mode: no GenAI API key configured — AI-generated content uses the deterministic fallback.'
                    : 'Demo mode: no email (SMTP) configured — password-reset links are not emailed.'}
              </span>
            </div>
          )}
          <header className="topbar">
          <div>
            <button className="nav-toggle" aria-label="Open menu" onClick={() => setNavOpen(true)}>☰</button>
            <div>
              <p className="eyebrow">Verified skill loop</p>
              <h2>{titles[section]}</h2>
            </div>
          </div>
          <div className="topbar-actions">
            <span className={`role-chip status-chip ${roleClass}`}>
              {role === 'Student' && <IconTarget size={13} />}
              {roleLabel}
            </span>
            <div className="topbar-popover-anchor">
              <button className="topbar-bell" aria-label="Notifications — coming soon" aria-expanded={notifOpen}
                onClick={(e) => { e.stopPropagation(); setNotifOpen((v) => !v) }}>
                <IconBell size={17} />
                <span className="soon-badge" aria-hidden="true">Coming soon</span>
                {notifOpen && <span className="popover-caret" />}
              </button>
              {notifOpen && (
                <div className="topbar-popover notif-popover" role="dialog" aria-label="Notifications">
                  <div className="popover-title">Notifications</div>
                  <p className="popover-empty"><strong>Coming soon.</strong> This is a placeholder — in-app alerts are not wired to real activity yet, so nothing here is live.</p>
                </div>
              )}
            </div>
            <div className="topbar-popover-anchor">
              <button className="user-chip" aria-label={`Account menu for ${me?.display_name || session.display_name}`}
                title={me?.display_name || session.display_name}
                aria-haspopup="menu" aria-expanded={userMenuOpen}
                onClick={(e) => { e.stopPropagation(); setUserMenuOpen((v) => !v) }}>
                <span className="avatar">{avatarInitials(me?.display_name || session.display_name)}</span>
                <span className="user-chip-name">{me?.display_name || session.display_name}</span>
                <IconChevron size={13} className={`user-chev ${userMenuOpen ? 'open' : ''}`} />
              </button>
              {userMenuOpen && (
                <div className="topbar-popover user-menu-popover" role="menu" aria-label="Account menu">
                  <div className="popover-title">Signed in as</div>
                  <p className="popover-meta">{me?.display_name || session.display_name}</p>
                  <p className="popover-meta">{session.role}</p>
                  {role === 'Student' && (
                    <button
                      className="btn btn-ghost popover-logout"
                      role="menuitem"
                      onClick={() => { setUserMenuOpen(false); setCopilotSettingsOpen(true); setCopilotOnboardingForce(false) }}
                    ><IconSparkles size={15} /> Change your copilot</button>
                  )}
                  <button className="btn btn-ghost popover-logout" role="menuitem" onClick={logout}><IconLogout size={15} /> Log out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        {section === 'dashboard' && <DashboardPage onNavigate={navigate} />}
        {section === 'skills' && <SkillsRolesPage onNavigate={navigate} backTo={backTo} />}
        {section === 'learning' && <LearningPage onNavigate={navigate} initialFocus={learningFocus} onFocusConsumed={() => setLearningFocus(null)} backTo={backTo} />}
        {section === 'scenarios' && <ScenariosPage onNavigate={navigate} initialFocus={learningFocus} onFocusConsumed={() => setLearningFocus(null)} backTo={backTo} />}
        {section === 'assessments' && <AssessmentsPage onNavigate={navigate} initialSkillId={learningFocus?.skillId ?? undefined} onFocusConsumed={() => setLearningFocus(null)} backTo={backTo} />}
        {section === 'university' && <UniversityPage />}
        <footer className="app-footer">
          <span>SkillBridge · Career Intelligence Platform</span>
          <span>© {new Date().getFullYear()} SkillBridge. All rights reserved.</span>
        </footer>
      </main>
    </div>
    {role === 'Student' && !assessmentActive && <CopilotPanel />}
    {role === 'Student' && !assessmentActive && !authBanner && studentId > 0 && (
      <>
        <CopilotOnboarding
          studentId={studentId}
          forceOpen={copilotOnboardingForce}
          onDone={() => setCopilotOnboardingForce(false)}
        />
        <CopilotSettingsModal
          studentId={studentId}
          open={copilotSettingsOpen}
          onClose={() => setCopilotSettingsOpen(false)}
          onRetakeQuiz={() => { setCopilotSettingsOpen(false); setCopilotOnboardingForce(true) }}
        />
      </>
    )}
    {session && authBanner && (
      <SuccessAnimationOverlay role={role} onDone={clearAuthBanner} />
    )}
    </>
  )
}

export default function App() {
  const m = window.location.pathname.match(/^\/p\/(\d+)/)
  if (m) return <PublicProfilePage studentId={Number(m[1])} />
  if (window.location.pathname.startsWith('/p/')) return <NotFound />
  return (
    <AppProvider>
      <ErrorBoundary>
        <Shell />
      </ErrorBoundary>
    </AppProvider>
  )
}
