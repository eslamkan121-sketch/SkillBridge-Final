import React, { useEffect, useState } from 'react'
import { useApp } from '../AppContext'
import { api } from '../lib/api'
import type { GoogleConfig, LocationOption, UniversityOption } from '../lib/types'
import { IconUser, IconGoogle, IconShield, IconUniversity, IconCheck, IconAlert, IconMail, IconLock } from '../components/Icons'
import { PasswordInput, ToastRegion, useToast } from '../components/ui'
import SkillBridgeJourneyHero, { STUDENT_JOURNEY } from '../components/SkillBridgeJourneyHero'

type Mode = 'signin' | 'signup' | 'reset' | 'google-role' | 'google-demo'

const EDUCATION_LEVELS = ['Undergraduate', 'Graduate', 'Bootcamp/Certificate', 'Self-taught/Independent', 'Other']

export default function LoginPage() {
  const { login, signup } = useApp()
  const [mode, setMode] = useState<Mode>('signin')
  const [google, setGoogle] = useState<GoogleConfig | null>(null)
  const [verify, setVerify] = useState<{ token: string; status: 'pending' | 'ok' | 'error' } | null>(null)

  useEffect(() => {
    const titles: Record<Mode, string> = {
      signin: 'Sign in',
      signup: 'Create account',
      reset: 'Account recovery',
      'google-role': 'Choose account type',
      'google-demo': 'Continue with Google',
    }
    document.title = `${titles[mode]} · SkillBridge`
  }, [mode])

  useEffect(() => {
    api.googleConfig()
      .then(setGoogle)
      .catch((e) => { console.error('[login] google config failed:', e) })
    const token = new URLSearchParams(window.location.search).get('token')
    if (token) {
      setVerify({ token, status: 'pending' })
      api.verifyEmail(token)
        .then(() => setVerify({ token, status: 'ok' }))
        .catch((e) => { console.error('[login] email verify failed:', e); setVerify({ token, status: 'error' }) })
    }
  }, [])

  return (
    <div className="login-split">
      <aside className="login-hero-panel">
        <div className="hero-logo">
          <div className="brand-mark">S</div>
          <span className="wordmark">SkillBridge</span>
        </div>
        <div className="hero-copy">
          <h1 className="hero-headline">
            Bridge your skills<br />to <span className="accent">your future.</span>
          </h1>
          <p className="hero-sub">SkillBridge connects what you learn<br />with real-world opportunities.</p>
        </div>
        <SkillBridgeJourneyHero data={STUDENT_JOURNEY} />
      </aside>

      <main className="login-form-panel">
        <div className="login-card-wrap">
          {verify && <VerifyBanner verify={verify} />}
          <AuthCard mode={mode} setMode={setMode} login={login} signup={signup} google={google} />
        </div>
      </main>
    </div>
  )
}

function VerifyBanner({ verify }: { verify: { token: string; status: 'pending' | 'ok' | 'error' } }) {
  if (verify.status === 'pending') {
    return <div className="info" style={{ marginBottom: 14, justifyContent: 'center' }}><IconShield size={16} /> Verifying your email…</div>
  }
  if (verify.status === 'ok') {
    return <div className="info ok" style={{ marginBottom: 14, justifyContent: 'center' }}><IconCheck size={16} /> Your email is verified. You can now sign in.</div>
  }
  return <div className="error" style={{ marginBottom: 14 }}>This verification link is invalid or has expired.</div>
}

