import puppeteer from 'puppeteer-core'
import { execSync } from 'child_process'

const BASE = 'http://127.0.0.1:8000'
const SHOTS = 'C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\shots'
const BRAVE = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function login (page) {
  const alreadyIn = await page.evaluate(() => !!document.querySelector('.nav-item'))
  if (!alreadyIn) {
    await page.waitForSelector('input[placeholder="you@example.com"]', { timeout: 20000 })
    await page.type('input[placeholder="you@example.com"]', 'omar@student.edu')
    await page.type('input[autocomplete="current-password"]', 'demo1234')
    await page.click('.btn-signin')
    await page.waitForSelector('.nav-item', { timeout: 30000 })
  }
  await sleep(1500)
  const hasOnboarding = await page.$('.cob-backdrop')
  if (hasOnboarding) {
    const btn = await page.$('.cob-backdrop .cob-close')
    if (btn) { await btn.click().catch(() => {}) }
    await sleep(600)
  }
}

async function sidebarInfo (page) {
  return page.evaluate(() => {
    const aside = document.querySelector('aside')
    const nav = aside ? aside.querySelector('nav') : document.querySelector('nav')
    const items = []
    if (nav) {
      nav.querySelectorAll('button.nav-item, a').forEach((el) => {
        const r = el.getBoundingClientRect()
        items.push({
          text: (el.textContent || '').trim().replace(/\s+/g, ' '),
          href: el.getAttribute('href') || null,
          top: Math.round(r.top),
          height: Math.round(r.height),
        })
      })
    }
    // geometry: equal item heights and equal gaps => no visual gap left by a removed item
    let uniform = null
    if (items.length > 1) {
      const hs = [...new Set(items.map((i) => i.height))]
      const gaps = items.slice(1).map((i, idx) => i.top - (items[idx].top + items[idx].height))
      const gs = [...new Set(gaps)]
      uniform = { equalHeights: hs.length <= 1, gaps: gs.length <= 1, heights: hs, gapValues: gs, count: items.length }
    }
    return {
      navText: (nav ? nav.innerText : '').trim(),
      items,
      uniform,
      hasCopilotLink: !!document.querySelector('a[href*="build-your-copilot"]'),
      hasCopilotNav: (nav ? nav.innerText : '').includes('AI Copilot'),
    }
  })
}

async function accountAndModal (page) {
  await page.click('.user-chip')
  await page.waitForSelector('.user-menu-popover', { timeout: 10000 })
  const accountInfo = await page.evaluate(() => {
    const pop = document.querySelector('.user-menu-popover')
    return { text: pop ? pop.innerText.trim() : null }
  })
  await page.screenshot({ path: SHOTS + '\\copilot-account-menu-1440.png', fullPage: false })
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.user-menu-popover button')].find((x) => (x.textContent || '').includes('Change your copilot'))
    if (b) b.click()
  })
  await page.waitForSelector('.csm-backdrop', { timeout: 10000 })
  await sleep(1200)
  const settingsInfo = await page.evaluate(() => {
    const shell = document.querySelector('.csm-backdrop')
    return {
      heading: shell ? shell.querySelector('.csm-h')?.textContent : null,
      optionCount: (document.querySelectorAll('.csm-name') || []).length,
      names: [...(document.querySelectorAll('.csm-name') || [])].map((n) => n.textContent.trim()),
    }
  })
  await page.screenshot({ path: SHOTS + '\\copilot-settings-modal-1440.png', fullPage: false })
  return { accountInfo, settingsInfo }
}

