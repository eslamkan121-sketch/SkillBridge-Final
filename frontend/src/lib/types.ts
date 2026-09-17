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
  canonical_role_id?: number | null
  canonical_mapping_updated_at?: string | null
  family?: string | null
  source_version?: string | null
  canonical_status?: string
  role_key?: string | null
}

export interface RecentRole {
  id: number
  title: string
  company_name?: string | null
  family?: string | null
  source?: string
  source_version?: string | null
  is_reference?: number
  external_id?: string | null
  viewed_at: string
}

export interface RecentRolesResponse {
  roles: RecentRole[]
}

export interface RoleAlias {
  id: number
  alias: string
  alias_type: string
  language: string
  created_at: string
}

export interface RoleIscoCode {
  id: number
  isco_code: string
  source: string
  source_ref?: string | null
  created_at: string
}

export interface RoleSkillSource {
  skill_id: number
  source?: string | null
  source_uri?: string | null
  attested_at?: string | null
}

export interface RoleRelated {
  parent: RoleRecord | null
  children: RoleRecord[]
  siblings: RoleRecord[]
  supersedes: RoleRecord[]
  superseded_by: RoleRecord | null
}

export interface RoleProvenance {
  role_id: number
  title: string
  source: string
  role_key?: string | null
  canonical_status: string
  source_version?: string | null
  external_id?: string | null
  is_local_authoring: boolean
  family?: string | null
  parent_role_id?: number | null
  fetched_at?: string | null
  imported_at?: string | null
  updated_at?: string | null
  aliases: RoleAlias[]
  isco_codes: RoleIscoCode[]
  skill_sources: Record<number, RoleSkillSource>
  mapping: RoleMappingTarget | null
  related: RoleRelated
}

export interface RoleMappingTarget {
  canonical_role_id: number
  mapped_title: string
  source: string
  external_id?: string | null
  mapped_at?: string | null
}

export interface RoleMappingMatch {
  role_id: number
  title: string
  source: string
  confidence: number
  confidence_label: 'High' | 'Medium' | 'Low'
  explanation: string
}

export interface RoleMappingSuggestion {
  role_id: number
  mapped: RoleMappingTarget | null
  matches: RoleMappingMatch[]
  ambiguous: boolean
}

export interface RoleMappingEvent {
  event_id: number
  action: 'mapped' | 'unmapped' | 'changed'
  from_canonical_role_id?: number | null
  from_title?: string | null
  to_canonical_role_id?: number | null
  to_title?: string | null
  actor_user_id: number
  actor_role: string
  created_at: string
}