function AuthCard({ mode, setMode, login, signup, google }: any) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('Student')
  const [university, setUniversity] = useState('')
  const [country, setCountry] = useState('')
  const [customUniversity, setCustomUniversity] = useState('')
  const [educationLevel, setEducationLevel] = useState('')
  const [industry, setIndustry] = useState('')
  const [location, setLocation] = useState('')
  const [universities, setUniversities] = useState<UniversityOption[]>([])
  const [locations, setLocations] = useState<LocationOption[]>([])
  const [verifyNotice, setVerifyNotice] = useState('')
  const [pending, setPending] = useState<any>(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const [fieldErrs, setFieldErrs] = useState<Record<string, string>>({})
  const toast = useToast()

  useEffect(() => {
    api.universities()
      .then(setUniversities)
      .catch((e) => { console.error('[signup] universities failed:', e); setFieldErrs((f) => ({ ...f, country: 'Could not load universities.' })) })
    api.locations()
      .then(setLocations)
      .catch((e) => { console.error('[signup] locations failed:', e) })
  }, [])

  const switchMode = (m: Mode) => { setMode(m); setError(''); setInfo(''); setVerifyNotice(''); setFieldErrs({}) }

  const selectedCountryUnis = () => {
    const g = universities.find((x) => x.country === country)
    return g ? g.universities : []
  }

  const selectedCountryCities = () => {
    const g = locations.find((x) => x.country === country)
    return g ? g.cities : []
  }

  const doLogin = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError('')
    const errs: Record<string, string> = {}
    if (!email.trim()) errs.email = 'Please enter your email.'
    if (!password) errs.password = 'Please enter your password.'
    setFieldErrs(errs)
    if (Object.keys(errs).length) return
    setBusy(true)
    try { await login(email.trim(), password) }
    catch (err: any) { setError(err.message || 'Login failed') }
    finally { setBusy(false) }
  }

  const doSignup = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError(''); setVerifyNotice('')
    const errs: Record<string, string> = {}
    if (!displayName.trim()) errs.displayName = 'Please enter your full name.'
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) errs.email = 'Enter a valid email address.'
    if (password.length < 8) errs.password = 'Password must be at least 8 characters.'
    if (role === 'Company' && !industry.trim()) errs.industry = 'Please enter your industry.'
    if (role === 'Student' && !educationLevel) errs.educationLevel = 'Please choose your education level.'
    if (!location.trim()) errs.location = 'Please enter your city so we can show you roles near you.'
    setFieldErrs(errs)
    if (Object.keys(errs).length) return
    setBusy(true)
    try {
      const isStudent = role === 'Student'
      const isAdmin = role === 'University Admin'
      const uni = university === '__other__' ? customUniversity.trim() : university === '__independent__' ? '' : university
      const res = await signup(email.trim(), password, displayName.trim(), role,
        isStudent || isAdmin ? uni : undefined, isStudent || isAdmin ? country : undefined,
        role === 'Company' ? industry.trim() : undefined,
        location.trim(),
        isStudent || isAdmin ? educationLevel : undefined)
      toast.push('Account created successfully.', 'success')
      if (res.email_verified_delivery) {
        // SMTP is configured: the user must verify their email before using the account.
        setVerifyNotice(`A verification email was sent to ${email.trim()}. Please click the link in it to activate your account.`)
      }
    } catch (err: any) { setError(err.message || 'Sign-up failed') }
    finally { setBusy(false) }
  }

  const doResetRequest = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError(''); setInfo(''); setBusy(true)
    try {
      const r = await api.resetRequest(email.trim())
      setInfo(r.message || 'Check your email for a reset link.')
      setMode('reset')
    } catch (err: any) { setError(err.message) }
    finally { setBusy(false) }
  }

  const doGoogle = async () => {
    setError('')
    if (google?.configured) { window.location.href = '/api/auth/google/login'; return }
    // demo identity provider
    setPending({ email: email.trim() || (displayName + '@demo.student.edu').toLowerCase() })
    switchMode('google-demo')
  }

  const doGoogleDemo = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError(''); setBusy(true)
    try {
      const res = await api.googleDemo(pending?.email, displayName.trim() || 'Demo User')
      if (res.registered) { window.location.reload() }
      else { setPending(res); switchMode('google-role') }
    } catch (err: any) { setError(err.message) }
    finally { setBusy(false) }
  }

  const doGoogleRole = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setError('')
    const errs: Record<string, string> = {}
    if ((role === 'Student' || role === 'University Admin') && !country) errs.country = 'Please choose a country.'
    if (role === 'University Admin' && !university) errs.university = 'Please choose a university.'
    if (role === 'Student' && !educationLevel) errs.educationLevel = 'Please choose your education level.'
    if (role === 'Company' && !industry.trim()) errs.industry = 'Please enter your industry.'
    if (!location.trim()) errs.location = 'Please enter your city so we can show you roles near you.'
    setFieldErrs(errs)
    if (Object.keys(errs).length) return
    setBusy(true)
    try {
      const uni = university === '__other__' ? customUniversity.trim() : university === '__independent__' ? '' : university
      await api.googleComplete(pending.google_sub, role, { university: uni, country, industry: industry.trim(), location: location.trim(), education_level: educationLevel })
      window.location.reload()
    } catch (err: any) { setError(err.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="login-card">
      <h1 className="lc-heading">{mode === 'signin' ? 'Welcome back' : mode === 'signup' ? 'Create your account' : 'Account recovery'}</h1>
      <p className="lc-sub">
        {mode === 'signin' ? 'Bridge university learning to real-world work.' : mode === 'signup' ? 'Join students, companies, and universities on one platform.' : 'We\u2019ll send you a link to reset your password.'}
      </p>

      {mode === 'signup' && (
        <div className="tabs">
          <button className={mode === 'signin' ? 'active' : ''} onClick={() => switchMode('signin')}>Sign in</button>
          <button className={mode === 'signup' ? 'active' : ''} onClick={() => switchMode('signup')}>Create account</button>
        </div>
      )}

      {mode === 'signin' && (
        <form onSubmit={doLogin} noValidate>
          <div className={`field ${fieldErrs.email ? 'invalid' : ''}`}><label>Email address</label>
            <div className="field-icon-wrap">
              <IconMail size={16} className="field-icon" />
              <input value={email} onChange={(e) => { setEmail(e.target.value); if (fieldErrs.email) setFieldErrs((f) => ({ ...f, email: '' })) }} autoComplete="email" placeholder="you@example.com" />
            </div>
            {fieldErrs.email && <span className="field-err">{fieldErrs.email}</span>}</div>
          <div className={`field ${fieldErrs.password ? 'invalid' : ''}`}><label>Password</label>
            <PasswordInput value={password} onChange={(v) => { setPassword(v); if (fieldErrs.password) setFieldErrs((f) => ({ ...f, password: '' })) }} autoComplete="current-password" icon={<IconLock size={16} className="field-icon" />} />
            {fieldErrs.password && <span className="field-err">{fieldErrs.password}</span>}</div>
          {error && <div className="error">{error}</div>}
          <div className="login-remember-row">
            <label><input type="checkbox" /> Remember me</label>
            <button type="button" className="link" onClick={() => switchMode('reset')}>Forgot password?</button>
          </div>
          <button className="btn btn-primary btn-signin" disabled={busy}>
            <IconUser size={15} /> {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <div className="divider">or continue with</div>
          <button type="button" className="btn btn-google" onClick={doGoogle}>
            <IconGoogle size={16} /> {google?.configured ? 'Continue with Google' : 'Continue with Google (demo)'}
          </button>
          <div className="login-footer-line">
            Don't have an account? <button type="button" className="link" onClick={() => switchMode('signup')}>Create account</button>
          </div>
        </form>
      )}

      {mode === 'signup' && (
        <form onSubmit={doSignup} noValidate>
          <div className={`field ${fieldErrs.displayName ? 'invalid' : ''}`}><label>Full name</label>
            <input value={displayName} onChange={(e) => { setDisplayName(e.target.value); if (fieldErrs.displayName) setFieldErrs((f) => ({ ...f, displayName: '' })) }} autoComplete="name" />
            {fieldErrs.displayName && <span className="field-err">{fieldErrs.displayName}</span>}</div>
          <div className={`field ${fieldErrs.email ? 'invalid' : ''}`}><label>Email</label>
            <input value={email} onChange={(e) => { setEmail(e.target.value); if (fieldErrs.email) setFieldErrs((f) => ({ ...f, email: '' })) }} autoComplete="email" />
            {fieldErrs.email && <span className="field-err">{fieldErrs.email}</span>}</div>
          <div className={`field ${fieldErrs.password ? 'invalid' : ''}`}><label>Password <span className="muted small">(8+ characters)</span></label>
            <PasswordInput value={password} onChange={(v) => { setPassword(v); if (fieldErrs.password) setFieldErrs((f) => ({ ...f, password: '' })) }} autoComplete="new-password" />
            {fieldErrs.password && <span className="field-err">{fieldErrs.password}</span>}</div>
          <div className="field">
            <label>I am a…</label>
            <select value={role} onChange={(e) => { setRole(e.target.value); setCountry(''); setUniversity(''); setCustomUniversity('') }}>
              <option value="Student">Student seeking roles</option>
              <option value="Company">Company hiring talent</option>
              <option value="University Admin">University administration</option>
            </select>
          </div>
          {role === 'Company' ? (
            <div className={`field ${fieldErrs.location ? 'invalid' : ''}`}><label>City (location) <span className="muted small">roles near you</span></label>
              <input value={location} onChange={(e) => { setLocation(e.target.value); if (fieldErrs.location) setFieldErrs((f) => ({ ...f, location: '' })) }} autoComplete="address-level2" placeholder="e.g. Birmingham" />
              {fieldErrs.location && <span className="field-err">{fieldErrs.location}</span>}</div>
          ) : (
            <div className="university-picker">
              <div className="field">
                <label>Country</label>
                <select value={country} onChange={(e) => { setCountry(e.target.value); setLocation(''); setUniversity(''); setCustomUniversity('') }}>
                  <option value="">Select a country…</option>
                  {universities.map((u) => <option key={u.country} value={u.country}>{u.country}</option>)}
                </select>
              </div>
              {country && (
                <div className={`field ${fieldErrs.location ? 'invalid' : ''}`}>
                  <label>City</label>
                  <select value={location} onChange={(e) => { setLocation(e.target.value); if (fieldErrs.location) setFieldErrs((f) => ({ ...f, location: '' })) }}>
                    <option value="">Select a city…</option>
                    {selectedCountryCities().map((ct) => <option key={ct} value={ct}>{ct}</option>)}
                  </select>
                  {fieldErrs.location && <span className="field-err">{fieldErrs.location}</span>}
                </div>
              )}
              {country && role !== 'Company' && (
                <div className="field">
                  <label>
                    University
                    {role === 'Student' && <span className="muted small"> (optional)</span>}
                  </label>
                  <select value={university} onChange={(e) => setUniversity(e.target.value)}>
                    <option value="">{role === 'Student' ? 'Select a university or choose below…' : 'Select a university…'}</option>
                    {selectedCountryUnis().map((un) => <option key={un} value={un}>{un}</option>)}
                    {role === 'Student' && <option value="__independent__">Not affiliated with a university / Independent learner</option>}
                    <option value="__other__">Other (not listed)</option>
                  </select>
                </div>
              )}
              {country && university === '__other__' && (
                <div className="field">
                  <label>University name</label>
                  <input value={customUniversity} onChange={(e) => setCustomUniversity(e.target.value)} placeholder="Type your university…" />
                </div>
              )}
              {role !== 'Company' && (
                <div className={`field ${fieldErrs.educationLevel ? 'invalid' : ''}`}>
                  <label>Education level <span className="muted small">(required)</span></label>
                  <select value={educationLevel} onChange={(e) => { setEducationLevel(e.target.value); if (fieldErrs.educationLevel) setFieldErrs((f) => ({ ...f, educationLevel: '' })) }}>
                    <option value="">Select your education level…</option>
                    {EDUCATION_LEVELS.map((lvl) => <option key={lvl} value={lvl}>{lvl}</option>)}
                  </select>
                  {fieldErrs.educationLevel && <span className="field-err">{fieldErrs.educationLevel}</span>}
                </div>
              )}
            </div>
          )}
          {role === 'Company' && (
            <div className={`field ${fieldErrs.industry ? 'invalid' : ''}`}><label>Industry</label>
              <input value={industry} onChange={(e) => { setIndustry(e.target.value); if (fieldErrs.industry) setFieldErrs((f) => ({ ...f, industry: '' })) }} placeholder="AI / Software" />
              {fieldErrs.industry && <span className="field-err">{fieldErrs.industry}</span>}</div>
          )}
          {verifyNotice && <div className="info" style={{ whiteSpace: 'normal' }}><IconShield size={15} /> {verifyNotice}</div>}
          {error && <div className="error">{error}</div>}
          <button className="btn btn-primary btn-signin" disabled={busy}>
            {busy ? 'Creating account…' : 'Create account'}
          </button>
          <div className="login-links">
            <button type="button" className="link" onClick={() => switchMode('signin')}>Already have an account? Sign in</button>
          </div>
        </form>
      )}

      {mode === 'reset' && (
        <form onSubmit={doResetRequest}>
          <div className="field"><label>Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></div>
          {info && <div className="info">{info}</div>}
          {error && <div className="error">{error}</div>}
          <button className="btn btn-primary btn-signin" disabled={busy}>
            Send reset link
          </button>
          <div className="login-links">
            <button type="button" className="link" onClick={() => switchMode('signin')}>Back to sign in</button>
          </div>
        </form>
      )}

      {mode === 'google-demo' && (
        <form onSubmit={doGoogleDemo}>
          <div className="field"><label>Google account email</label>
            <input value={pending?.email || ''} onChange={(e) => setPending({ ...pending, email: e.target.value })} /></div>
          <div className="field"><label>Display name</label>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></div>
          {error && <div className="error">{error}</div>}
          <button className="btn btn-google" disabled={busy}>
            <IconGoogle size={16} /> {busy ? 'Continuing…' : 'Continue with Google'}
          </button>
        </form>
      )}

      {mode === 'google-role' && (
        <form onSubmit={doGoogleRole} noValidate>
          <div className="info">You're new here — pick the account type for <strong>{pending?.email}</strong>.</div>
          <div className="field"><label>I am a…</label>
            <select value={role} onChange={(e) => { setRole(e.target.value); setCountry(''); setLocation(''); setUniversity(''); setCustomUniversity(''); setIndustry('') }}>
              <option value="Student">Student seeking roles</option>
              <option value="Company">Company hiring talent</option>
              <option value="University Admin">University administration</option>
            </select>
          </div>
          {role === 'Company' ? (
            <div className={`field ${fieldErrs.location ? 'invalid' : ''}`}><label>City (location) <span className="muted small">roles near you</span></label>
              <input value={location} onChange={(e) => { setLocation(e.target.value); if (fieldErrs.location) setFieldErrs((f) => ({ ...f, location: '' })) }} autoComplete="address-level2" placeholder="e.g. Birmingham" />
              {fieldErrs.location && <span className="field-err">{fieldErrs.location}</span>}</div>
          ) : (
            <div className="university-picker">
              <div className={`field ${fieldErrs.country ? 'invalid' : ''}`}>
                <label>Country</label>
                <select value={country} onChange={(e) => { setCountry(e.target.value); setLocation(''); setUniversity(''); setCustomUniversity(''); if (fieldErrs.country) setFieldErrs((f) => ({ ...f, country: '' })) }}>
                  <option value="">Select a country…</option>
                  {universities.map((u) => <option key={u.country} value={u.country}>{u.country}</option>)}
                </select>
                {fieldErrs.country && <span className="field-err">{fieldErrs.country}</span>}
              </div>
              {country && (
                <div className={`field ${fieldErrs.location ? 'invalid' : ''}`}>
                  <label>City</label>
                  <select value={location} onChange={(e) => { setLocation(e.target.value); if (fieldErrs.location) setFieldErrs((f) => ({ ...f, location: '' })) }}>
                    <option value="">Select a city…</option>
                    {selectedCountryCities().map((ct) => <option key={ct} value={ct}>{ct}</option>)}
                  </select>
                  {fieldErrs.location && <span className="field-err">{fieldErrs.location}</span>}
                </div>
              )}
              {country && (
                <div className={`field ${fieldErrs.university ? 'invalid' : ''}`}>
                  <label>
                    University
                    {role === 'Student' && <span className="muted small"> (optional)</span>}
                  </label>
                  <select value={university} onChange={(e) => { setUniversity(e.target.value); if (fieldErrs.university) setFieldErrs((f) => ({ ...f, university: '' })) }}>
                    <option value="">{role === 'Student' ? 'Select a university or choose below…' : 'Select a university…'}</option>
                    {selectedCountryUnis().map((un) => <option key={un} value={un}>{un}</option>)}
                    {role === 'Student' && <option value="__independent__">Not affiliated with a university / Independent learner</option>}
                    <option value="__other__">Other (not listed)</option>
                  </select>
                  {fieldErrs.university && <span className="field-err">{fieldErrs.university}</span>}
                </div>
              )}
              {country && university === '__other__' && (
                <div className="field">
                  <label>University name</label>
                  <input value={customUniversity} onChange={(e) => setCustomUniversity(e.target.value)} placeholder="Type your university…" />
                </div>
              )}
              {role !== 'Company' && (
                <div className={`field ${fieldErrs.educationLevel ? 'invalid' : ''}`}>
                  <label>Education level <span className="muted small">(required)</span></label>
                  <select value={educationLevel} onChange={(e) => { setEducationLevel(e.target.value); if (fieldErrs.educationLevel) setFieldErrs((f) => ({ ...f, educationLevel: '' })) }}>
                    <option value="">Select your education level…</option>
                    {EDUCATION_LEVELS.map((lvl) => <option key={lvl} value={lvl}>{lvl}</option>)}
                  </select>
                  {fieldErrs.educationLevel && <span className="field-err">{fieldErrs.educationLevel}</span>}
                </div>
              )}
            </div>
          )}
          {role === 'Company' && (
            <div className={`field ${fieldErrs.industry ? 'invalid' : ''}`}><label>Industry</label>
              <input value={industry} onChange={(e) => { setIndustry(e.target.value); if (fieldErrs.industry) setFieldErrs((f) => ({ ...f, industry: '' })) }} placeholder="AI / Software" />
              {fieldErrs.industry && <span className="field-err">{fieldErrs.industry}</span>}</div>
          )}
          {error && <div className="error">{error}</div>}
          <button className="btn btn-google" disabled={busy}>
            <IconGoogle size={16} /> Create account
          </button>
          <div className="login-links">
            <button type="button" className="link" onClick={() => switchMode('signin')}>Cancel</button>
          </div>
        </form>
      )}
      <ToastRegion toasts={toast.toasts} dismiss={toast.dismiss} />
    </div>
  )
}