async function main () {
  const browser = await puppeteer.launch({
    executablePath: BRAVE,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
    userDataDir: 'C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\brave-profile-sidebar',
  })
  const page = await browser.newPage()
  const consoleErrors = []
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
  page.on('pageerror', (e) => consoleErrors.push('PAGEERROR: ' + e.message))

  // ---------- DESKTOP 1440 ----------
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
  await login(page)
  const desk = await sidebarInfo(page)
  await page.screenshot({ path: SHOTS + '\\copilot-sidebar-1440.png', fullPage: false })
  const acc = await accountAndModal(page)

  // ---------- MOBILE 390 ----------
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 })
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
  await login(page)
  // open the mobile nav drawer
  const toggle = await page.$('.nav-toggle')
  if (toggle) await toggle.click().catch(() => {})
  await sleep(700)
  const mob = await page.evaluate(() => {
    const docOverflow = document.documentElement.scrollWidth - document.documentElement.clientWidth
    const bodyOverflow = document.body.scrollWidth - document.body.clientWidth
    const aside = document.querySelector('aside')
    const nav = aside ? aside.querySelector('nav') : null
    const items = []
    if (nav) {
      nav.querySelectorAll('button.nav-item, a').forEach((el) => {
        const r = el.getBoundingClientRect()
        items.push({ text: (el.textContent || '').trim(), height: Math.round(r.height), width: Math.round(r.width), visible: r.width > 0 && r.height > 0 })
      })
    }
    return {
      viewport: document.documentElement.clientWidth,
      docOverflow, bodyOverflow,
      navItems: items,
      allVisible: items.every((i) => i.visible),
      allReadable: items.every((i) => i.visible && i.height >= 36),
      copilotVisible: items.some((i) => i.text.includes('AI Copilot')),
    }
  })
  await page.screenshot({ path: SHOTS + '\\copilot-sidebar-390.png', fullPage: false })

  await browser.close()

  // ---------- ORPHANED CSS SCAN ----------
  let orphanScan = 'not-run'
  try {
    const css = execSync('type "C:\\Users\\khale\\Downloads\\SkillBridge-Final-main\\SkillBridge-Final-main\\frontend\\src\\index.css"', { encoding: 'utf8' })
    // classes a removed nav item could have owned: any rule scoped to a copilot nav entry
    const probes = [/\.nav-copilot/, /\.sidebar[^}]*copilot/i, /\.copilot-nav/, /build-your-copilot/]
    orphanScan = probes.filter((p) => p.test(css)).map((p) => p.source)
  } catch (e) { orphanScan = 'scan-error: ' + e.message }

  const okNav = !desk.hasCopilotNav && !desk.hasCopilotLink &&
    desk.items.every((i) => !i.text.includes('AI Copilot'))
  const okGeo = desk.uniform && desk.uniform.equalHeights && desk.uniform.gaps
  const okAccount = !!(acc.accountInfo.text || '').includes('Change your copilot')
  const okSettings = acc.settingsInfo.heading === 'Change your copilot' && acc.settingsInfo.optionCount === 4
  const mobOk = mob.docOverflow <= 0 && mob.bodyOverflow <= 0 && mob.allReadable && !mob.copilotVisible
  const okOrphan = orphanScan === null || (Array.isArray(orphanScan) && orphanScan.length === 0)
  const noConsole = consoleErrors.length === 0

  console.log('=== [1440] SIDEBAR ===')
  console.log(desk.navText)
  console.log('navItems=' + JSON.stringify(desk.items))
  console.log('geometry=' + JSON.stringify(desk.uniform))
  console.log('=== [1440] ACCOUNT MENU ===')
  console.log(JSON.stringify(acc.accountInfo))
  console.log('=== [1440] SETTINGS MODAL ===')
  console.log(JSON.stringify(acc.settingsInfo))
  console.log('=== [390] MOBILE ===')
  console.log(JSON.stringify(mob, null, 2))
  console.log('=== ORPHANED-CSS PROBES (empty = none) ===')
  console.log(JSON.stringify(orphanScan))
  console.log('=== CONSOLE ERRORS ===')
  console.log(noConsole ? 'NONE' : JSON.stringify(consoleErrors, null, 2))
  console.log('CHECKS=' + JSON.stringify({
    sidebarNoCopilot: okNav,
    geometryUniform: okGeo,
    accountEntryPresent: okAccount,
    modal4Mentors: okSettings,
    mobileNoOverflowAndReadable: mobOk,
    noOrphanedCss: okOrphan,
    noConsoleErrors: noConsole,
  }, null, 2))
  const all = okNav && okGeo && okAccount && okSettings && mobOk && okOrphan && noConsole
  console.log('RESULT: ' + (all ? 'PASS' : 'FAIL'))
  process.exit(all ? 0 : 1)
}

main().catch((e) => { console.error(e); process.exit(2) })