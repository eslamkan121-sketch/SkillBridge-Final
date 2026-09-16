import { launch } from 'puppeteer-core'

const brave = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const profile = process.env.TEMP + '\\opencode\\brave-profile-skills-check'
const file = 'file:///' + 'C:/Users/khale/Downloads/SkillBridge-Final-main/SkillBridge-Final-main/docs/mockups/skills-and-roles.html'

function checkResults(label, checks) {
  console.log('\n== ' + label + ' ==')
  let fail = 0
  for (const [name, ok, extra] of checks) {
    if (ok) console.log('  PASS  ' + name)
    else { console.log('  FAIL  ' + name + (extra ? '  → ' + extra : '')); fail++ }
  }
  return fail
}

const browser = await launch({
  executablePath: brave,
  headless: 'new',
  userDataDir: profile,
  args: ['--no-sandbox', '--disable-gpu'],
})

let fails = 0

try {
  // ---------- EN 1440 ----------
  let page = await browser.newPage()
  await page.setViewport({ width: 1440, height: 2600 })
  await page.goto(file, { waitUntil: 'networkidle0', timeout: 45000 })

  let r = await page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const qa = (s) => [...document.querySelectorAll(s)]
    const txt = (s) => (q(s) ? q(s).textContent.replace(/\s+/g, ' ').trim() : null)
    return {
      sameTargetName: txt('.srb-target-title .ltr-only'),
      crumbs: txt('.crumbs'),
      heroTitle: txt('.sro3-hero-title'),
      targetCard: !!q('.srb-card.srb-target-card'),
      profileCard: !!q('.srb-card.srb-profile-card'),
      currentTargetBadge: txt('.srb-target-card .current-target-badge'),
      changeTargetBtn: txt('.srb-target-card label.btn.srb-btn-outline'),
      ringPct: q('.srb-target-card .srb-match-ring')?.getAttribute('style'),
      statRow: qa('.srb-stat').map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
      betav: txt('.srb-target-meta .srb-cat-version'),
      tabs: qa('.rd-tab').map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
      facets: qa('.srb-facet > summary').map((e) => e.textContent.replace(/\s+/g, ' ').trim()),
      facetSearch: !!q('.srb-facet-search'),
      facetScroll: !!q('.srb-facet-opts.srb-facet-scroll'),
      sortOpts: qa('.srb-sort option').map((e) => e.textContent.trim()),
      count: txt('.srb-count'),
      roles: qa('.srb-role').length,
      companyChips: qa('.srb-role .chip-company').length,
      catalogChips: qa('.srb-role .chip-catalog').length,
      titleBtns: qa('.srb-role-title').length,
      viewBtns: qa('.srb-role-foot label').filter((e) => /details/.test(e.textContent.toLowerCase())).length,
      pagerInfo: txt('.rd-pager-info'),
      prevDisabled: q('.rd-pager .btn[disabled]'),
      catVersionCount: qa('.srb-cat-version').length,
      notSpecified: qa('body *').filter((e) => /Not specified/i.test(e.textContent || '')).length,
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      hasNim: qa('body *').filter((e) => /NVIDIA|NIM/.test(e.textContent || '')).length,
      drawerCount: qa('.rd-shell').length,
      backdropCount: qa('.rd-backdrop').length,
    }
  })

  fails += checkResults('EN 1440 · Skills & Roles mockup', [
    ['crumbs present', r.crumbs && r.crumbs.includes('Skills'), r.crumbs],
    ['hero present', r.heroTitle && r.heroTitle.length > 0, r.heroTitle],
    ['target card + profile card', r.targetCard && r.profileCard, r.targetCard + '/' + r.profileCard],
    ['target = Cybersecurity Analyst 54%', r.sameTargetName === 'Cybersecurity Analyst', r.sameTargetName],
    ['match ring --pct:54', (r.ringPct || '').includes('--pct:54'), r.ringPct],
    ['non-interactive Current target badge', r.currentTargetBadge && (r.currentTargetBadge || '').trim() !== '', r.currentTargetBadge],
    ['enabled Change target button', r.changeTargetBtn && /Change target/i.test(r.changeTargetBtn), r.changeTargetBtn],
    ['rd-tabs 6/11 with counts', r.tabs.length === 2 && r.tabs[0].includes('6') && r.tabs[1].includes('11'), r.tabs.join(' | ')],
    ['category + skill facets', r.facets.length === 2 && r.facets[0].includes('Category') && r.facets[1].includes('Skill'), r.facets.join(' | ')],
    ['in-facet search + scroll list', r.facetSearch && r.facetScroll, r.facetSearch + '/' + r.facetScroll],
    ['sort dropdown 4 options', r.sortOpts.length === 4, r.sortOpts.join(', ')],
    ['17-role count label', r.count && r.count.includes('17'), r.count],
    ['12 role cards on page 1', r.roles === 12, 'roles=' + r.roles],
    ['6 company + 6 catalog chips', r.companyChips === 6 && r.catalogChips === 6, r.companyChips + '/' + r.catalogChips],
    ['12 role title buttons', r.titleBtns === 12, r.titleBtns],
    ['12 View details buttons', r.viewBtns === 12, r.viewBtns],
    ['pager Page 1 of 2 · 17 roles', r.pagerInfo && r.pagerInfo.includes('Page 1 of 2') && r.pagerInfo.includes('17 roles'), r.pagerInfo],
    ['prev disabled on page 1', !!r.prevDisabled, String(!!r.prevDisabled)],
    ['srb-cat-version in use', r.catVersionCount >= 12, 'x' + r.catVersionCount],
    ['no literal "Not specified"', r.notSpecified === 0, 'found=' + r.notSpecified],
    ['no horizontal overflow', r.overflowX <= 0, 'dx=' + r.overflowX],
    ['no NVIDIA/NIM branding', r.hasNim === 0, 'found=' + r.hasNim],
    ['12 drawer shells + backdrops', r.drawerCount === 12 && r.backdropCount === 12, r.drawerCount + '/' + r.backdropCount],
  ])

  // Extra assertions on card #1 = target role (badge, not a select button)
  r = await page.evaluate(() => {
    const card = document.querySelectorAll('.srb-role')[0]
    return {
      hasBadge: !!card.querySelector('.current-target-badge'),
      hasSelectBtn: /Select as target/.test(card.querySelector('.srb-role-foot').textContent),
      match: card.querySelector('.srb-match-inner strong')?.textContent,
    }
  })
  fails += checkResults('EN 1440 · target-role card', [
    ['card 1 has Current target badge', r.hasBadge, String(!!r.hasBadge)],
    ['card 1 has no Select-as-target button', !r.hasSelectBtn, String(r.hasSelectBtn)],
    ['card 1 shows 54% ring', r.match === '54%', r.match],
  ])

  // ---------- Drawer open/close interaction ----------
  r = await page.evaluate(async () => {
    const q = (s) => document.querySelector(s)
    const drawerRect = () => {
      const b = q('.rd-shell-1 .rd-drawer').getBoundingClientRect()
      return { x: b.x, right: b.x + b.width, w: b.width }
    }
    const set = (id, v) => { const el = document.getElementById(id); el.checked = v; el.dispatchEvent(new Event('change', { bubbles: true })) }
    set('rd-view-1', true)
    await new Promise((res) => setTimeout(res, 500))
    const shell = q('.rd-shell-1')
    const cs = getComputedStyle(shell)
    const rect = drawerRect()
    const onScreen = rect.x >= -1 && rect.right <= innerWidth + 1
    const info = { vis: cs.visibility, op: cs.opacity, x: rect.x, right: rect.right, w: rect.w, head: q('.rd-shell-1 .rd-drawer h3')?.textContent.replace(/\s+/g, ' ').trim() }
    set('rd-view-1', false)
    await new Promise((res) => setTimeout(res, 500))
    const hidden = getComputedStyle(q('.rd-shell-1')).visibility === 'hidden'
    return { onScreen, info, hidden }
  })
  fails += checkResults('Drawer interaction (zero-JS checkbox + :has)', [
    ['open #rd-view-1 → shell visible & drawer completely on-screen', r.onScreen, JSON.stringify(r.info)],
    ['drawer shows CyberSecurity title', r.info.head && /Cybersecurity Analyst/.test(r.info.head), r.info.head],
    ['deselect → shell hidden', r.hidden, String(r.hidden)],
  ])

  // ---------- AR 1440 ----------
  await page.evaluate(() => { const el = document.getElementById('lang-ar'); el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })) })
  await new Promise((res) => setTimeout(res, 500))
  r = await page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const b = q('.rd-shell-1 .rd-drawer').getBoundingClientRect()
    return {
      dir: getComputedStyle(document.body).direction,
      drawerRect: { x: b.x, w: b.width, right: b.x + b.width },
      ltrOnlyVisible: [...document.querySelectorAll('.ltr-only')].some((e) => getComputedStyle(e).display !== 'none'),
      rtlOnlyVisible: [...document.querySelectorAll('.rtl-only')].some((e) => getComputedStyle(e).display !== 'none'),
      targetAr: q('.srb-target-title').textContent.replace(/\s+/g, ' ').trim(),
      footprint: q('.srb-target-meta').textContent.replace(/\s+/g, ' ').trim(),
      ringStill: !!q('.srb-target-card .srb-match-ring'),
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    }
  })
  const offScreenLeft = (r.drawerRect.right ?? 1e9) <= 0
  fails += checkResults('AR 1440 · RTL mirroring', [
    ['body direction rtl', r.dir === 'rtl', r.dir],
    ['.ltr-only hidden', !r.ltrOnlyVisible, String(r.ltrOnlyVisible)],
    ['.rtl-only visible', r.rtlOnlyVisible, String(r.rtlOnlyVisible)],
    ['target title in Arabic', /محللة أمن سيبراني/.test(r.targetAr), r.targetAr],
    ['Arabic meta (northstar/remote)', r.footprint.includes('نورث ستار'), r.footprint],
    ['match ring preserved in AR', r.ringStill, String(r.ringStill)],
    ['closed drawer parked off-screen (RTL −110%)', offScreenLeft, JSON.stringify(r.drawerRect)],
    ['no horizontal overflow in RTL', r.overflowX <= 0, 'dx=' + r.overflowX],
  ])
  await page.close()

  // ---------- 390 viewport (mobile) ----------
  page = await browser.newPage()
  await page.setViewport({ width: 390, height: 1200 })
  await page.goto(file, { waitUntil: 'networkidle0', timeout: 45000 })
  await page.evaluate(() => { const el = document.getElementById('vp-390'); el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })) })
  await new Promise((res) => setTimeout(res, 150))
  r = await page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const qa = (s) => [...document.querySelectorAll(s)]
    return {
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      gridCols: qa('.srb-role').length,
      tabsDouble: getComputedStyle(q('.rd-tabs')).gridTemplateColumns.split(' ').length,
      facets1col: getComputedStyle(q('.srb-filterbar')).gridTemplateColumns.split(' ').length,
      pager: q('.rd-pager').getBoundingClientRect().width,
      stackSummary: getComputedStyle(q('.srb-summary')).gridTemplateColumns === 'minmax(0px, 1fr)' || getComputedStyle(q('.srb-summary')).gridTemplateColumns === 'minmax(0, 1fr)',
      drawerFullWidth: (function () { const el = document.getElementById('rd-view-1'); el.checked = true; return true })()
    }
  })
  await new Promise((res) => setTimeout(res, 350))
  r = await page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const dw = q('.rd-shell-1 .rd-drawer')
    const b = dw.getBoundingClientRect()
    return {
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      roles: q('.srb-grid').children.length,
      summary1col: q('.srb-summary').getBoundingClientRect().height > 0,
      drawerW: b.width,
      overlay: getComputedStyle(dw).opacity,
    }
  })
  fails += checkResults('390 mobile', [
    ['no horizontal overflow', r.overflowX <= 0, 'dx=' + r.overflowX],
    ['12 role cards still rendered', r.roles === 12, 'roles=' + r.roles],
    ['drawer is full-width overlay', r.drawerW === 390 || r.overlay === '1', 'w=' + r.drawerW + ' op=' + r.overlay],
  ])
  await page.close()
} finally {
  await browser.close()
}

console.log('\n' + (fails === 0 ? 'ALL CHECKS PASSED' : fails + ' CHECK(S) FAILED'))
process.exit(fails === 0 ? 0 : 1)