export interface RolesResponse {
  roles: RoleRecord[]
  catalog: RoleRecord[]
  is_company: boolean
  company_id: number | null
  location?: string
  role_data_version?: string | null
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
  conversation_id?: number | null
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface TutorConversation {
  id: number
  student_id: number
  tutor_id: string
  title: string
  created_at: string
  updated_at: string
  message_count?: number
  last_message_at?: string | null
  preview?: string | null
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
  fingerprint?: string
  work_type?: string
  listing_status?: string
  provider?: string
  provider_job_id?: string
  apply_url?: string
  description_excerpt?: string
  published_date?: string
  fetched_at?: string
  link_state?: string
  link_reason?: string
  provenance?: Record<string, { value?: unknown; basis?: string }>
}

export type ProviderStatus = 'ok' | 'failed' | 'skipped'

export interface ProviderReport {
  source: string
  status: ProviderStatus
  count?: number
  reason?: string
  error?: string
  health?: string
}

export interface RecentJobsResponse {
  source: 'live' | 'empty' | 'unavailable' | 'no-cv'
  jobs: RecentJob[]
  groups?: { local_count: number; broader_count: number; other_count: number }
  providers?: ProviderReport[]
  status?: 'fresh' | 'cached' | 'stale_fallback' | 'unavailable'
  cache?: { hits?: number; misses?: number; avg_fetch_ms?: number }
}

export interface JobLinkReport {
  id: number
  fingerprint: string
  url: string
  title: string
  provider: string
  reported_at: string
}

export interface JobsHealthPayload {
  jobs?: {
    providers_total?: number
    providers_available?: string[]
    providers_health?: Record<string, string>
    last_error_by_provider?: Record<string, string>
    last_build_at?: string | null
    cache?: { hits?: number; misses?: number; avg_fetch_ms?: number }
  }
}

export type JobStage = 'saved' | 'preparing' | 'applied' | 'screening' | 'interview' | 'offer' | 'hired' | 'rejected' | 'withdrawn' | 'archived_or_expired'

export const JOB_STAGES: JobStage[] = ['saved', 'preparing', 'applied', 'screening', 'interview', 'offer', 'hired', 'rejected', 'withdrawn', 'archived_or_expired']

export interface TrackerStageHistory {
  id: number
  stage: JobStage
  changed_from: JobStage | null
  note: string
  created_at: string
}

export interface TrackedJob {
  id: number
  student_id: number
  fingerprint: string
  title: string
  company: string
  url: string
  apply_url: string
  location: string
  country: string
  provider?: string
  source?: string
  match_pct?: number
  work_type?: string
  seniority?: string
  listing_status?: string
  link_state?: string
  is_expired: boolean
  stage: JobStage
  note: string
  interview_date?: string
  application_deadline?: string
  created_at: string
  updated_at: string
  history: TrackerStageHistory[]
}

export interface TrackerResponse {
  items: TrackedJob[]
  counts: Record<JobStage, number>
}

export interface SaveJobRequest {
  fingerprint: string
  location?: string
  country?: string
  market?: string
}

// ---- Phase Q: prepare-for-job readiness (backend prepare_job_view) ----

export type JobPrepareSkillStatus = 'verified' | 'self_reported' | 'gap' | 'no_path'

export interface JobPrepareSkill {
  name: string
  skill_id: number | null
  status: JobPrepareSkillStatus
  student_level?: string
  verified_at?: string
}

export interface JobPreparePayload {
  job: {
    title: string
    company: string
    location_label?: string | null
    match_pct?: number | null
    apply_url: string
    listing_status?: string | null
    provider?: string | null
  }
  skills: JobPrepareSkill[]
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

// ---- Phase J: explainable match breakdowns (backend match_explain.py) ----

export interface MatchAdjustmentLine {
  label: string
  label_long?: string
  points: number
}

export interface TargetRoleRequirement {
  skill_id: number
  skill_name: string
  category?: string | null
  required_level: string | null
  student_level: string | null
  status: string
  evidence: 'verified' | 'self_reported' | 'none'
  contribution_points: number
  max_points: number
}

export interface TargetRoleMatchBreakdown {
  formula: string
  version: string
  as_of: string
  role_data_version: string
  role_title: string | null
  company?: string | null
  requirements: TargetRoleRequirement[]
  total_points: number
  max_points: number
  raw_percent: number
  displayed_percent: number
  adjustment_lines: MatchAdjustmentLine[]
  evidence_precedence: string
  missing_data: string[]
  next_action: string
}

export interface RoleMatchRequirement {
  name: string
  required_level: string | null
  student_level: string | null
  evidence: 'verified' | 'self_reported' | 'none'
  essential: boolean
  weight: number
  level_factor: number | null
  credit: number
  is_discovery: boolean
  verified: boolean
}

export interface RoleMatchBreakdown {
  formula: string
  version: string
  as_of: string
  role_data_version: string
  role_id: number | null
  external_id?: string | null
  title: string | null
  source: string
  company_name?: string | null
  requirements: RoleMatchRequirement[]
  total_weight: number
  earned_weight: number
  raw_percent: number
  displayed_percent: number
  adjustment_lines: MatchAdjustmentLine[]
  matched_skills: MatchedSkillDetail[]
  missing_key_skills: string[]
  verified_matches: string[]
  evidence_precedence: string
  missing_data: string[]
  next_action: string
}

export interface JobMatchRelevance {
  final: number
  base_points: number
  family_bonus: number
  family_cap_70: number | null
  family_top_bump: number | null
  title_fallback_boost: number | null
  minor_bonus: number
  verified_bonus: number
  fresh_bonus: number
  title_family_hit: boolean
}

export interface JobMatchExperience {
  points: number
  label: string
  job_seniority: number
  student_seniority: number
}

export interface JobMatchLocation {
  tier: 'city' | 'country' | 'country_remote' | 'global_remote' | 'unknown' | 'different'
  points: number
  label: string
}

export interface JobMatchMatches {
  matched: string[]
  title_hits: string[]
  minor_hits: string[]
  verified_hits: string[]
}

export interface JobMatchConstraints {
  location: { tier: string; label: string; supported: boolean }
  work_type: { value: string; supported: boolean }
  seniority: { job: number; student: number; supported: boolean }
}

export interface JobMatchBreakdown {
  formula: string
  version: string
  as_of: string
  role_data_version: string
  role_title: string
  job: {
    title?: string
    company?: string
    location_label?: string | null
    work_type?: string | null
    seniority?: string | null
    listed_days_ago?: number | null
    listing_status?: string | null
    apply_url?: string | null
  }
  components: {
    relevance: JobMatchRelevance
    experience: JobMatchExperience
    location: JobMatchLocation
  }
  lines: MatchAdjustmentLine[]
  displayed_percent: number
  matches: JobMatchMatches
  verified_skill_hits: string[]
  other_matched_keywords: string[]
  constraints: JobMatchConstraints
  evidence_note: string
  next_action: string
}

export type MatchBreakdownPayload =
  | TargetRoleMatchBreakdown
  | RoleMatchBreakdown
  | JobMatchBreakdown

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
  latest_diagnostic_id?: number | null
  stale?: boolean | null
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
  misconception_hint?: string
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
  starter_code?: string
  automated_tests?: { input: unknown[]; expected: unknown }[]
}

export interface CanonicalLessonMetadata {
  source: string
  version: string
  prerequisites: { competency: string; relationship: string; why: string }[]
  roadmap_rationale: string
}

export interface LessonContent {
  learn: LessonSection
  example: LessonSection
  practice: LessonPractice
  resources?: LearningResource[] | null
  mini_check: { questions: LessonQuestion[] }
  /** Reviewed display translations; scoring still uses the canonical questions. */
  locales?: Partial<Record<'ar', {
    learn?: LessonSection
    example?: LessonSection
    practice?: LessonPractice
  }>>
  self_check?: LessonSelfCheck
  canonical?: CanonicalLessonMetadata
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
  static_check?: { status: 'looks_structurally_sound' | 'needs_fix'; checks: string[]; note: string } | null
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

export type LearningAgentActionType = 'EXPLAIN' | 'PRACTICE' | 'GIVE_HINT' | 'REVIEW_PREREQUISITE' | 'MINI_CHECK' | 'ADVANCE' | 'REQUEST_REASSESSMENT'
export interface LearningAgentDecision {
  action_type: LearningAgentActionType
  topic_id: string | null
  objective: string
  evidence: { kind: string; detail: string }[]
  decision_reason: string
  next_step: string
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

// ------------------------------------------------------------------ copilot onboarding & config

export type CopilotArchetypeKey = 'nova' | 'axel' | 'sage' | 'vex'
export type CopilotOnboardingState = 'not_started' | 'completed' | 'skipped'
export type CopilotOnboardingSource = 'quiz' | 'skip' | 'manual_change'

export interface CopilotOption {
  key: CopilotArchetypeKey
  name: string
  title: string
  voice_agent_id: string
  capabilities: Record<string, boolean>
}

export interface CopilotConfigRecord {
  choice: CopilotArchetypeKey
  voice_agent_id: string
  name: string
  title: string
  role: string
  specialty: string
  origin: string
  traits: string[]
  behavior: string
  style: string
  capabilities: Record<string, boolean>
  updated_at?: string
}

export interface CopilotOnboardingStateResponse {
  state: CopilotOnboardingState
  source: CopilotOnboardingSource
  answered_at: string | null
  configured: boolean
  copilot: CopilotConfigRecord | null
  options: CopilotOption[]
}

export interface CopilotOnboardingSubmit {
  answers?: string[]
  skipped?: boolean
  choice?: string
}

export interface CopilotOnboardingResponse {
  state: CopilotOnboardingState
  source: CopilotOnboardingSource
  assigned: string
  answered_at: string | null
  copilot: CopilotConfigRecord
  options: CopilotOption[]
}

export interface CopilotConfigResponse {
  configured: boolean
  copilot: CopilotConfigRecord | null
  options: CopilotOption[]
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
  family: string | null
  family_label: string | null
  family_icon: string | null
  version: number
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

export interface ScenarioHintPolicy {
  penalty: number
  cap: number
  used: number
  deduction: number
}

export interface ScenarioLastDecision {
  label: string
  icon: string | null
  verdict: 'good' | 'neutral' | 'bad'
  good: boolean
  points: number
  feedback: string
  consequence: string
  step_title: string
}

export interface ScenarioFollowUp {
  component_key: string | null
  component_label: string | null
  weakness_pct: number | null
  skill: string | null
  skill_id: number | null
  action: 'lesson' | 'practice' | 'review'
  message: string
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
  target_role: string | null
  role_title: string
  last_decision: ScenarioLastDecision | null
  hint_policy: ScenarioHintPolicy
  outcome: string | null
}

export interface ScenarioHint {
  hint: string
  explanation: string
  source: 'curated'
  hints_used: number
  hints_capped: boolean
  hint_policy: ScenarioHintPolicy
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
  hint_policy: ScenarioHintPolicy
  follow_up: ScenarioFollowUp
  evidence_inspected_pct: number | null
  target_role: string | null
  role_title: string
  certified: false
  note: string
}

export interface ScenarioHistoryEntry {
  attempt_id: number
  scenario_id: string
  title: string
  role_title: string
  family: string | null
  family_label: string | null
  family_icon: string | null
  difficulty_label: string
  difficulty_icon: string
  status: 'in_progress' | 'completed'
  score: number | null
  scenario_version: number
  hints_used: number
  started_at: string | null
  completed_at: string | null
  outcome_title: string | null
  outcome_tone: string | null
}

export interface ScenarioHistory {
  attempts: ScenarioHistoryEntry[]
}

export interface SavedRolesResponse {
  role_ids: number[]
}
