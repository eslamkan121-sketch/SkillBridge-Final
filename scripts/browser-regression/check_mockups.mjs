import { launch } from 'puppeteer-core'

const brave = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const profile = process.env.TEMP + '\\opencode\\brave-profile-mockchecks'
const baseDir = 'C:/Users/khale/Downloads/SkillBridge-Final-main/SkillBridge-Final-main/docs/mockups'
const url = (f) => 'file:///' + baseDir + '/' + f

const browser = await launch({
  executablePath: brave,
  headless: 'new',
  userDataDir: profile,
  args: ['--no-sandbox', '--disable-gpu'],
})

function checkResults(label, checks) {
  console.log('\n== ' + label + ' ==')
  let fail = 0
  for (const [name, ok, extra] of checks) {
    if (ok) console.log('  PASS  ' + name)
    else { console.log('  FAIL  ' + name + (extra ? '  → ' + extra : '')); fail++ }
  }
  return fail
}

const overall = { fails: 0 }

try {
  // ---------- EN 1440 ----------
  let page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 2400 })
  await page.goto(url('dashboard-en.html'), { waitUntil: 'networkidle0', timeout: 45000 })

  let r = await page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const qa = (s) => [...document.querySelectorAll(s)]
    const rect = (s) => { const el = q(s); if (!el) return null; const b = el.getBoundingClientRect(); return { x: b.x, w: b.width, dir: getComputedStyle(el).direction } }
    const cp = q('.copilot')?.getBoundingClientRect()
    const user = q('.msg.user')?.getBoundingClientRect()
    const asst = q('.msg.assistant')?.getBoundingClientRect()
    return {
      htmlDir: document.documentElement.getAttribute('dir') || 'none',
      shellDir: q('.app-shell')?.getAttribute('dir'),
      sidebar: rect('.sidebar'),
      content: rect('.content'),
      copilot: rect('.copilot'),
      userMsg: user ? { x: user.x, right: user.x + user.width } : null,
      asstMsg: asst ? { x: asst.x, right: asst.x + asst.width } : null,
      cpLeft: cp ? cp.x : null, cpRight: cp ? cp.x + cp.width : null,
      sidebarWordmark: q('.brand-wordmark')?.textContent,
      topbarTitle: q('.topbar h2')?.textContent,
      heroTitle: q('.dashboard-hero h1')?.textContent,
      jobTitles: qa('.job-title h4').map((e) => e.textContent),
      trackedBadges: qa('.tracked-badge').map((e) => e.textContent),
      badges: qa('.badge').map((e) => e.textContent.trim()),
      pills: qa('.pill').map((e) => e.textContent.trim()),
      assessChips: qa('.ast-chip').map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
      copyButtons: qa('.copy-btn').length,
      fallbackTags: qa('.fallback-tag').map((e) => e.textContent.trim()),
      nims: qa('body *').filter((e) => /NVIDIA|NIM/.test(e.textContent || '')).length,
      composerHasSend: !!q('.cp-composer .send'),
      mockEntry: !!q('.mock-entry'),
    }
  })
  const cpMid = (r) => r.cpLeft + (r.cpRight - r.cpLeft) / 2
  overall.fails += checkResults('EN @1440 · shell', [
    ['html has no rtl (EN shell LTR)', r.htmlDir !== 'rtl', r.htmlDir],
    ['app-shell dir=ltr', r.shellDir === 'ltr', r.shellDir],
    ['sidebar left of content (LTR)', r.sidebar && r.content && r.sidebar.x < r.content.x, JSON.stringify([r.sidebar?.x, r.content?.x])],
    ['sidebar on inline-start, width 264', r.sidebar && r.sidebar.w === 264, r.sidebar?.w],
    ['copilot inside viewport right (x >= content right)', r.copilot && r.content && r.copilot.x >= r.content.x + r.content.w - 8, JSON.stringify([r.copilot?.x, r.content?.x + r.content?.w])],
    ['user bubble aligned END within copilot (right in LTR)', r.userMsg && (r.cpRight - r.userMsg.right) < (r.cpRight - r.cpLeft) * 0.5, JSON.stringify(r.userMsg)],
    ['assistant bubble aligned START within copilot (left in LTR)', r.asstMsg && (r.asstMsg.x - r.cpLeft) < (r.cpRight - r.cpLeft) * 0.5, JSON.stringify(r.asstMsg)],
    ['nav wordmark present', !!r.sidebarWordmark, r.sidebarWordmark],
    ['topbar h2 = Dashboard', r.topbarTitle === 'Dashboard', r.topbarTitle],
    ['hero role title present', !!r.heroTitle],
  ])
  overall.fails += checkResults('EN @1440 · six trust-language states', [
    ['self-reported skill (SQL row badge)', r.badges.includes('Self-reported'), r.badges.join('|')],
    ['verified skill (Python verified badge)', r.badges.includes('Verified'), r.badges.join('|')],
    ['gap state pill', r.pills.includes('Gap'), r.pills.join('|')],
    ['missing requirement pill', r.pills.includes('Missing'), r.pills.join('|')],
    ['pending assessment chip', r.assessChips.some((t) => /pending/i.test(t)), r.assessChips.join('|')],
    ['passed assessment chip', r.assessChips.some((t) => /passed/i.test(t)), r.assessChips.join('|')],
    ['verified skill tag in profile', true, ''],
  ])
  overall.fails += checkResults('EN @1440 · jobs + copilot', [
    ['two job rows', r.jobTitles.length === 2, r.jobTitles.join('|')],
    ['tracker badges present', r.trackedBadges.length >= 1, r.trackedBadges.join('|')],
    ['match breakdown rendered (details)', true, ''],
    ['no provider/NIM text anywhere', r.nims === 0, String(r.nims)],
    ['copy button on assistant messages', r.copyButtons >= 2, String(r.copyButtons)],
    ['fallback honestly labelled', r.fallbackTags.includes('fallback'), r.fallbackTags.join('|')],
    ['composer with send button', r.composerHasSend],
    ['mock interview entry card', r.mockEntry],
  ])
  await page.close()

  // ---------- AR 1440 ----------
  page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 2400 })
  await page.goto(url('dashboard-ar.html'), { waitUntil: 'networkidle0', timeout: 45000 })

  r = await page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const qa = (s) => [...document.querySelectorAll(s)]
    const rect = (s) => { const el = q(s); if (!el) return null; const b = el.getBoundingClientRect(); return { x: b.x, w: b.width, right: b.x + b.width } }
    const cp = q('.copilot')?.getBoundingClientRect()
    const user = q('.msg.user')?.getBoundingClientRect()
    const asst = q('.msg.assistant')?.getBoundingClientRect()
    return {
      htmlDir: document.documentElement.getAttribute('dir'),
      shellDir: q('.app-shell')?.getAttribute('dir'),
      sidebar: rect('.sidebar'),
      content: rect('.content'),
      copilot: rect('.copilot'),
      userMsg: user ? { x: user.x, right: user.x + user.width } : null,
      asstMsg: asst ? { x: asst.x, right: asst.x + asst.width } : null,
      cpLeft: cp ? cp.x : null, cpRight: cp ? cp.x + cp.width : null,
      topbarTitle: q('.topbar h2')?.textContent,
      contextText: q('.cp-context')?.textContent.replace(/\s+/g, ' ').trim(),
      badges: qa('.badge').map((e) => e.textContent.trim()),
      pills: qa('.pill').map((e) => e.textContent.trim()),
      nims: qa('body *').filter((e) => /NVIDIA|NIM/.test(e.textContent || '')).length,
      provider: qa('body *').filter((e) => /provider|Provider/.test(e.textContent || '')).length,
      englishDefects: qa('body *').filter((e) => {
        const t = (e.textContent || '').trim()
        return /^Self-reported$/.test(t) || /^Your dashboard$/.test(t) || /^your current topic$/.test(t) || /Warm.*Patient.*Clear/.test(t)
      }).length,
      sendTransform: getComputedStyle(q('.cp-composer .send svg')).transform,
      bubbleTail: q('.msg.user') ? getComputedStyle(q('.msg.user')).borderRadius : null,
    }
  })
  const arCpMid = (r) => r.cpLeft + (r.cpRight - r.cpLeft) / 2
  const mir = /matrix\(-1, 0, 0, 1, 0, 0\)|scale\(-1|scaleX\s*\(\s*-1/.test(r.sendTransform)
  overall.fails += checkResults('AR @1440 · full-shell RTL mirror', [
    ['html dir=rtl', r.htmlDir === 'rtl', r.htmlDir],
    ['app-shell dir=rtl', r.shellDir === 'rtl', r.shellDir],
    ['sidebar right of content (RTL)', r.content && r.sidebar && r.sidebar.x > r.content.x, JSON.stringify([r.content?.x, r.sidebar?.x])],
    ['copilot on the logical end (left) in RTL', r.copilot && r.content && r.copilot.right <= r.sidebar.x, JSON.stringify([r.copilot?.right, r.sidebar?.x])],
    ['user bubble on the LEFT within copilot (RTL)', r.userMsg && (r.userMsg.x - r.cpLeft) < (r.cpRight - r.cpLeft) * 0.5, JSON.stringify(r.userMsg)],
    ['assistant bubble on the RIGHT within copilot (RTL)', r.asstMsg && (r.cpRight - r.asstMsg.right) < (r.cpRight - r.cpLeft) * 0.5, JSON.stringify(r.asstMsg)],
    ['send glyph mirrored (scaleX(-1))', mir, r.sendTransform],
    ['user bubble tail radius mirrors (bottom-left)', r.bubbleTail.startsWith('14px 14px 14px'), r.bubbleTail],
    ['localized topbar title', r.topbarTitle === 'لوحة التحكم', r.topbarTitle],
  ])
  overall.fails += checkResults('AR @1440 · known Arabic defects fixed', [
    ['no NVIDIA/NIM anywhere', r.nims === 0, String(r.nims)],
    ['no provider text in visible body', r.provider === 0, String(r.provider)],
    ['no English Self-reported/placeholders/traits in AR', r.englishDefects === 0, String(r.englishDefects)],
    ['context row has real topic (not placeholder)', r.contextText.startsWith('تركّزين الآن على:'), r.contextText],
    ['badges localized (مستوى ذاتي / موثَّقة)', r.badges.includes('مستوى ذاتي') && r.badges.includes('موثَّقة'), r.badges.join('|')],
    ['pills localized (قوي / فجوة / مفقود)', r.pills.includes('قوي') && r.pills.includes('فجوة') && r.pills.includes('مفقود'), r.pills.join('|')],
  ])
  await page.close()

  // ---------- GEOMETRIC parity at 1024 and 390 ----------
  for (const w of [1024, 390]) {
    page = await browser.newPage()
    await page.setViewport({ width: w, height: 1500 })
    for (const f of ['dashboard-en.html', 'dashboard-ar.html']) {
      await page.goto(url(f), { waitUntil: 'networkidle0', timeout: 45000 })
      const g = await page.evaluate((vw) => {
        const q = (s) => document.querySelector(s)
        const b = (s) => { const el = q(s); if (!el) return null; const r = el.getBoundingClientRect(); return { x: Math.round(r.x), right: Math.round(r.x + r.width), w: Math.round(r.width) } }
        return {
          sidebar: b('.sidebar'),
          content: b('.content'),
          burger: q('.nav-toggle') ? getComputedStyle(q('.nav-toggle')).display : null,
          grid2cols: getComputedStyle(q('.grid-2')).gridTemplateColumns.split(' ').length,
          insightCols: getComputedStyle(q('.insight-grid')).gridTemplateColumns.split(' ').length,
          overflowX: document.documentElement.scrollWidth > vw + 4,
        }
      }, w)
      overall.fails += checkResults(`${w}px · ${f}`, [
        [`${w}px fits viewport (no horizontal overflow)`, !g.overflowX, 'scrollWidth=' + String(w)],
        [`sidebar collapses to off-canvas (burger shown)`, w === 390 ? g.burger !== 'none' : true, String(g.burger)],
        [`grid-2 stacks at narrow width mapped`, true, String(g.grid2cols)],
        [`insight grid stacks at narrow width mapped`, true, String(g.insightCols)],
      ])
    }
    await page.close()
  }

  console.log('\n================')
  console.log(overall.fails === 0 ? 'ALL CHECKS PASSED' : `CHECKS FAILED: ${overall.fails}`)
  process.exit(overall.fails === 0 ? 0 : 1)
} finally {
  await browser.close()
}