import type {
  ActivitySummary, Analysis, AssessmentAttempt, Candidate, CareerRoadmap, CohortResponse, Company, GeneratedAssessment,
  DiagnosticResult, GeneratedDiagnostic, GoogleConfig, LearningItem, Lesson, QuizQuestion, PublicProfile, RoleRecord, RolesResponse, RoleSkillCoverage, Skill, Student,
  Session, TutorMessage, InterviewReply, UniversityStatsResponse, UniversityOption, RecentJob, RecentJobsResponse, LocationOption,
  PersonalizedPath, PersonalizedPathItem, PersonalizedStage, PersonalizedPathResponse, FinalAssessmentStatus, PracticeAttempt, PracticeAttemptsResponse,
  EscoMarketResponse, RoleRecommendationsResponse,
  ScenarioLibrary, ScenarioPlayer, ScenarioResult, ScenarioHint, ScenarioHistory, SavedRolesResponse,
  RoleMappingSuggestion, RoleMappingEvent,
  TargetRoleMatchBreakdown, RoleMatchBreakdown, JobMatchBreakdown,
  SaveJobRequest, TrackedJob, TrackerResponse,
  RecentRole, RecentRolesResponse,
  RoleProvenance, JobsHealthPayload, JobLinkReport,
  CopilotConfigResponse, CopilotOnboardingStateResponse, CopilotOnboardingSubmit, CopilotOnboardingResponse,
} from './types'
import type { AssessmentIntegrityEvent } from './webcamIntegrity'

