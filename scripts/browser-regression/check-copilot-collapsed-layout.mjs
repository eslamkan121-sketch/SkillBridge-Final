// Contract: COLLAPSED Copilot float must remain byte-identical in behaviour to
// the pre-Track-A layout. Nothing about collapsed mode changed; this guard
// exists so a future change cannot accidentally leak expanded-mode layout into
// the collapsed float.
//  - panel is `.copilot-open` and NOT `.copilot-expanded` / `.history-open`
//  - `.copilot-body` keeps the legacy `overflow-y: auto` scroll model
//  - thread has no history gutter (`padding-inline-start: 0`)
//  - quick-chips render inside the thread container
//  - the thread itself is content-sized (the BODY scrolls, not the thread)
//  - composer bottom-anchored ~15px above the panel bottom (no giant blank)
import puppeteer from 'puppeteer-core'
const BASE = 'http://127.0.0.1:8000'
const BRAVE = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const sleep = ms => new Promise(r => setTimeout(r, ms))

async function login(page) {
  const alreadyIn = await page.evaluate(() => !!document.querySelector('.nav-item'))
  if (!alreadyIn) {
    await page.waitForSelector('input[placeholder="you@example.com"]', { timeout: 20000 })
    await page.type('input[placeholder="you@example.com"]', 'omar@student.edu')
    await page.type('input[autocomplete="current-password"]', 'demo1234')
    await page.click('.btn-signin')
    await page.waitForSelector('.nav-item', { timeout: 30000 })
  }
  await sleep(2000)
  const ob = await page.$('.cob-backdrop')
  if (ob) { const b = await page.$('.cob-backdrop .cob-close'); if (b) await b.click().catch(() => {}); await sleep(600) }
}

const browser = await puppeteer.launch({
  executablePath: BRAVE,
  headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--window-size=1440,900'],
  defaultViewport: { width: 1440, height: 900 },
  userDataDir: 'C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\brave-profile-collapsed-contract',
})
const page = await browser.newPage()
page.on('pageerror', e => console.log('PAGEERR:', e.message))

const vps = [
  { width: 1440, height: 900, label: '1440' },
  { width: 390, height: 844, label: '390', mobile: true },
]

const failures = []
const lines = []

for (const vp of vps) {
  await page.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: 1 })
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
  await login(page)

  // open the collapsed float only — never click .copilot-expand
  await page.click('.copilot-bar-main').catch(() => {})
  await sleep(600)

  const ta = await page.$('.copilot-v2 textarea')
  if (ta) {
    await ta.click()
    await page.keyboard.type('explain docker networks')
    await page.keyboard.press('Enter')
    await sleep(2500)
  }

  const layout = await page.evaluate(() => {
    const panel = document.querySelector('.copilot-panel')
    if (!panel) return { error: 'no .copilot-panel' }
    if (!panel.classList.contains('copilot-open')) return { error: 'panel not open (no copilot-open)' }
    if (!panel.classList.contains('copilot-expanded')) {
      // collapsed float present
    }
    const pr = panel.getBoundingClientRect()
    const body = panel.querySelector('.copilot-body')
    if (!body) return { error: 'no .copilot-body' }
    const thread = panel.querySelector('.thread')
    const chips = panel.querySelector('.quick-chips')
    const cw = panel.querySelector('.composer-wrapper')?.getBoundingClientRect()
    const panelCls = Array.from(panel.classList).join(' ')
    const bodyOv = getComputedStyle(body).overflowY
    const ts = thread ? getComputedStyle(thread) : null
    const chipsInside = !!chips && !!chips.closest('.copilot-body')
    return {
      panelClasses: panelCls,
      expanded: panel.classList.contains('copilot-expanded'),
      historyOpen: panel.classList.contains('history-open'),
      bodyOverflowY: bodyOv,
      threadExists: !!thread,
      threadScrollable: !!thread && thread.scrollHeight > thread.clientHeight + 2,
      threadPadInline: ts ? ts.paddingInlineStart : null,
      chipsPresent: !!chips,
      chipsInside,
      composerBottom: cw ? Math.round(cw.bottom) : null,
      panelBottom: Math.round(pr.bottom),
      blankBelowComposer: cw ? Math.round(pr.bottom - cw.bottom) : null,
      msgCount: panel.querySelectorAll('.thread .msg').length,
    }
  })

  lines.push(vp.label + ': ' + JSON.stringify(layout))

  if (layout.error) { failures.push(vp.label + ': ' + layout.error); continue }
  if (layout.expanded) failures.push(vp.label + ': panel has copilot-expanded (must stay collapsed)')
  if (layout.historyOpen) failures.push(vp.label + ': panel has history-open (collapsed has no drawer)')
  if (layout.bodyOverflowY !== 'auto') failures.push(vp.label + ': .copilot-body overflowY=' + layout.bodyOverflowY + ' (must be auto in collapsed mode)')
  if (!layout.threadExists) failures.push(vp.label + ': .thread missing after send')
  if (layout.threadPadInline !== '0px') failures.push(vp.label + ': thread paddingInlineStart=' + layout.threadPadInline + ' (history gutter leaked into collapsed)')
  if (!layout.chipsPresent || !layout.chipsInside) failures.push(vp.label + ': quick-chips not inside the collapsed body')
  if (layout.threadScrollable) failures.push(vp.label + ': thread scrollable in collapsed mode (body must scroll, not thread)')
  if ((layout.blankBelowComposer ?? 999) > 40) failures.push(vp.label + ': blankBelowComposer=' + layout.blankBelowComposer + ' (composer not bottom-anchored)')
  if ((layout.blankBelowComposer ?? -1) < 0) failures.push(vp.label + ': composer overlapped past panel bottom')
  if (layout.msgCount < 1) failures.push(vp.label + ': no messages seeded')
}

await browser.close()

console.log(lines.join('\n'))
if (failures.length) {
  console.log('FAILURES=' + JSON.stringify(failures))
  process.exit(1)
}
console.log('RESULT: PASS')
process.exit(0)