import puppeteer from "puppeteer-core"

const BASE = "http://127.0.0.1:8000"
const SHOTS = "C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\shots"
const BMARK = "C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\brave-profile-icons2"
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const { rmSync } = await import("fs")
try { rmSync(BMARK, { recursive: true, force: true }) } catch {}

async function login (page) {
  const alreadyIn = await page.evaluate(() => !!document.querySelector(".nav-item"))
  if (!alreadyIn) {
    await page.waitForSelector("input[placeholder=\"you@example.com\"]", { timeout: 20000 })
    await page.type("input[placeholder=\"you@example.com\"]", "omar@student.edu")
    await page.type("input[autocomplete=\"current-password\"]", "demo1234")
    await page.click(".btn-signin")
    await page.waitForSelector(".nav-item", { timeout: 30000 })
  }
  await sleep(1500)
  const hasOnboarding = await page.$(".cob-backdrop")
  if (hasOnboarding) { const btn = await page.$(".cob-backdrop .cob-close"); if (btn) { await btn.click().catch(() => {}) }; await sleep(600) }
}

async function openCopilot (page) {
  // If the panel is already open, close it first so the bar click reliably opens.
  const wasOpen = await page.evaluate(() => document.querySelector(".copilot-panel")?.classList.contains("copilot-open") || false)
  const bar = await page.$(".copilot-bar-main")
  if (bar && wasOpen) { await bar.click(); await sleep(600) }
  if (bar) await bar.click()
  await sleep(1200)
  await page.waitForSelector(".suggestion-card", { timeout: 15000 })
  await sleep(800)
}

async function openLearning (page) {
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll(".nav-item")]
    const target = btns.find((b) => (b.textContent || "").includes("Learning"))
    if (target) target.click()
  })
  await page.waitForSelector(".quick-panel .quick-item", { timeout: 15000 })
  await sleep(800)
}

async function quickAccessMetrics (page) {
  return page.evaluate(() => {
    const rows = [...document.querySelectorAll(".quick-panel .quick-item:not(.tip)")]
    const out = rows.map((row) => {
      const icon = row.querySelector(".quick-icon")
      const chev = row.querySelector(".chev")
      const ir = icon.getBoundingClientRect()
      const cr = chev.getBoundingClientRect()
      const rr = row.getBoundingClientRect()
      let labelCenterY = null
      for (const node of row.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
          const range = document.createRange()
          range.selectNodeContents(node)
          const lr = range.getBoundingClientRect()
          if (lr.width > 0) { labelCenterY = lr.top + lr.height / 2; break }
        }
      }
      return {
        text: (row.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30),
        iconCenterY: +(ir.top + ir.height / 2).toFixed(2),
        labelCenterY: labelCenterY == null ? null : +labelCenterY.toFixed(2),
        chevCenterY: +(cr.top + cr.height / 2).toFixed(2),
        rowCenterY: +(rr.top + rr.height / 2).toFixed(2),
        chevSide: cr.left + cr.width / 2 > rr.left + rr.width / 2 ? "right" : "left",
        dir: getComputedStyle(row).direction,
        alignItems: getComputedStyle(row).alignItems,
      }
    })
    const icons = out.map((o) => o.iconCenterY)
    return { out, rows: out.length, iconSpread: +(Math.max(...icons) - Math.min(...icons)).toFixed(2) }
  })
}

async function suggestionMetrics (page) {
  return page.evaluate(() => {
    const cards = [...document.querySelectorAll(".suggestion-card")]
    return cards.map((card) => {
      const icon = card.querySelector(".suggestion-icon")
      const text = card.children[1]
      const ir = icon.getBoundingClientRect()
      const tr = text.getBoundingClientRect()
      return {
        title: (text.textContent || "").trim().replace(/\s+/g, " ").slice(0, 24),
        iconCenterY: +(ir.top + ir.height / 2).toFixed(2),
        textCenterY: +(tr.top + tr.height / 2).toFixed(2),
        delta: +((ir.top + ir.height / 2) - (tr.top + tr.height / 2)).toFixed(2),
      }
    })
  })
}

