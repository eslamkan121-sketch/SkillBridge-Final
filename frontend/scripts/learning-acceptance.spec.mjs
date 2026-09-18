/** Browser acceptance. Set both URL variables to a disposable instance before running. */
import { test, expect, chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const FRONTEND = process.env.SKILLBRIDGE_FRONTEND_URL
const BACKEND = process.env.SKILLBRIDGE_BACKEND_URL
const OUT = path.join(process.cwd(), 'test-results', 'learning-acceptance')
const email = `learning.acceptance.${Date.now()}@example.test`
const password = 'SyntheticAcceptance9!'
let browser, context, page, token, studentId, pythonId, sqlId, verifiedBefore
test.describe.configure({ mode: 'serial' })
test.setTimeout(60000)

async function api(pathname, options = {}) {
  const response = await fetch(`${BACKEND}${pathname}`, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) } })
  const text = await response.text()
  if (!response.ok) throw new Error(`${options.method || 'GET'} ${pathname} -> ${response.status}: ${text}`)
  return text ? JSON.parse(text) : null
}
async function shot(name) { fs.mkdirSync(OUT, { recursive: true }); await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true }) }
async function closeOnboarding() {
  const dialog = page.getByRole('dialog', { name: 'Find your SkillBridge mentor' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Close (decide later)' }).click()
  await expect(dialog).toBeHidden()
}
async function learning() {
  // "Decide later" deliberately hides this first-run prompt for the current
  // page only, so a reload may legitimately display it again. Close it through
  // its own UI each time before touching sidebar navigation.
  const onboarding = page.getByRole('dialog', { name: 'Find your SkillBridge mentor' })
  const nav = page.getByRole('button', { name: 'Learning', exact: true })
  if (await onboarding.isVisible()) await closeOnboarding()
  await expect(nav).toBeEnabled()
  try {
    await nav.click({ timeout: 10_000 })
  } catch (error) {
    // The first-run prompt is loaded asynchronously. If it appeared between
    // the visibility check and the click, close it through its own action and
    // retry navigation once; any other click failure remains a real failure.
    if (!await onboarding.isVisible()) throw error
    await closeOnboarding()
    await nav.click()
  }
  await expect(page.getByRole('heading', { name: 'Learning', exact: true })).toBeVisible()
}
async function skill(name) {
  const card = page.locator('.learning-skill-card').filter({ hasText: name }).first()
  await expect(card).toBeVisible(); await card.click()
  await expect(page.locator('#skill-detail').getByRole('heading', { name, exact: true })).toBeVisible()
}
async function createPath(expected) {
  await page.getByRole('button', { name: 'Start Diagnostic', exact: true }).click()
  const questions = page.locator('.diag-question')
  await expect(questions).toHaveCount(expected.length)
  await expect(questions.locator('.diag-comp-chip').allTextContents()).resolves.toEqual(expected)
  // Use the final visible choice for each fixed curated question. It is a
  // deliberately non-correct distractor in these authored diagnostics, so the
  // resulting path includes every curated topic without direct score writes.
  for (let i = 0; i < expected.length; i++) await questions.nth(i).locator('input[type="radio"]').last().check()
  await page.getByRole('button', { name: 'Submit Diagnostic', exact: true }).click()
  const create = page.getByRole('button', { name: 'Create My Learning Path', exact: true })
  await expect(create).toBeVisible(); await create.click()
  await expect(page.locator('.pp-item')).toHaveCount(new Set(expected).size)
}
async function resume(topic) {
  // Scope to the active-path card; generic dashboard buttons share this label.
  const skillName = topic.startsWith('SQL') ? 'SQL' : 'Python'
  const card = page.locator('.continue-card').filter({ hasText: skillName }).first()
  await expect(card).toBeVisible()
  // Wait for the selected skill's own path panel to resolve before exercising
  // its global Continue action. The card and panel load independently.
  await expect(page.locator('#skill-detail .pp-item').first()).toBeVisible({ timeout: 30_000 })
  await card.getByRole('button', { name: 'Continue Learning', exact: true }).click()
  const lesson = page.locator('.lesson-view:not(.lesson-loading-skel)')
  await expect(lesson).toContainText(topic, { timeout: 30_000 })
  await expect(page.locator('.diagnostic-questions')).toHaveCount(0)
}
async function complete(answers, answer, next = false) {
  await page.getByRole('button', { name: 'Practice', exact: true }).click()
  const field = page.locator('textarea.practice-response')
  await expect(field).toBeVisible(); await field.fill(answer)
  await page.getByRole('button', { name: 'Submit Practice', exact: true }).click()
  const toCheck = page.getByRole('button', { name: 'Continue to Mini Check', exact: true })
  await expect(toCheck).toBeVisible(); await toCheck.click()
  for (const answerText of answers) await page.getByRole('button', { name: answerText, exact: true }).click()
  await page.getByRole('button', { name: 'Submit Mini Check', exact: true }).click()
  await expect(page.locator('.lesson-result')).toContainText('topic completed')
  if (next) await page.getByRole('button', { name: 'Next Lesson', exact: true }).click()
}
async function completedDiagnostic(skillId) {
  const diag = await api(`/api/students/${studentId}/learning/${skillId}/diagnostic/generate`, { method: 'POST', body: '{}' })
  return api(`/api/students/${studentId}/learning/${skillId}/diagnostic/submit`, { method: 'POST', body: JSON.stringify({ diagnostic_id: diag.diagnostic_id, answers: diag.questions.map(q => q.options[0]) }) })
}

test.beforeAll(async () => {
  if (!FRONTEND || !BACKEND) throw new Error('Set SKILLBRIDGE_FRONTEND_URL and SKILLBRIDGE_BACKEND_URL to the isolated test instance.')
  const status = await fetch(`${BACKEND}/api/system/db-status`)
  if (!status.ok) throw new Error(`Backend unavailable at ${BACKEND}: ${status.status}`)
  browser = await chromium.launch({ headless: true }); context = await browser.newContext({ viewport: { width: 1440, height: 900 } }); page = await context.newPage()
})
test.afterEach(async ({}, info) => { if (info.status !== info.expectedStatus) await shot(`FAIL-${info.title.replace(/[^a-z0-9]+/gi, '-')}`) })
test.afterAll(async () => { await context?.close(); await browser?.close() })

test('setup uses UI authentication and closes the actual mentor onboarding modal', async () => {
  await page.goto(`${FRONTEND}/login`)
  await page.getByRole('button', { name: 'Create account', exact: true }).first().click()
  const form = page.locator('form')
  // These visible labels are presentation text, not HTML label-for pairs.
  // Keep the locator inside the signup form and use the real field order.
  const inputs = form.locator('input')
  await inputs.nth(0).fill('Learning Acceptance Synthetic')
  await inputs.nth(1).fill(email); await inputs.nth(2).fill(password)
  const selects = form.locator('select')
  await selects.first().selectOption({ label: 'Student seeking roles' }); await selects.nth(1).selectOption({ label: 'Egypt' })
  await expect(selects.nth(2)).toBeVisible(); await selects.nth(2).selectOption({ index: 1 }); await selects.last().selectOption({ index: 1 })
  await form.getByRole('button', { name: 'Create account', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  token = await page.evaluate(() => localStorage.getItem('skillbridge_token')); expect(token).toBeTruthy()
  const me = await api('/api/auth/me'); studentId = me.student.id; verifiedBefore = me.student.verified_skills || []
  await closeOnboarding()
  const roles = await api('/api/roles'); const analyst = [...roles.catalog, ...roles.roles].find(role => role.title === 'Data Analyst')
  expect(analyst).toBeTruthy(); await api(`/api/students/${studentId}`, { method: 'PUT', body: JSON.stringify({ target_role_id: analyst.id }) })
  // /learning is a history endpoint and is empty for a new learner. Resolve
  // canonical skill IDs from the authenticated catalog instead of treating an
  // empty history as a setup success or a missing curriculum.
  const skills = await api('/api/skills')
  const python = skills.find(row => row.name === 'Python'), sql = skills.find(row => row.name === 'SQL')
  if (!python || !sql) throw new Error(`Catalog did not expose Python and SQL: ${JSON.stringify(skills.map(row => row.name))}`)
  pythonId = python.id; sqlId = sql.id
})

test('current path and newer unfinished diagnostic resume Python Functions', async () => {
  await learning(); await skill('Python')
  await createPath(['python_functions', 'python_functions', 'python_functions', 'python_error_handling', 'python_error_handling', 'python_error_handling'])
  await page.reload(); await learning(); await skill('Python'); await resume('Python Functions')
  await api(`/api/students/${studentId}/learning/${pythonId}/diagnostic/generate`, { method: 'POST', body: '{}' })
  await page.reload(); await learning(); await skill('Python'); await resume('Python Functions')
  await shot('current-path-after-newer-unfinished-diagnostic')
})

test('stale path exposes refresh instead of opening a lesson', async () => {
  await completedDiagnostic(pythonId)
  await page.reload(); await learning(); await skill('Python')
  const refresh = page.getByRole('button', { name: 'Refresh path from latest diagnostic', exact: true })
  await expect(refresh).toBeVisible({ timeout: 30_000 }); await expect(page.locator('.lesson-view')).toHaveCount(0)
  await refresh.click(); await expect(refresh).toHaveCount(0); await expect(page.locator('.pp-item')).toHaveCount(2)
  await shot('stale-path-refresh-action')
})

test('Python Functions and Error Handling complete through Practice and Mini Check', async () => {
  await resume('Python Functions')
  const before = await page.getByRole('button', { name: 'Dashboard', exact: true }).boundingBox()
  await page.getByRole('button', { name: 'العربية المصرية', exact: true }).click(); await expect(page.locator('.lesson-content')).toHaveAttribute('dir', 'rtl')
  await page.getByRole('button', { name: 'مثال', exact: true }).click(); await expect(page.locator('.lesson-content pre').first()).toHaveCSS('direction', 'ltr')
  expect((await page.getByRole('button', { name: 'Dashboard', exact: true }).boundingBox()).x).toBe(before.x)
  await page.getByRole('button', { name: 'English', exact: true }).click(); await expect(page.locator('.lesson-content')).toHaveAttribute('dir', 'ltr')
  await complete(['return total', 'A parameter', '25'], 'def celsius_to_fahrenheit(celsius):\n    return (celsius * 9 / 5) + 32\n\nreturn lets the caller reuse and test the converted value.', true)
  await expect(page.locator('.lesson-view')).toContainText('Python Error Handling')
  await complete(['ValueError', 'None', 'It handles the expected invalid-number input without hiding every other bug'], 'def parse_score(text):\n    try:\n        return int(text)\n    except ValueError:\n        return None\n\nA bare except could hide an unrelated programming bug.')
})

test('SQL Queries & Filtering completes; both paths persist and Verified Skills stay identical', async () => {
  await page.reload(); await learning(); await skill('SQL')
  await createPath(['sql_queries_filtering', 'sql_queries_filtering', 'sql_queries_filtering'])
  await page.reload(); await learning(); await skill('SQL'); await resume('SQL Queries & Filtering')
  await complete(["WHERE city = 'Cairo'", 'The name and email columns', "SELECT name, email FROM customers WHERE city = 'Cairo' AND status = 'active';"], "SELECT name, email\nFROM customers\nWHERE city = 'Cairo'\n  AND status = 'active';\n\nThe city condition keeps Cairo customers, and the status condition keeps active customers.")
  await page.reload(); await learning(); await skill('Python'); await expect(page.locator('#skill-detail')).toContainText('2/2 topics complete')
  await skill('SQL'); await expect(page.locator('#skill-detail')).toContainText('1/1 topics complete')
  expect((await api(`/api/students/${studentId}`)).verified_skills || []).toEqual(verifiedBefore)
  await shot('completed-and-persisted')
})
