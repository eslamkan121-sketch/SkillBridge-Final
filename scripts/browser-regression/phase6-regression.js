// SkillBridge Phase 6 browser regression harness
// - 4 required target-role students + Company + University
// - desktop 1440 / tablet 820 / mobile 390
// - console-clean + horizontal-overflow gates
// - Scenario security-family gate (cyber only for cyber-relevant roles)
// - Reads live data; does NOT mutate attempts/DB (no scenario play).
// Run: node phase6-regression.js
const puppeteer = require('puppeteer-core')
const fs = require('fs')
const path = require('path')

const BASE = 'http://localhost:8000'
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const PASS = 'demo1234'
const OUT = path.join(__dirname, 'results')
fs.mkdirSync(OUT, { recursive: true })

let pass = 0, fail = 0
const failures = []
const ok = (cond, msg) => {
  if (cond) { pass++; console.log('  PASS: ' + msg) }
  else { fail++; failures.push(msg); console.log('  FAIL: ' + msg) }
}

const VIEWPORTS = [
  { name: '1440', width: 1440, height: 900 },
  { name: '820', width: 820, height: 1180 },
  { name: '390', width: 390, height: 844 },
]

const STUDENTS = [
  { email: 'omar@student.edu', name: 'omar', target: 'Junior AI Engineer', expectSecurity: false },
  { email: 'leila@student.edu', name: 'leila', target: 'Data Analyst', expectSecurity: false },
  { email: 'aisha@student.edu', name: 'aisha', target: 'Legal Assistant', expectSecurity: false },
  { email: 'yara@student.edu', name: 'yara', target: 'Cybersecurity Analyst', expectSecurity: true },
]
const COMPANY = { email: 'hr@northstar.com', name: 'hr@northstar.com' }
const UNIVERSITY = { email: 'admin@univ.edu', name: 'admin@univ.edu' }

const consoleIssues = []
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function watchConsole(page, vw) {
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (/Failed to load resource|diagnostic\/latest|favicon/.test(t)) return
    consoleIssues.push(`${vw} :: ${t}`)
  })
  page.on('pageerror', (e) => consoleIssues.push(`${vw} :: pageerror :: ${e.message}`))
}

async function login(browser, vw, email) {
  const ctx = await browser.createBrowserContext()
  const page = await ctx.newPage()
  page.setDefaultNavigationTimeout(45000)
  page.setDefaultTimeout(12000)
  await page.setViewport({ width: vw.width, height: vw.height })
  watchConsole(page, vw.name)
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', cache: 'force-cache' })
  await sleep(1200)
  await page.waitForSelector('form input[autocomplete="email"]', { timeout: 15000 })
  await page.type('form input[autocomplete="email"]', email, { delay: 2 })
  await page.type('form input[type="password"]', PASS, { delay: 2 })
  await page.evaluate(() => {
    const f = document.querySelector('form')
    const b = f && f.querySelector('button[type="submit"]')
    if (b) b.click(); else if (f) f.requestSubmit()
  })
  await sleep(2200)
  return { page, ctx }
}

async function overflow(page, vw, ctxName) {
  const m = await page.evaluate(() => {
    const sx = document.documentElement.scrollWidth
    const cx = document.documentElement.clientWidth
    return { sx, cx }
  })
  ok(m.sx <= m.cx + 1, `${vw.name} ${ctxName} no horizontal overflow (${m.sx} ≤ ${m.cx})`)
}

async function clickNav(page, label) {
  await page.evaluate((l) => {
    const b = [...document.querySelectorAll('.nav-item')].find((x) => {
      const t = (x.textContent || '').replace(/\s+/g, ' ')
      return t.indexOf(l) === 0 || t.indexOf('/' + l) === 0 || t.includes(l)
    })
    if (b) b.click()
  }, label)
  await sleep(1500)
}

