import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const page = fs.readFileSync(path.join(root, 'src/pages/LearningPage.tsx'), 'utf8')
const cards = fs.readFileSync(path.join(root, 'src/components/learning.tsx'), 'utf8')

function expect(value, message) {
  if (!value) throw new Error(message)
}

expect(page.includes('api.student(studentId)'), 'My Skills must refresh from the student profile API')
expect(page.includes('studentProfile?.self_reported_skills'), 'My Skills must use stored self-reported profile skills')
expect(page.includes('studentProfile?.verified_skills'), 'My Skills must include stored officially verified skills')
expect(page.includes("if (activeTab === 'my-skills') return profileSkills"), 'My Skills must not use role skill gaps')
expect(page.includes("if (activeTab === 'continue') return continueSkills"), 'Continue Learning must render persisted incomplete paths')
expect(page.includes("if (activeTab === 'completed') return completedLearningSkills"), 'Completed must render completed learning paths')
expect(page.includes('const stepperRows = skillsForTab.map'), 'The primary panel must follow the selected tab dataset')
expect(page.includes('const currentTabCopy = tabCopy[activeTab]'), 'The primary panel heading must describe the selected tab')
expect(page.includes('profileSource={gap.profileSource}'), 'Profile skill provenance must reach rendered cards')
expect(cards.includes('Profile claim') && cards.includes('Officially verified'), 'Profile claims and official verification must be distinct')
console.log('Learning tab data contract: OK')
