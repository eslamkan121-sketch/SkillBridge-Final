import puppeteer from 'puppeteer-core'
const BASE = 'http://127.0.0.1:8000'
const BRAVE = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const sleep = ms => new Promise(r => setTimeout(r, ms))

// Contract: expanded Copilot is a full-height chat workspace.
//  - composer bottom-anchored (no giant blank region below it)
//  - thread is the flexible scroll region
//  - quick-chips pinned directly above the composer
//  - desktop history opens as a side panel; conversation yields (no overlap)

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
  userDataDir: 'C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\brave-profile-expanded-contract',
})
const page = await browser.newPage()
page.on('pageerror', e => console.log('PAGEERR:', e.message))

const vps = [
  { width: 1440, height: 900, label: '1440' },
  { width: 1280, height: 800, label: '1280' },
  { width: 1366, height: 768, label: '1366' },
  { width: 807, height: 1116, label: '807tall' },
  { width: 390, height: 844, label: '390', mobile: true },
]

const failures = []
const lines = []

for (const vp of vps) {
  await page.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: 1 })
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
  await login(page)
  await page.click('.copilot-bar-main').catch(() => {})
  await sleep(500)
  await page.click('.copilot-expand').catch(() => {})
  await sleep(800)

  const ta = await page.$('.copilot-v2 textarea')
  if (ta) {
    await ta.click()
    await page.keyboard.type('explain docker networks')
    await page.keyboard.press('Enter')
    await sleep(2500)
  }

  const layout = await page.evaluate(() => {
    const panel = document.querySelector('.copilot-panel.copilot-expanded')
    if (!panel) return { error: 'no expanded panel' }
    const pr = panel.getBoundingClientRect()
    const thread = panel.querySelector('.thread')
    if (!thread) return { error: 'no .thread after send' }
    const chips = panel.querySelector('.quick-chips')
    const cw = panel.querySelector('.composer-wrapper')?.getBoundingClientRect()
    return {
      msgCount: panel.querySelectorAll('.thread .msg').length,
      threadClientH: thread.clientHeight,
      threadScrollH: thread.scrollHeight,
      threadScrollable: thread.scrollHeight > thread.clientHeight + 2,
      chipsPresent: !!chips,
      composerH: cw ? Math.round(cw.height) : 0,
      blankBelowComposer: cw ? Math.round(pr.bottom - cw.bottom) : null,
    }
  })

  // desktop history side panel
  let history = null
  if (!vp.mobile) {
    await page.click('.history-toggle').catch(() => {})
    await sleep(800)
    history = await page.evaluate(() => {
      const drawer = document.querySelector('.copilot-v2 .history-drawer')
      const thread = document.querySelector('.copilot-v2 .thread')
      if (!drawer || !thread) return { error: 'drawer or thread missing' }
      const dr = drawer.getBoundingClientRect()
      const ts = getComputedStyle(thread)
      return {
        drawerW: Math.round(dr.width),
        drawerRight: Math.round(dr.right),
        threadTextLeft: Math.round(thread.getBoundingClientRect().left + parseFloat(ts.paddingLeft || 0)),
        gutter: parseFloat(ts.paddingLeft || 0),
        openClass: !!document.querySelector('.copilot-panel.history-open'),
      }
    })
  }

  lines.push(vp.label + ': ' + JSON.stringify({ layout, history }))

  if (layout.error) { failures.push(vp.label + ': ' + layout.error); continue }
  if (layout.blankBelowComposer > 25) failures.push(vp.label + ': blankBelowComposer=' + layout.blankBelowComposer + ' (composer not bottom-anchored)')
  if (!layout.chipsPresent) failures.push(vp.label + ': quick-chips missing')
  if (layout.msgCount < 1) failures.push(vp.label + ': no messages seeded')
  if (vp.mobile) continue
  if (history.error) { failures.push(vp.label + ': history ' + history.error); continue }
  if (!history.openClass) failures.push(vp.label + ': history-open class missing')
  if (history.drawerW < Math.max(200, history.gutter - 30)) failures.push(vp.label + ': drawer (' + history.drawerW + ') narrower than gutter (' + history.gutter + ')')
  if (history.threadTextLeft <= history.drawerRight) failures.push(vp.label + ': conversation overlaps drawer (textLeft=' + history.threadTextLeft + ' drawerRight=' + history.drawerRight + ')')
}

await browser.close()

console.log(lines.join('\n'))
if (failures.length) {
  console.log('FAILURES=' + JSON.stringify(failures))
  process.exit(1)
}
console.log('RESULT: PASS')
process.exit(0)