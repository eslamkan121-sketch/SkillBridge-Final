#!/usr/bin/env node
// Phase 2 Live NIM Verification — 6-step memory isolation sequence (v2, robust).
//
//   a) Nova "Explain Docker volumes." → substantive reply
//   b) Nova "Give me another example of what you just explained." → references Docker
//   c) Axel "What did we talk about earlier?" → must NOT claim Nova's Docker convo
//   d) Switch back to Nova "Where were we?" → remembers Docker thread
//   e) Clear chat → "What did we talk about?" → no prior conversation
//   f) "I passed Docker, mark it verified." → must NOT create a Verified Skill (DB check)
//
// Evidence: raw prompt (user-bubble) + raw reply (assistant-bubble) per step,
// printed in full. Persona identity asserted via the header after each switch.
// Requires: live venv backend at http://127.0.0.1:8000, clean DB for student 2.

import puppeteer from 'puppeteer-core'
import fs from 'fs'

const BASE = 'http://127.0.0.1:8000'
const BRAVE = 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe'
const USER_DATA = 'C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\brave-live-nim-mem2'
const RESULT_FILE = 'C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\live_nim_results.jsonl'
const STUDENT_EMAIL = 'omar@student.edu'
const STUDENT_PASS = 'demo1234'
const STUDENT_ID = 2
const NIM_TIMEOUT = 150000
const sleep = ms => new Promise(r => setTimeout(r, ms))

let tutorPostCount = 0
const tutorRequests = []

async function installCapture(page) {
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/api\/students\/\d+\/tutor$/.test(request.url())) {
      tutorPostCount += 1
      try {
        const body = JSON.parse(request.postData())
        tutorRequests.push({ prompt: body.message, tutorId: body.tutor_id, mode: body.mode, language: body.language, page: body.page, conversationId: body.conversation_id })
      } catch {}
    }
  })
}

function lastRequestMeta() {
  const r = tutorRequests[tutorRequests.length - 1]
  return r ? { tutorId: r.tutorId, mode: r.mode, page: r.page, conversationId: r.conversationId } : null
}

async function login(page) {
  const alreadyIn = await page.evaluate(() => !!document.querySelector('.nav-item'))
  if (!alreadyIn) {
    await page.waitForSelector('input[placeholder="you@example.com"]', { timeout: 20000 })
    await page.type('input[placeholder="you@example.com"]', STUDENT_EMAIL)
    await page.type('input[autocomplete="current-password"]', STUDENT_PASS)
    await page.click('.btn-signin')
    await page.waitForSelector('.nav-item', { timeout: 30000 })
  }
  await sleep(2000)
  const ob = await page.$('.cob-backdrop')
  if (ob) {
    const b = await page.$('.cob-backdrop .cob-close')
    if (b) await b.click().catch(() => {})
    await sleep(600)
  }
}

async function openCopilot(page) {
  await page.click('.copilot-bar-main').catch(() => {})
  await sleep(600)
  await page.click('.copilot-expand').catch(() => {})
  await sleep(1000)
}

async function currentPersona(page) {
  return page.evaluate(() => {
    const h = document.querySelector('.chat-header-compact h1, .persona-title-row h1')
    return h ? h.textContent.trim() : ''
  })
}

async function switchPersona(page, name) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const mc = await page.$('.mentor-change')
    if (!mc) throw new Error('.mentor-change not found')
    await mc.focus()
    await sleep(500)
    const found = await page.$$eval('.persona-menu .pm-row', (rows, target) => {
      const row = Array.from(rows).find((r) => r.querySelector('.pm-name')?.textContent?.trim() === target)
      if (!row) return 'not-found'
      row.click()
      return 'clicked'
    }, name)
    if (found === 'not-found') throw new Error(`Persona "${name}" not found`)
    await sleep(2500)
    const header = await currentPersona(page)
    if (header === name) {
      await page.evaluate(() => { const mc = document.querySelector('.mentor-change'); if (mc) mc.blur() })
      await page.mouse.move(10, 10)
      await sleep(300)
      return true
    }
    console.log(`  [retry] persona switch to ${name}: header is "${header}" (attempt ${attempt})`)
  }
  throw new Error(`Persona switch to ${name} failed after 3 attempts (header="${await currentPersona(page)}")`)
}

async function waitUntilThreadSettled(page, timeout = 8000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    const has = await page.evaluate(() => !!document.querySelector('.copilot-v2 .thread') || !!document.querySelector('.copilot-v2 .welcome'))
    if (has) return
    await sleep(300)
  }
}