async function main () {
  const browser = await puppeteer.launch({
    executablePath: "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    headless: true, args: ["--no-sandbox", "--disable-gpu"],
    defaultViewport: { width: 1440, height: 900 }, userDataDir: BMARK,
  })
  const page = await browser.newPage()
  const results = {}
  const fails = []

  // ==== DESKTOP 1440 LTR ====
  await page.goto(BASE + "/", { waitUntil: "networkidle2", timeout: 60000 })
  await login(page)
  await openCopilot(page)
  results.suggestionDesktop = await suggestionMetrics(page)
  await page.screenshot({ path: SHOTS + "\\icons-suggestion-1440.png", fullPage: false })
  await openLearning(page)
  results.quickAccessDesktop = await quickAccessMetrics(page)
  await page.screenshot({ path: SHOTS + "\\icons-quick-1440.png", fullPage: false })

  // ==== DESKTOP 1440 RTL ====
  await openCopilot(page)
  await page.evaluate(() => { const b = document.querySelector(".copilot-body"); if (b) b.setAttribute("dir", "rtl"); document.documentElement.dir = "rtl" })
  await sleep(300)
  results.suggestionDesktopRTL = await suggestionMetrics(page)
  await page.screenshot({ path: SHOTS + "\\icons-suggestion-1440-rtl.png", fullPage: false })
  await openLearning(page)
  results.quickAccessDesktopRTL = await quickAccessMetrics(page)
  await page.screenshot({ path: SHOTS + "\\icons-quick-1440-rtl.png", fullPage: false })

  // ==== MOBILE 390 LTR ====
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 })
  await page.goto(BASE + "/", { waitUntil: "networkidle2", timeout: 60000 })
  await login(page)
  await openCopilot(page)
  results.suggestionMobile = await suggestionMetrics(page)
  await page.screenshot({ path: SHOTS + "\\icons-suggestion-390.png", fullPage: false })
  await openLearning(page)
  results.quickAccessMobile = await quickAccessMetrics(page)
  await page.screenshot({ path: SHOTS + "\\icons-quick-390.png", fullPage: false })

  await browser.close()

function evalQuick (r) {
    if (!r || r.rows < 5) return { ok: false, why: "rows<5" }
    const offs = r.out.map((o) => {
      const lc = o.labelCenterY == null ? o.chevCenterY : o.labelCenterY
      return Math.abs(o.iconCenterY - lc)
    })
    const maxOff = Math.max(...offs)
    return { ok: maxOff <= 2, maxOff: +maxOff.toFixed(2) }
  }
  function evalRtl (r) {
    if (!r || r.rows < 5) return { ok: false, why: "rows<5" }
    const sides = new Set(r.out.map((o) => o.chevSide))
    return { ok: sides.size === 1 && r.out[0].chevSide === "left", sides: [...sides] }
  }
  function evalSugg (r) {
    if (!r || r.length < 4) return { ok: false, why: "cards<4" }
    const maxDelta = Math.max(...r.map((c) => Math.abs(c.delta)))
    return { ok: maxDelta <= 2, maxDelta: +maxDelta.toFixed(2) }
  }

const checks = {
    quickDesktopLTR: evalQuick(results.quickAccessDesktop),
    quickDesktopRTL: evalQuick(results.quickAccessDesktopRTL),
    quickMobile390: evalQuick(results.quickAccessMobile),
    suggestionDesktopLTR: evalSugg(results.suggestionDesktop),
    suggestionDesktopRTL: evalSugg(results.suggestionDesktopRTL),
    suggestionMobile390: evalSugg(results.suggestionMobile),
  }
  for (const [k, v] of Object.entries(checks)) if (!v.ok) fails.push(k + " => " + JSON.stringify(v))

  console.log("=== RESULT DATA ===")
  console.log(JSON.stringify(results, null, 2))
  console.log("=== CHECKS ===")
  console.log(JSON.stringify(checks, null, 2))
  console.log("RESULT: " + (fails.length ? "FAIL\n" + fails.join("\n") : "PASS"))
  process.exit(fails.length ? 1 : 0)
}
main().catch((e) => { console.error(e); process.exit(2) })