const BASE = ''
const TOKEN_KEY = 'skillbridge_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, { ...options, headers })
  if (!res.ok) {
    let detail = `Request failed: ${res.status}`
    try {
      const data = await res.json()
      if (data && data.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* non-JSON error body */ }
    if (res.status === 401) setToken(null)
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

async function reqBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, { ...options, headers })
  if (!res.ok) {
    let detail = `Request failed: ${res.status}`
    try {
      const data = await res.json()
      if (data && data.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* non-JSON error body */ }
    if (res.status === 401) setToken(null)
    throw new Error(detail)
  }
  return res.blob()
}

export const api = {
  // ---- auth
  login: (email: string, password: string) => {
    const p = req<Session & { entity_type: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
    return p.then((s) => { setToken(s.token); return s })
  },
  signup: (email: string, password: string, display_name: string, role: string, university?: string, country?: string, industry?: string, location?: string, education_level?: string) => {
    const p = req<any>('/api/auth/signup', { method: 'POST', body: JSON.stringify({ email, password, display_name, role, university, country, industry, location, education_level }) })
    return p.then((s) => { setToken(s.token); return s })
  },
  logout: () => {
    try { return req<any>('/api/auth/logout', { method: 'POST' }).finally(() => setToken(null)) }
    catch { setToken(null); return Promise.resolve({ ok: true }) }
  },
  me: () => req<Session>('/api/auth/me'),
  googleConfig: () => req<GoogleConfig>('/api/auth/google/config'),
  googleDemo: (email: string, display_name: string) =>
    req<any>('/api/auth/google/demo', { method: 'POST', body: JSON.stringify({ email, display_name }) }),
  googleComplete: (google_sub: string, role: string, opts?: { university?: string; country?: string; industry?: string; location?: string; education_level?: string }) => {
    const p = req<any>('/api/auth/google/complete', { method: 'POST', body: JSON.stringify({ google_sub, role, university: opts?.university, country: opts?.country, industry: opts?.industry, location: opts?.location, education_level: opts?.education_level }) })
    return p.then((s) => { setToken(s.token); return s })
  },
  resetRequest: (email: string) =>
    req<{ ok: boolean; reset_token?: string; message?: string }>('/api/auth/reset/request', { method: 'POST', body: JSON.stringify({ email }) }),
  resetConfirm: (token: string, new_password: string) =>
    req<{ ok: boolean }>('/api/auth/reset/confirm', { method: 'POST', body: JSON.stringify({ token, new_password }) }),
  verifyEmail: (token: string) =>
    req<{ ok: boolean }>('/api/auth/verify', { method: 'POST', body: JSON.stringify({ token }) }),
  universities: () => req<UniversityOption[]>('/api/universities'),
  locations: () => req<LocationOption[]>('/api/locations'),
  demoMode: () => req<{ genai_enabled: boolean; email_configured: boolean }>('/api/config/demo-mode'),

  // ---- catalog
  skills: () => req<Skill[]>('/api/skills'),
  roles: () => req<RolesResponse>('/api/roles'),
  catalogRoles: () => req<RoleRecord[]>('/api/roles/catalog'),
  escoMarket: (q: string, limit = 8, targetRole?: string) => req<EscoMarketResponse>(
    `/api/roles/esco-market?q=${encodeURIComponent(q)}&limit=${limit}${targetRole ? `&target_role=${encodeURIComponent(targetRole)}` : ''}`
  ),
  createRole: (body: any) => req<RoleRecord>('/api/roles', { method: 'POST', body: JSON.stringify(body) }),
  updateRole: (id: number, body: any) => req<RoleRecord>(`/api/roles/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteRole: (id: number) => req<{ deleted: boolean }>(`/api/roles/${id}`, { method: 'DELETE' }),
  companies: () => req<Company[]>('/api/companies'),
  candidates: (roleId: number) => req<Candidate[]>(`/api/company/roles/${roleId}/candidates`),
  roleSkillCoverage: (roleId: number) => req<RoleSkillCoverage>(`/api/company/roles/${roleId}/skills`),
  canonicalMatches: (roleId: number) =>
    req<RoleMappingSuggestion>(`/api/company/roles/${roleId}/canonical-matches`),
  setCanonicalMapping: (roleId: number, canonicalRoleId: number | null) =>
    req<{ role_id: number; canonical_role_id: number | null; mapping_updated_at?: string | null }>(
      `/api/company/roles/${roleId}/canonical-mapping`,
      { method: 'POST', body: JSON.stringify({ canonical_role_id: canonicalRoleId }) },
    ),
  mappingHistory: (roleId: number) =>
    req<RoleMappingEvent[]>(`/api/company/roles/${roleId}/mapping-history`),

  // ---- students
  student: (id: number) => req<Student>(`/api/students/${id}`),
  updateStudent: (id: number, body: any) => req<Student>(`/api/students/${id}`, { method: 'PUT', body: JSON.stringify(body) }),

  roleRecommendations: (studentId: number) =>
    req<RoleRecommendationsResponse>(`/api/students/${studentId}/role-recommendations`),
  selectEscoTarget: (studentId: number, uri: string, title: string, skills?: string[]) =>
    req<Student>(`/api/students/${studentId}/target-role/esco`, {
      method: 'POST',
      body: JSON.stringify({ uri, title, skills: skills || [] }),
    }),

  uploadCv: async (studentId: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const headers: Record<string, string> = {}
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${BASE}/api/students/${studentId}/cv`, { method: 'POST', body: fd, headers })
    if (!res.ok) {
      let detail = 'CV upload failed'
      try { const d = await res.json(); detail = d.detail || detail } catch { /* ignore */ }
      if (res.status === 401) setToken(null)
      throw new Error(detail)
    }
    return res.json()
  },

  analysis: (studentId: number) => req<Analysis>(`/api/students/${studentId}/analysis`),

  // ---- Phase J: explainable match breakdowns (read-only)
  targetRoleMatchBreakdown: (studentId: number) =>
    req<TargetRoleMatchBreakdown>(`/api/students/${studentId}/target-role-match/breakdown`),
  roleMatchBreakdown: (studentId: number, roleId?: number | null, externalId?: string | null) => {
    const qs = new URLSearchParams()
    if (roleId != null) qs.set('role_id', String(roleId))
    else if (externalId) qs.set('external_id', externalId)
    return req<RoleMatchBreakdown>(`/api/students/${studentId}/role-match/breakdown?${qs.toString()}`)
  },
  jobMatchBreakdown: (studentId: number, fingerprint: string, opts?: { location?: string; country?: string; market?: string }) => {
    const qs = new URLSearchParams()
    if (opts?.location) qs.set('location', opts.location)
    if (opts?.country) qs.set('country', opts.country)
    if (opts?.market) qs.set('market', opts.market)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return req<JobMatchBreakdown>(
      `/api/students/${studentId}/jobs/recent/${encodeURIComponent(fingerprint)}/breakdown${suffix}`)
  },

  learning: (studentId: number) => req<LearningItem[]>(`/api/students/${studentId}/learning`),
  generateLearning: (studentId: number, skillId: number) =>
    req<LearningItem>(`/api/students/${studentId}/learning/generate`, { method: 'POST', body: JSON.stringify({ skill_id: skillId }) }),
  learningProgress: (studentId: number, skillId: number, steps: number[]) =>
    req<LearningItem>(`/api/students/${studentId}/learning/${skillId}/progress`, { method: 'POST', body: JSON.stringify({ steps }) }),

  generateDiagnostic: (studentId: number, skillId: number) =>
    req<GeneratedDiagnostic>(`/api/students/${studentId}/learning/${skillId}/diagnostic/generate`, { method: 'POST', body: JSON.stringify({}) }),
  submitDiagnostic: (studentId: number, skillId: number, body: { diagnostic_id: number; answers: string[] }) =>
    req<DiagnosticResult>(`/api/students/${studentId}/learning/${skillId}/diagnostic/submit`, { method: 'POST', body: JSON.stringify(body) }),
  latestDiagnostic: (studentId: number, skillId: number) =>
    req<DiagnosticResult>(`/api/students/${studentId}/learning/${skillId}/diagnostic/latest`),

  personalizedPath: (studentId: number, skillId: number) =>
    req<PersonalizedPathResponse>(`/api/students/${studentId}/learning/${skillId}/personalized-path`),
  generatePersonalizedPath: (studentId: number, skillId: number) =>
    req<PersonalizedPathResponse>(`/api/students/${studentId}/learning/${skillId}/personalized-path/generate`, { method: 'POST', body: JSON.stringify({}) }),
  personalizedPathProgress: (studentId: number, skillId: number, progress: string[]) =>
    req<{ progress: string[] }>(`/api/students/${studentId}/learning/${skillId}/personalized-path/progress`, { method: 'POST', body: JSON.stringify({ progress }) }),

  finalAssessmentStatus: (studentId: number, skillId: number) =>
    req<FinalAssessmentStatus>(`/api/students/${studentId}/learning/${skillId}/final-assessment/status`),

  lessonGenerate: (studentId: number, skillId: number, competency: string, action?: string) =>
    req<Lesson>(`/api/students/${studentId}/learning/${skillId}/lessons/${encodeURIComponent(competency)}/generate`, { method: 'POST', body: JSON.stringify(action ? { action } : {}) }),
  lessonGet: (studentId: number, skillId: number, competency: string) =>
    req<Lesson>(`/api/students/${studentId}/learning/${skillId}/lessons/${encodeURIComponent(competency)}`),
  lessonStart: (studentId: number, skillId: number, competency: string) =>
    req<Lesson>(`/api/students/${studentId}/learning/${skillId}/lessons/${encodeURIComponent(competency)}/start`, { method: 'POST', body: JSON.stringify({}) }),
  lessonPracticeAttempts: (studentId: number, skillId: number, competency: string) =>
    req<PracticeAttemptsResponse>(`/api/students/${studentId}/learning/${skillId}/lessons/${encodeURIComponent(competency)}/practice`),
  lessonSubmitPractice: (studentId: number, skillId: number, competency: string, answer: string, sourceAttemptId?: number | null) =>
    req<{ attempt: PracticeAttempt; attempts_count: number }>(`/api/students/${studentId}/learning/${skillId}/lessons/${encodeURIComponent(competency)}/practice`, { method: 'POST', body: JSON.stringify(sourceAttemptId ? { answer, practice_task_source_attempt_id: sourceAttemptId } : { answer }) }),
  lessonMiniCheck: (studentId: number, skillId: number, competency: string, answers: string[]) =>
    req<{ lesson: Lesson; path_progress: string[] }>(`/api/students/${studentId}/learning/${skillId}/lessons/${encodeURIComponent(competency)}/mini-check`, { method: 'POST', body: JSON.stringify({ answers }) }),

  publicProfile: (studentId: number) => req<PublicProfile>(`/api/public/verified/${studentId}`),

  tutorHistory: (studentId: number, tutorId?: string) =>
    req<TutorMessage[]>(`/api/students/${studentId}/tutor${tutorId ? `?tutor_id=${encodeURIComponent(tutorId)}` : ''}`),
  clearTutorChat: (studentId: number, tutorId: string) =>
    req<{ cleared: boolean; tutor_id: string }>(`/api/students/${studentId}/tutor`, { method: 'DELETE', body: JSON.stringify({ tutor_id: tutorId }) }),
  tutorTts: (studentId: number, tutor: string, text: string) =>
    reqBlob(`/api/students/${studentId}/tutor/tts`, { method: 'POST', body: JSON.stringify({ tutor, text }) }),
  tutorSend: (studentId: number, message: string, opts: { skillId?: number | null; page?: string; competency?: string | null; jobTitle?: string | null; jobUrl?: string | null; tutorId?: string | null; mode?: string | null; language?: string | null } = {}) =>
    req<TutorMessage & { reply?: string; tutor_id?: string; mode?: string; language?: string }>(`/api/students/${studentId}/tutor`, { method: 'POST', body: JSON.stringify({ message, skill_id: opts.skillId ?? null, page: opts.page ?? 'dashboard', competency: opts.competency ?? null, job_title: opts.jobTitle ?? null, job_url: opts.jobUrl ?? null, tutor_id: opts.tutorId ?? null, mode: opts.mode ?? null, language: opts.language ?? null }) }),
  tutorPreference: (studentId: number) => req<{ tutor_id: string; mode?: string; language?: string }>(`/api/students/${studentId}/tutor/preference`),
  setTutorPreference: (studentId: number, patch: { tutor_id?: string; mode?: string; language?: string } = {}) =>
    req<{ tutor_id: string; mode: string; language: string }>(`/api/students/${studentId}/tutor/preference`, { method: 'PUT', body: JSON.stringify(patch) }),
  copilotConfig: (studentId: number) =>
    req<CopilotConfigResponse>(`/api/students/${studentId}/copilot`),
  setCopilot: (studentId: number, choice: string) =>
    req<CopilotConfigResponse>(`/api/students/${studentId}/copilot`, { method: 'PUT', body: JSON.stringify({ choice }) }),
  copilotOnboardingState: (studentId: number) =>
    req<CopilotOnboardingStateResponse>(`/api/students/${studentId}/copilot/onboarding-state`),
  submitCopilotOnboarding: (studentId: number, body: CopilotOnboardingSubmit) =>
    req<CopilotOnboardingResponse>(`/api/students/${studentId}/copilot/onboarding`, { method: 'POST', body: JSON.stringify(body) }),
  startAssessmentSession: (studentId: number, skillId: number, externalToken?: string | null, webcamGate?: { passed: boolean; checked_at: string; meta?: Record<string, string | number | boolean> }) =>
    req<{ active: boolean; skill_id: number; webcam_gate?: { required: boolean; passed: boolean } }>(`/api/students/${studentId}/assessments/session`, { method: 'POST', body: JSON.stringify({ skill_id: skillId, external_token: externalToken || undefined, webcam_gate: webcamGate }) }),
  endAssessmentSession: (studentId: number) =>
    req<{ active: boolean }>(`/api/students/${studentId}/assessments/session`, { method: 'DELETE' }),
  assessmentIntegrityEvent: (studentId: number, body: AssessmentIntegrityEvent & { skill_id: number; external_token: string }) =>
    req<{ accepted: boolean; event: AssessmentIntegrityEvent; events_count: number }>(`/api/students/${studentId}/assessments/integrity-events`, { method: 'POST', body: JSON.stringify(body) }),
  interviewSend: (studentId: number, message: string, turn: number, skillId?: number | null, tutor?: string, language?: string) =>
    req<InterviewReply>(`/api/students/${studentId}/interview`, { method: 'POST', body: JSON.stringify({ message, turn, skill_id: skillId, tutor, language }) }),
  interviewVoice: (studentId: number) =>
    req<{ available: boolean; api_key_loaded: boolean; tutor_voices_loaded: Record<string, boolean> }>(`/api/students/${studentId}/interview/voice`),
  interviewTts: (studentId: number, tutor: string, text: string) =>
    reqBlob(`/api/students/${studentId}/interview/tts`, { method: 'POST', body: JSON.stringify({ tutor, text }) }),

  generateAssessment: (studentId: number, skillId: number, opts: { practice?: boolean; num_questions?: number } = {}) =>
    req<GeneratedAssessment>(`/api/students/${studentId}/assessments/generate`, { method: 'POST', body: JSON.stringify({ skill_id: skillId, practice: !!opts.practice, num_questions: opts.num_questions || 10 }) }),
  submitAssessment: (studentId: number, body: any) =>
    req<any>(`/api/students/${studentId}/assessments`, { method: 'POST', body: JSON.stringify(body) }),
  finalizeAssessment: (studentId: number, body: any) =>
    req<any>(`/api/students/${studentId}/assessments/finalize`, { method: 'POST', body: JSON.stringify(body) }),
  studentAssessments: (studentId: number) => req<AssessmentAttempt[]>(`/api/students/${studentId}/assessments`),
  studentActivity: (studentId: number) => req<ActivitySummary>(`/api/students/${studentId}/activity`),

  // ---- university
  universityStats: () => req<UniversityStatsResponse>('/api/university/stats'),
  universityCohort: () => req<CohortResponse>('/api/university/cohort'),
  universityConfirm: () => req<CohortResponse>('/api/university/cohort/confirm', { method: 'POST', body: JSON.stringify({ confirm: true }) }),

  // ---- recent jobs
  recentJobs: (opts?: { location?: string; country?: string; market?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (opts?.location) qs.set('location', opts.location)
    if (opts?.country) qs.set('country', opts.country)
    if (opts?.market) qs.set('market', opts.market)
    if (opts?.limit) qs.set('limit', String(opts.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return req<RecentJobsResponse>(`/api/jobs/recent${suffix}`)
  },
  jobsHealth: () => req<JobsHealthPayload>('/api/config/demo-mode'),
  jobLinkReports: (studentId: number) => req<{ reports: JobLinkReport[] }>(`/api/students/${studentId}/jobs/link-reports`),
  reportDeadJobLink: (studentId: number, fingerprint: string, payload: { location?: string; country?: string; market?: string } = {}) =>
    req<{ report_id: number; created: boolean; fingerprint: string }>(
      `/api/students/${studentId}/jobs/recent/${encodeURIComponent(fingerprint)}/report-dead-link`,
      { method: 'POST', body: JSON.stringify(payload) }),

  // ---- full career roadmap
  careerRoadmap: (studentId: number) => req<CareerRoadmap>(`/api/students/${studentId}/career-roadmap`),

  // ---- practice scenarios
  scenarios: (studentId: number) => req<ScenarioLibrary>(`/api/students/${studentId}/scenarios`),
  startScenario: (studentId: number, scenarioId: string) =>
    req<ScenarioPlayer>(`/api/students/${studentId}/scenarios/${scenarioId}/start`, { method: 'POST', body: JSON.stringify({}) }),
  scenarioAttempt: (studentId: number, attemptId: number) =>
    req<ScenarioPlayer | ScenarioResult>(`/api/students/${studentId}/scenarios/attempts/${attemptId}`),
  decideScenario: (studentId: number, attemptId: number, payload: { decision_id?: string; option_ids?: string[]; evidence_viewed?: string[] }) =>
    req<ScenarioPlayer | ScenarioResult>(`/api/students/${studentId}/scenarios/attempts/${attemptId}/decide`, { method: 'POST', body: JSON.stringify(payload) }),
  scenarioHint: (studentId: number, attemptId: number, question?: string) =>
    req<ScenarioHint>(`/api/students/${studentId}/scenarios/attempts/${attemptId}/hint`, { method: 'POST', body: JSON.stringify(question ? { question } : {}) }),
  scenarioHistory: (studentId: number) => req<ScenarioHistory>(`/api/students/${studentId}/scenarios/history`),

  // ---- saved roles
  savedRoles: (studentId: number) => req<SavedRolesResponse>(`/api/students/${studentId}/saved-roles`),
  saveRole: (studentId: number, roleId: number) =>
    req<SavedRolesResponse>(`/api/students/${studentId}/saved-roles/${roleId}`, { method: 'POST', body: JSON.stringify({}) }),
  unsaveRole: (studentId: number, roleId: number) =>
    req<SavedRolesResponse>(`/api/students/${studentId}/saved-roles/${roleId}`, { method: 'DELETE' }),

  // ---- recently-viewed roles (Phase L role explorer)
  recentRoles: (studentId: number) => req<RecentRolesResponse>(`/api/students/${studentId}/recent-roles`),
  recordRoleView: (studentId: number, roleId: number) =>
    req<{ viewed_at: string }>(`/api/students/${studentId}/recent-roles`, { method: 'POST', body: JSON.stringify({ role_id: roleId }) }),

  // ---- role provenance + related-role graph (Phase M)
  roleProvenance: (roleId: number) => req<RoleProvenance>(`/api/roles/${roleId}/provenance`),

  // ---- saved jobs + application tracker (Phase K)
  saveTrackedJob: (studentId: number, payload: SaveJobRequest) =>
    req<{ tracker_id: number; created: boolean; item: TrackedJob }>(`/api/students/${studentId}/jobs/saved`, { method: 'POST', body: JSON.stringify(payload) }),
  jobTracker: (studentId: number) => req<TrackerResponse>(`/api/students/${studentId}/jobs/tracker`),
  trackerItem: (studentId: number, trackerId: number) =>
    req<TrackedJob>(`/api/students/${studentId}/jobs/tracker/${trackerId}`),
  updateTrackerItem: (studentId: number, trackerId: number, patch: Partial<Pick<TrackedJob, 'stage' | 'note' | 'interview_date' | 'application_deadline'>>) =>
    req<TrackedJob>(`/api/students/${studentId}/jobs/tracker/${trackerId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteTrackerItem: (studentId: number, trackerId: number) =>
    req<{ deleted: boolean }>(`/api/students/${studentId}/jobs/tracker/${trackerId}`, { method: 'DELETE' }),
}