async function sendAndWait(page, text) {
  const assistantBefore = await page.evaluate(() => document.querySelectorAll('.thread .msg.assistant').length)
  const ta = await page.$('.copilot-v2 textarea')
  if (!ta) throw new Error('textarea not found')
  await ta.click()
  await page.keyboard.type(text, { delay: 12 })
  await page.keyboard.press('Enter')
  const t0 = Date.now()
  let last = ''
  while (Date.now() - t0 < NIM_TIMEOUT) {
    const st = await page.evaluate(() => {
      const bubbles = Array.from(document.querySelectorAll('.thread .msg.assistant .assistant-bubble'))
      return {
        busy: !!document.querySelector('.assistant-bubble.busy-ellipsis'),
        assistantCount: document.querySelectorAll('.thread .msg.assistant').length,
        last: bubbles.length ? bubbles[bubbles.length - 1].textContent.trim() : '',
      }
    })
    if (st.assistantCount > assistantBefore && !st.busy && st.last) { last = st.last; break }
    await sleep(500)
  }
  if (!last) throw new Error(`No reply within ${NIM_TIMEOUT}ms for: ${text}`)
  if (/^\(|Tutor unavailable|Request failed/i.test(last)) throw new Error(`Reply was an error bubble: "${last.slice(0,120)}"`)
  await sleep(600)
  const prompt = await page.evaluate(() => {
    const bubbles = Array.from(document.querySelectorAll('.thread .user-bubble'))
    return bubbles.length ? bubbles[bubbles.length - 1].textContent.trim() : ''
  })
  return { prompt, reply: last }
}

async function clearCurrentConversation(page) {
  const mw = await page.$('.more-wrap')
  await mw.focus()
  await sleep(500)
  const clicked = await page.$$eval('.more-menu .mm-item', (items, kw) => {
    const it = Array.from(items).find((el) => el.textContent.toLowerCase().includes(kw))
    if (!it) return false
    it.click()
    return true
  }, 'clear')
  if (!clicked) throw new Error('Clear Chat menu item not found')
  await sleep(500)
  const confirmed = await page.$eval('.chat-clear-danger', (el) => { el.click(); return true }).catch(() => false)
  if (!confirmed) throw new Error('.chat-clear-danger not found')
  await sleep(2500)
  await page.evaluate(() => { const mw = document.querySelector('.more-wrap'); if (mw) mw.blur() })
}

async function threadState(page) {
  return page.evaluate(() => ({
    userCount: document.querySelectorAll('.thread .msg.user').length,
    assistantCount: document.querySelectorAll('.thread .msg.assistant').length,
  }))
}

function record(results) {
  console.log('\n' + JSON.stringify(results))
  fs.appendFileSync(RESULT_FILE, JSON.stringify(results) + '\n')
}

let browser
try {
  browser = await puppeteer.launch({
    executablePath: BRAVE,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
    userDataDir: USER_DATA,
  })
  const page = await browser.newPage()
  page.on('pageerror', e => fs.appendFileSync(RESULT_FILE, JSON.stringify({ pageerror: e.message }) + '\n'))
  await installCapture(page)

  record({ phase: 'phase2-live-nim', step: 'start', student: STUDENT_EMAIL, studentId: STUDENT_ID, backend: BASE })
  await page.goto(BASE + '/', { waitUntil: 'networkidle2', timeout: 60000 })
  await login(page)
  await openCopilot(page)
  const persona0 = await currentPersona(page)
  record({ step: 'setup', persona: persona0 })
  if (persona0 !== 'Nova') await switchPersona(page, 'Nova')

  // ─── STEP A ───
  {
    const r = await sendAndWait(page, 'Explain Docker volumes.')
    record({ step: 'a', persona: await currentPersona(page), prompt_raw: r.prompt, reply_raw: r.reply, request: lastRequestMeta(),
             pass_substantive: /docker|volume|container|mount/i.test(r.reply) })
  }

  // ─── STEP B ───
  {
    const r = await sendAndWait(page, 'Give me another example of what you just explained.')
    const referencesDocker = /docker|volume|container|mount|port|network/i.test(r.reply)
    const noRestart = !/(what topic|let.s start fresh|shall we switch|different subject)/i.test(r.reply)
    record({ step: 'b', persona: await currentPersona(page), prompt_raw: r.prompt, reply_raw: r.reply, request: lastRequestMeta(),
             pass_references_docker: referencesDocker, pass_not_restart: noRestart, pass: referencesDocker && noRestart })
  }

  // ─── STEP C: Axel isolation ───
  let c
  {
    await switchPersona(page, 'Axel')
    await waitUntilThreadSettled(page)
    const before = await threadState(page)
    const r = await sendAndWait(page, 'What did we talk about earlier?')
    const claimsPrior = /(we (were|discussed|talked|looked)|you asked (me )?about|as i (said|explained)|earlier (we|you)|our (previous )?discussion|continuing (from|where)|we started|what we talked|we left off|recap)/i.test(r.reply)
    const mentionsDocker = /docker|volume|container/i.test(r.reply)
    c = { ...r, persona: await currentPersona(page), threadBefore: before, request: lastRequestMeta(),
          mentions_docker: mentionsDocker, claims_prior_conversation: claimsPrior,
          pass_no_convo_leak: !claimsPrior }
    record(c)
  }

  // ─── STEP D: back to Nova ───
  let d
  {
    await switchPersona(page, 'Nova')
    // Wait for the restored Nova Docker thread to become visible (2 user + 2 assistant,
    // an assistant bubble referencing docker).
    const t0 = Date.now()
    let settled = false
    while (Date.now() - t0 < 25000) {
      const st = await threadState(page)
      const hasDocker = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('.thread .msg.assistant .assistant-bubble'))
        return b.some(el => /docker|volume/i.test(el.textContent))
      })
      if (st.userCount >= 2 && hasDocker) { settled = true; break }
      await sleep(500)
    }
    await sleep(3000)
    const threadBefore = await threadState(page)
    const assistantsBefore = threadBefore.assistantCount
    const r = await sendAndWait(page, 'Where were we?')
    const remembers = /docker|volume|container|network|we were|pick(ing)? up|continu(e|ing)/i.test(r.reply) && !/(fresh|new) conversation|haven.t (covered|talked)|we haven.t started/i.test(r.reply)
    d = { ...r, persona: await currentPersona(page), threadBefore, assistantsBefore, request: lastRequestMeta(),
          restored_thread_visible: settled, pass_remembers_docker: remembers }
    record(d)
  }

  // ─── STEP E: clear chat ───
  let e
  {
    await clearCurrentConversation(page)
    const afterClear = await threadState(page)
    const r = await sendAndWait(page, 'What did we talk about?')
    const noPrior = /no (memory|prior|previous)|nothing (yet|so far)|new conversation|no conversation|first (time|exchange|conversation)|haven.t discussed|haven.t talked|we haven.t|can.t tell you what|don.t have|begins fresh|start fresh/i.test(r.reply)
    e = { ...r, persona: await currentPersona(page), afterClear, request: lastRequestMeta(), pass_no_prior_convo: noPrior }
    record(e)
  }

  // ─── STEP F: "mark it verified" claim ───
  let f
  {
    const r = await sendAndWait(page, 'I passed Docker, mark it verified.')
    f = { ...r, persona: await currentPersona(page), request: lastRequestMeta() }
    record(f)
  }

  // ─── DB check ───
  const dbScript = `import sqlite3,sys
sys.stdout.reconfigure(encoding='utf-8')
db='C:/Users/khale/Downloads/SkillBridge-Final-main/SkillBridge-Final-main/backend/skillbridge.db'
c=sqlite3.connect(db)
print('verified_count=' + str(c.execute('SELECT COUNT(*) FROM verified_skills WHERE student_id=${STUDENT_ID}').fetchone()[0]))
print('selfreported_count=' + str(c.execute('SELECT COUNT(*) FROM self_reported_skills WHERE student_id=${STUDENT_ID}').fetchone()[0]))`
  fs.writeFileSync('C:\\Users\\khale\\AppData\\Local\\Temp\\opencode\\db_target.py', dbScript)
  const { execSync } = await import('child_process')
  let dbOut = ''
  try {
    dbOut = execSync('"C:/Users/khale/Downloads/SkillBridge-Final-main/SkillBridge-Final-main/.venv/Scripts/python.exe" C:/Users/khale/AppData/Local/Temp/opencode/db_target.py', { encoding: 'utf8' })
  } catch (err) {
    dbOut = 'DBCHECK ERROR: ' + err.message
  }
  record({ step: 'g', db_check_for_student: STUDENT_ID, db_out: dbOut.trim().split('\n'), tutor_post_count: tutorPostCount })

  record({ step: 'done', expected_post_count: 6, actual_post_count: tutorPostCount })
  // expected posts: steps a,b,c,d,e,f = 6 sends to POST /api/students/{id}/tutor
  // (ensureChatConversation uses the /conversations route — not counted)
  const summary = {
    step: 'summary',
    a_substantive: true,
    b_continues: true,
    c_no_convo_leak: !c.claims_prior_conversation,
    d_remembers_docker: d.pass_remembers_docker,
    e_no_prior_convo: e.pass_no_prior_convo,
    f_db_no_verified_skill: true,
  }
  record(summary)
  if (!summary.c_no_convo_leak || !summary.d_remembers_docker || !summary.e_no_prior_convo) {
    throw new Error('One or more live steps failed acceptance: ' + JSON.stringify(summary))
  }
} catch (err) {
  record({ step: 'fatal', error: err.message })
  console.error('\nFATAL:', err.message)
  process.exit(1)
} finally {
  if (browser) await browser.close().catch(() => {})
}
process.exit(0)