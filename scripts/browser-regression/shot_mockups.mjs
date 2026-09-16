import { launch } from 'puppeteer-core'

const brave = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const profile = process.env.TEMP + '\\opencode\\brave-profile-mockups'
const outDir = process.argv[2] || (process.env.TEMP + '\\opencode\\shots')
const baseDir = 'C:/Users/khale/Downloads/SkillBridge-Final-main/SkillBridge-Final-main/docs/mockups'
const specs = [
  { file: 'dashboard-en.html', name: 'en' },
  { file: 'dashboard-ar.html', name: 'ar' },
]
const widths = [1440, 1024, 390]

const url = (f) => 'file:///' + baseDir + '/' + f

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

const browser = await launch({
  executablePath: brave,
  headless: 'new',
  userDataDir: profile,
  args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars'],
})

try {
  for (const s of specs) {
    for (const w of widths) {
      const page = await browser.newPage()
      await page.setViewport({ width: w, height: 900 })
      await page.goto(url(s.file), { waitUntil: 'networkidle0', timeout: 45000 })
      await sleep(400)
      await page.screenshot({ path: `${outDir}\\mockup-${s.name}-${w}.png`, fullPage: true })
      const title = await page.title()
      const dir = await page.evaluate(() => document.querySelector('.app-shell')?.getAttribute('dir'))
      const msgs = await page.evaluate(() => {
        return [...document.querySelectorAll('.msg')].map((m) => m.className).join('|')
      })
      console.log(`OK  ${s.name}@${w}  dir=${dir}  msgs=[${msgs}]  title="${title}"`)
      await page.close()
    }
  }
  console.log('DONE')
} finally {
  await browser.close()
}