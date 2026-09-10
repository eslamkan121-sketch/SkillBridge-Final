export type Role = 'Student' | 'Company' | 'University Admin'

export interface Session {
  token: string
  id: number
  email: string
  role: Role
  display_name: string
  auth_provider: string
  entity_type: 'student' | 'company' | 'university'
  verified?: boolean
  country?: string
  university?: string
  education_level?: string
  location?: string
  student?: Student
  company?: Company
  roles?: RoleRecord[]
  analysis?: Analysis | null
  learning?: LearningItem[]
}

export interface UniversityOption {
  country: string
  universities: string[]
}

export interface LocationOption {
  country: string
  cities: string[]
}

export interface Skill {
  id: number
  name: string
  category: string
}

export interface RequiredSkill {
  skill_id: number
  name: string
  category: string
  required_level: string
  skill_kind?: string
}

export interface RoleRecord {
  id: number
  company_id: number
  title: string
  description?: string
  company_name?: string
  company_location?: string
  required_skills: RequiredSkill[]
  is_reference?: number
  source?: string
  external_id?: string | null
}

export interface RolesResponse {
  roles: RoleRecord[]
  catalog: RoleRecord[]
  is_company: boolean
  company_id: number | null
  location?: string
}

export interface SelfReportedSkill {
  skill_id: number
  name: string
  category: string
  level: string
  source: string
  evidence?: string | null
}

export interface VerifiedSkill {
  skill_id: number
  name: string
  category: string
  level: string
  verified_at: string
}

export interface Student {
  id: number
  name: string
  email: string
  university: string | null
  education_level?: string
  target_role_id: number | null
  target_role?: RoleRecord
  cv_filename?: string | null
  cohort_confirmed?: number
  share_public?: number
  self_reported_skills: SelfReportedSkill[]
  verified_skills: VerifiedSkill[]
}

export interface SkillGap {
  skill_id: number
  skill_name: string
  category: string
  required_level: string
  student_level: string | null
  status: 'strong' | 'gap' | 'missing'
  verified: boolean
}

export interface BadgeInfo {
  code: string
  name: string
  desc: string
  hint?: string
  earned: boolean
  earned_at?: string | null
}

export interface ActivitySummary {
  student_id: number
  streak_days: number
  active_days: number
  xp: number
  level: number
  xp_into_level: number
  xp_per_level: number
  assessments_taken: number
  verified_skills: number
  badges: BadgeInfo[]
  leaderboard: { status: string; message?: string }
}

export interface Analysis {
  student_id: number
  role_id: number
  role_title: string
  company?: string
  match_score: number
  skill_gaps: SkillGap[]
  gap_count: number
}

export interface LearningResource {
  rank?: number
  type: string
  type_label?: string
  title: string
  url: string
  source?: string
  provider?: string
  helpfulness?: string
  reason?: string
  source_kind?: 'curated' | 'curated_fallback' | string
  available?: boolean | null
  status?: string
  is_direct_resource?: boolean
  estimated_minutes?: number
  verified?: boolean
  difficulty?: string
  cta?: string
  unavailable?: boolean
}

export interface RoadmapStep {
  step: number
  title: string
  objective: string
  resource_ranks: number[]
  practice: string
  checkpoint: string
  resources?: LearningResource[] | null
  resource_unavailable?: boolean
}

export interface Roadmap {
  summary: string
  steps: RoadmapStep[]
  resource_version?: number
}

export interface PlanModule {
  competency: string
  title: string
  objective: string
  estimated_minutes: number
  beyond_blueprint: boolean
}

export interface CoverageCheck {
  covered: boolean
  missing: string[]
}

export interface LearningItem {
  id: number
  skill_id: number
  skill_name: string
  category: string
  explanation: string
  practice_exercise: string
  mini_project: string
  resources: LearningResource[] | null
  roadmap: Roadmap | null
  progress?: number[]
  modules?: PlanModule[] | null
  blueprint_version?: string | null
  blueprint_competencies?: string[] | null
  coverage_check?: CoverageCheck | null
  generated_at: string
}

