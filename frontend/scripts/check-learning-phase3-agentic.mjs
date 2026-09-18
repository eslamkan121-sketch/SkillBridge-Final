import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const page = fs.readFileSync(path.join(root, 'src/pages/LearningPage.tsx'), 'utf8')
const types = fs.readFileSync(path.join(root, 'src/lib/types.ts'), 'utf8')
const api = fs.readFileSync(path.join(root, 'src/lib/api.ts'), 'utf8')

function expect(value, message) {
  if (!value) throw new Error(message)
}

for (const action of ['EXPLAIN', 'PRACTICE', 'GIVE_HINT', 'REVIEW_PREREQUISITE', 'MINI_CHECK', 'ADVANCE', 'REQUEST_REASSESSMENT']) {
  expect(types.includes(`'${action}'`), `missing LearningAgentActionType ${action}`)
}
expect(api.includes('learningAgentNext'), 'Learning page must call the real orchestrator API')
expect(page.includes('agentDecision.action_type'), 'agent action is not rendered')
expect(page.includes('Why this step?'), 'agent evidence disclosure is missing')
expect(page.includes('lessonSubmitPractice') && page.includes('lessonMiniCheck'), 'practice/Mini Check API integration is missing')
expect(page.includes('learner code is not executed here'), 'UI must disclose non-execution of submitted Python')
expect(page.includes('Static code check') && page.includes('فحص ثابت للكود'), 'UI must label non-executing static checks clearly')
expect(page.includes("static_check?.status === 'looks_structurally_sound'"), 'a structurally sound stored check must enable the real Mini Check handoff')
expect(page.includes("sb_learning_language") && page.includes('العربية المصرية'), 'persistent English/Arabic learning control is missing')
expect(page.includes('Retry recommendation') && page.includes('setRetryKey'), 'retry/error states are missing')
expect(page.includes('View full roadmap'), 'roadmap return is missing')
console.log('Phase 3 agentic learning UI contract: OK')