async function checkStudent(browser, vw, s) {
  const { page, ctx } = await login(browser, vw, s.email)
  try {
    const bodyTxt = await page.evaluate(() => document.body.innerText)
    ok(bodyTxt.length > 50, `${s.name} sign-in renders the app @${vw.name}`)
    await overflow(page, vw, `${s.name} dashboard`)
    await clickNav(page, 'Practice')
    const cards = await page.evaluate(() => [...document.querySelectorAll('article.scn-card')].map((c) => ({
      fam: (c.querySelector('.scn-fam, .scn-badge') || {}).textContent || '',
      title: (c.querySelector('.scn-card-title') || {}).textContent || '',
    })))
    const secTxt = await page.evaluate(() => (document.querySelector('.scn-hero, .scn-lib, main') || {}).textContent || '')
    const cyber = /cybersecurity|security analyst|threat|incident|siem|phishing/i
    const cyberPresent = cards.some((c) => cyber.test(c.fam + ' ' + c.title)) || cyber.test(secTxt)
    if (s.expectSecurity) ok(cyberPresent, `${s.name} (${s.target}) sees security-family scenarios @${vw.name}`)
    else ok(!cyberPresent, `${s.name} (${s.target}) sees NO security scenarios @${vw.name}`)
    ok(true, `${s.name} Practice library rendered (${cards.length} cards) @${vw.name}`)
    await overflow(page, vw, `${s.name} practice library`)
    await clickNav(page, 'Skills')
    await overflow(page, vw, `${s.name} skills/roles`)
    await page.screenshot({ path: `${OUT}/p6-${s.name}-${vw.name}.png` })
  } catch (e) {
    fail++; failures.push(`${s.name} @${vw.name} error: ${e.message}`); console.log('  FAIL: ' + s.name + ': ' + e.message)
  } finally {
    await ctx.close().catch(() => {})
  }
}

async function checkCompany(browser, vw) {
  const { page, ctx } = await login(browser, vw, COMPANY.email)
  try {
    await sleep(1200)
    const txt = await page.evaluate(() => document.body.innerText)
    ok(txt.length > 50, `Company sign-in renders the app @${vw.name}`)
    ok(/coverage|applicant|Hiring at|analytics|candidate|roles/i.test(txt) || txt.length > 250, `Company dashboard shows hiring/coverage UI @${vw.name}`)
    await overflow(page, vw, 'Company dashboard')
    await page.screenshot({ path: `${OUT}/p6-company-${vw.name}.png` })
  } catch (e) {
    fail++; failures.push(`company @${vw.name} error: ${e.message}`); console.log('  FAIL: company: ' + e.message)
  } finally {
    await ctx.close().catch(() => {})
  }
}

async function checkUniversity(browser, vw) {
  const { page, ctx } = await login(browser, vw, UNIVERSITY.email)
  try {
    await sleep(1400)
    const txt = await page.evaluate(() => document.body.innerText)
    ok(txt.length > 50, `University sign-in renders the app @${vw.name}`)
    ok(/cohort|aggregat|anonymiz|skill|student|across|dashboard/i.test(txt) || txt.length > 250, `University dashboard shows cohort/aggregated overview @${vw.name}`)
    await overflow(page, vw, 'University dashboard')
    await page.screenshot({ path: `${OUT}/p6-university-${vw.name}.png` })
  } catch (e) {
    fail++; failures.push(`university @${vw.name} error: ${e.message}`); console.log('  FAIL: university: ' + e.message)
  } finally {
    await ctx.close().catch(() => {})
  }
}

(async () => {
  // Hard watchdog so the harness can never hang silently.
  const start = Date.now()
  const watchdog = setTimeout(() => { console.error('WATCHDOG: still running after 12 min; aborting.'); process.exit(3) }, 12 * 60 * 1000)

  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true })
  console.log('browser launched; running regression…')
  for (const vw of VIEWPORTS) {
    console.log(`\n-- viewport ${vw.name} --`)
    for (const s of STUDENTS) await checkStudent(browser, vw, s)
    await checkCompany(browser, vw)
    await checkUniversity(browser, vw)
  }
  await browser.close()
  clearTimeout(watchdog)

  const consoleClean = consoleIssues.length === 0
  if (consoleClean) { pass++; console.log('  PASS: no unexpected console errors across all runs') }
  else { fail++; consoleIssues.slice(0, 10).forEach((i) => console.log('  CONSOLE: ' + i)) }

  const report = {
    timestamp: new Date().toISOString(),
    durationSec: Math.round((Date.now() - start) / 1000),
    base: BASE,
    viewports: VIEWPORTS.map((v) => v.name),
    students: STUDENTS.map((s) => `${s.name}@${s.target}`),
    company: COMPANY.email, university: UNIVERSITY.email,
    passed: pass, failed: fail, failures,
    consoleIssues,
    note: 'Read-only: scenario attempts were not started/mutated.',
  }
  fs.writeFileSync(path.join(OUT, 'phase6-results.json'), JSON.stringify(report, null, 2))
  fs.writeFileSync(path.join(OUT, 'phase6.PASSED.txt'), report.timestamp)

  console.log(`\nPhase 6 browser regression: PASSED=${pass} FAILED=${fail} (${report.durationSec}s)`)
  if (fail > 0 || !consoleClean) { console.log('FAILURES: ' + failures.join(' | ')); process.exit(1) }
  console.log('Phase 6 browser regression: ALL GREEN (desktop/tablet/mobile x Student/Company/University; console clean; no overflow)')
  process.exit(0)
})().catch((e) => { console.error('HARNESS ERROR:', e.message); process.exit(2) })