export interface TutorMessage {
  id: number
  skill_id: number | null
  tutor_id?: string | null
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface InterviewReply {
  reply: string
  turn: number
  /** Resolved conversation language, 'en' or 'ar', decided by the backend. */
  language?: string
}

export interface QuizQuestion {
  question: string
  type: 'multiple_choice' | 'free_text'
  options: string[]
  answer: string
  explanation: string
  competency?: string
}

export interface IntegrityFlag {
  code: string
  label: string
  severity: string
  detail: string
  source?: string
  duration_ms?: number
  occurred_at?: string
  incident_id?: string
}

export interface AssessmentAttempt {
  id: number
  student_id: number
  skill_id: number
  skill_name: string
  questions: string
  answers: string
  score: number
  passed: number
  flags: string
  per_question?: string
  level_before: string
  level_after: string
  created_at: string
}

export interface GeneratedAssessment {
  skill: Skill
  questions: QuizQuestion[]
  practice: boolean
  competency_coverage?: {
    required_level: string
    required: string[]
    labels: string[]
    covered: boolean
    missing: string[]
    valid: boolean
  } | null
  previous_results: PerQuestionResult[] | null
  previous_score: number | null
  previous_passed: boolean | null
}

export interface PerQuestionResult {
  index: number
  type: string
  correct: boolean
  answer: string
  competency?: string
}

export interface CompetencyResult {
  competency: string
  score: number
  passed: boolean
}

export interface AssessmentResult {
  score: number
  passed: boolean
  flags: IntegrityFlag[]
  per_question: PerQuestionResult[]
  competencies?: CompetencyResult[]
  full_coverage?: boolean
  level_before: string
  level_after: string
  analysis: Analysis | null
}

export interface UniversityStat {
  skill_name: string
  category: string
  count: number
  strong: number
  gap: number
  missing: number
  need_improvement_pct: number
}

export interface UniversityStatsResponse {
  rule: { min_cohort_size: number; satisfied: boolean; student_count: number; confirmed_count?: number }
  student_count?: number
  with_target_role?: number
  average_match_score?: number
  skill_stats?: UniversityStat[]
  verified_skills_total?: number
  assessments_total?: number
  message?: string
}

export interface CohortResponse {
  student_count: number
  confirmed_count: number
  min_cohort_size: number
  students: { index: number; confirmed: boolean }[]
}

export interface Company {
  id: number
  name: string
  industry: string
}

export interface Candidate {
  student_id: number
  name: string
  email: string
  university: string
  match_score: number
  gap_count: number
  verified_count: number
}

export interface SkillCoverageRow {
  skill_id: number
  skill_name: string
  category?: string
  required_level: string
  strong: number
  gap: number
  missing: number
  coverage_pct: number
  n_candidates: number
}

export interface RoleSkillCoverage {
  role_id: number
  role_title: string
  candidate_count: number
  skills: SkillCoverageRow[]
}

export interface GoogleConfig {
  configured: boolean
  demo: boolean
}

export interface PublicVerifiedSkill {
  skill_id: number
  name: string
  category: string
  level: string
  verified_at: string
}

export interface PublicProfile {
  student_id: number
  name: string
  university: string
  target_role: { title: string; company?: string } | null
  verified_skills: PublicVerifiedSkill[]
}

export interface RecentJob {
  id?: string
  title: string
  company: string
  url: string
  date?: string
  tags?: string[]
  location?: string
  country?: string
  city?: string
  source?: string
  source_url?: string
  description?: string
  employment_type?: string
  workplace_type?: string
  salary?: string
  required_skills?: string[]
  seniority?: string
  match_pct?: number
  match_reason?: string
  location_tier?: 'city' | 'country' | 'country_remote' | 'global_remote' | 'unknown' | 'different'
  location_label?: string
  is_expired?: boolean
  expires_at?: string
  listed_days_ago?: number
}

export type ProviderStatus = 'ok' | 'failed' | 'skipped'

export interface ProviderReport {
  source: string
  status: ProviderStatus
  count?: number
  reason?: string
  error?: string
}

export interface RecentJobsResponse {
  source: 'live' | 'empty' | 'unavailable' | 'no-cv'
  jobs: RecentJob[]
  groups?: { local_count: number; broader_count: number; other_count: number }
  providers?: ProviderReport[]
}

export interface EscoOccupation {
  title: string
  uri: string
  skills: string[]
  skill_count: number
}

export interface EscoMarketResponse {
  source: 'ESCO'
  query: string
  occupations: EscoOccupation[]
  status?: 'ok' | 'unavailable'
  message?: string
}

export type RecommendationSource = 'company' | 'catalog' | 'esco'

export interface MatchedSkillDetail {
  name: string
  student_level: string | null
  required_level: string | null
  verified: boolean
}

export interface RoleRecommendation {
  role_id: number | null
  external_id?: string | null
  title: string
  source: RecommendationSource
  company_name?: string | null
  match_score: number
  confidence: string
  matched_skills: MatchedSkillDetail[]
  missing_key_skills: string[]
  verified_matches: string[]
  reason: string
  selectable: boolean
  regulated_warning?: boolean
  skills?: string[]
}

export interface RoleRecommendationsResponse {
  recommendations: RoleRecommendation[]
  note: string
  esco_status: 'ok' | 'unavailable'
  source_counts: Partial<Record<RecommendationSource, number>>
}

export interface CareerRoadmapSkill {
  name: string
  category: string
}

export interface CareerRoadmapPhase {
  phase: number
  title: string
  goal: string
  skills: CareerRoadmapSkill[]
  deliverables: string[]
  checkpoint: string
}

export interface CareerRoadmap {
  role_title: string | null
  summary: string
  student_starting_point?: number
  phase_count: number
  phases: CareerRoadmapPhase[]
}

// ------------------------------------------------------------------ learning diagnostic

export type DiagnosticQuestionType = 'mcq' | 'free_text'
export type DiagnosticDifficulty = 'beginner' | 'intermediate' | 'advanced'
export type TopicStatus = 'mastered' | 'developing' | 'weak'

export interface DiagnosticQuestion {
  id: string
  type: DiagnosticQuestionType
  question: string
  options: string[]
  correct_answer: string
  competency: string
  difficulty: DiagnosticDifficulty
}

export interface TopicResult {
  competency: string
  label: string
  score: number
  status: TopicStatus
  correct: number
  total: number
}

export interface GeneratedDiagnostic {
  skill: Skill
  topics: string[]
  questions: DiagnosticQuestion[]
  diagnostic_id: number
}

export interface DiagnosticResult {
  id: number
  student_id: number
  skill_id: number
  questions: DiagnosticQuestion[] | null
  answers: string[] | null
  score: number | null
  topic_results: TopicResult[]
  weak_topics: string[]
  strong_topics: string[]
  created_at: string | null
  completed_at: string | null
}

// ------------------------------------------------------------------ personalized path

export interface PersonalizedPathItem {
  id: string
  competency: string
  title: string
  topic_status: 'weak' | 'developing'
  diagnostic_score: number
  action: 'learn' | 'review'
  order: number
  estimated_minutes: number
  state: string
}

export interface PersonalizedStage {
  id: string
  stage: string
  action: string
  order: number
  estimated_minutes: number
  state: string
}

export interface PersonalizedPath {
  id: number
  student_id: number
  skill_id: number
  diagnostic_id: number
  required_level: string
  items: PersonalizedPathItem[]
  stages: PersonalizedStage[]
  skipped_mastered: string[]
  progress: string[]
  created_at: string
}

export type PersonalizedPathResponse = PersonalizedPath | { diagnostic_required: true; path: null }

export interface FinalAssessmentReadiness {
  ready: boolean
  required: string[]
  satisfied: string[]
  missing: string[]
}

export interface FinalAssessmentStatus {
  skill: { id: number; name: string }
  required_level: string
  diagnostic_completed: boolean
  path_exists: boolean
  has_blueprint: boolean
  readiness: FinalAssessmentReadiness
}

export interface LessonQuestion {
  id: string
  type: 'mcq' | 'free_text'
  question: string
  options?: string[]
  correct_answer: string
  explanation?: string
  competency?: string
  difficulty?: string
}

export interface LessonGroundingSource {
  title: string
  url: string
  source?: string
}

export interface LessonSelfCheck {
  passed: boolean
  checks: { name: string; passed: boolean; note?: string }[]
  flags: string[]
}

export interface LessonSection {
  title: string
  explanation: string
  key_ideas?: string[]
  key_terms?: Record<string, string>
  type?: string
  content?: string
  job_relevance?: string
  common_mistake?: string
  worked_example?: string
  depth_note?: string
  version_note?: string
  grounding_sources?: LessonGroundingSource[]
  unsupported_claims?: string[]
}

export interface LessonPractice {
  type: string
  title?: string
  task?: string
  response_type?: string
  competency?: string
  questions?: LessonQuestion[]
}

export interface LessonContent {
  learn: LessonSection
  example: LessonSection
  practice: LessonPractice
  resources?: LearningResource[] | null
  mini_check: { questions: LessonQuestion[] }
  self_check?: LessonSelfCheck
}

export interface MiniCheckResult {
  score: number
  correct: number
  total: number
  passed: boolean
}

export type PracticeStatus = 'needs_review' | 'ready'
export type PracticeSource = 'ai' | 'fallback'
export type PracticeTaskSource = 'lesson' | 'remediation'

export interface PracticeTaskQuestion {
  id: string
  type: string
  question: string
  options?: string[]
  correct_answer?: string
  competency?: string
  difficulty?: string
}

export interface PracticeTask {
  source: PracticeTaskSource
  source_attempt_id: number | null
  type: string
  questions: PracticeTaskQuestion[]
}

export interface RemediationReview {
  focus_points: string[]
  explanation: string
  targeted_example: string
  follow_up_task: string
  source: PracticeSource
  practice_attempt_id?: number | null
}

export interface PracticeAttempt {
  id: number
  student_id: number
  skill_id: number
  personalized_path_id: number
  lesson_id: number
  competency: string
  answer: string
  practice_task?: PracticeTask | null
  score: number
  status: PracticeStatus
  strengths: string[]
  missing_points: string[]
  feedback: string
  next_action: string
  source: PracticeSource
  remediation?: RemediationReview | null
  created_at: string
}

export interface PracticeAttemptsResponse {
  latest: PracticeAttempt | null
  attempts: PracticeAttempt[]
  count: number
}

export interface Lesson {
  id: number
  student_id: number
  skill_id: number
  personalized_path_id: number
  competency: string
  title: string
  action: 'learn' | 'review'
  content: LessonContent
  state: 'not_started' | 'in_progress' | 'completed'
  mini_check_result: MiniCheckResult | null
  created_at: string
  completed_at: string | null
}

// ------------------------------------------------------------------ global AI copilot context

export type CopilotPage = 'dashboard' | 'skills_roles' | 'learning' | 'jobs' | 'career_roadmap' | 'mock_interview' | 'assessment' | 'scenarios'

/** Unified working mode of the Global Copilot (validated on the backend). */
export type TutorMode = 'chat' | 'practice' | 'discuss' | 'interview'

export type TutorLanguage = 'auto' | 'en' | 'ar'

export interface CopilotContext {
  page: CopilotPage
  skillId: number | null
  competency: string | null
  jobTitle: string | null
  jobUrl: string | null
}

export interface TutorPreferences {
  tutor_id: string
  mode: string
  language: TutorLanguage
}

// ------------------------------------------------------------------ practice scenarios

export type ScenarioDifficulty = 'beginner' | 'intermediate' | 'advanced'
export type ScenarioStatus = 'not_started' | 'in_progress' | 'completed'
export type ScenarioStepType = 'choice' | 'multi'

export interface ScenarioCard {
  id: string
  title: string
  description: string
  role_title: string
  difficulty: ScenarioDifficulty
  difficulty_label: string
  difficulty_icon: string
  estimated_minutes: number
  estimated_time_label: string
  category: string
  category_label: string
  category_icon: string
  skills: string[]
  steps_count: number
  status: ScenarioStatus
  best_score: number | null
  attempts_count: number
  last_outcome_title: string | null
  last_outcome_tone: string | null
}

export interface ScenarioCategory {
  key: string
  label: string
  icon: string
}

export interface ScenarioPhase {
  label: string
  icon: string
  key: string
}

export interface ScenarioLibraryStats {
  scenarios_completed: number
  attempts: number
  average_score: number | null
  practice_time_minutes: number
  skills_practiced: number
}

export interface ScenarioLibrary {
  scenarios: ScenarioCard[]
  recommended: string[]
  categories: ScenarioCategory[]
  stats: ScenarioLibraryStats
  target_role: string | null
  availability: 'ok' | 'none'
  availability_reason: string
  note: string
}

export interface ScenarioEvidenceRow {
  label: string
  value: string
}

export interface ScenarioEvidence {
  id: string
  tab: string
  icon: string
  title: string
  content: ScenarioEvidenceRow[]
  has_data: boolean
}

export interface ScenarioOption {
  id: string
  label: string
}

export interface ScenarioDecision {
  id: string
  label: string
  icon: string
}

export interface ScenarioProgress {
  step_number: number
  total_steps: number
  current_phase: string
  phases: ScenarioPhase[]
}

export interface ScenarioStepView {
  id: string
  index: number
  total: number
  title: string
  phase: string
  phase_label: string
  situation: string
  intro: string
  evidence: ScenarioEvidence[]
  decisions: ScenarioDecision[]
  multi: boolean
  options: ScenarioOption[]
  type: ScenarioStepType
}

export interface ScenarioPlayer {
  attempt_id: number
  scenario_id: string
  scenario_title: string
  status: 'in_progress'
  step: ScenarioStepView
  progress: ScenarioProgress
  outcome: string | null
}

export interface ScenarioHint {
  hint: string
  explanation: string
  source: 'curated'
  hints_used: number
  hints_capped: boolean
}

export interface ScenarioOutcome {
  key: string
  title: string
  icon: string
  tone: 'good' | 'bad' | null
  summary: string
}

export interface ScenarioComponentScore {
  key: string
  label: string
  pct: number | null
}

export interface ScenarioSkillScore {
  name: string
  pct: number | null
}

export interface ScenarioSkillDelta {
  skill: string
  level_before: string | null
  level_after: string | null
  note: string
}

export interface ScenarioDecisionRow {
  step_title: string
  decision: string
  icon: string
  verdict: 'good' | 'neutral' | 'bad'
  good: boolean
  feedback: string
  consequence: string
}

export interface ScenarioResult {
  completed: true
  attempt_id: number
  scenario_id: string
  title: string
  difficulty_icon: string
  difficulty_label: string
  score: number
  verdict_label: string
  verdict_tone: 'great' | 'good' | 'fair' | 'review'
  outcome: ScenarioOutcome
  components: ScenarioComponentScore[]
  skills: ScenarioSkillScore[]
  skills_updated: ScenarioSkillDelta[]
  match: { before: number | null; after: number | null; delta: number | null }
  decision_review: ScenarioDecisionRow[]
  strengths: string[]
  improvements: string[]
  hints_used: number
  evidence_inspected_pct: number | null
  certified: false
  note: string
}

export interface SavedRolesResponse {
  role_ids: number[]
}
