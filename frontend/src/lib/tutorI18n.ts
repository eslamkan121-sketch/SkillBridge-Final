// Tutor language support (Phase 5.5 Step 4).
//
// Centralized, small i18n for the Tutor/Copilot surface only — the rest of the
// SkillBridge app stays English. The backend owns the final language decision;
// this module only decides what the Copilot chrome, quick actions and browser
// speech should present for a given (validated) language.
import type { TutorLanguage, TutorMode } from './types'
import type { TutorId, TutorProfile } from './tutorProfiles'

export const TUTOR_LANGUAGES: TutorLanguage[] = ['auto', 'en', 'ar']

export function isTutorLanguage(value: string): value is TutorLanguage {
  return value === 'auto' || value === 'en' || value === 'ar'
}

/** Short option labels for the compact selector in the Copilot bar. */
export const LANGUAGE_SHORT: Record<TutorLanguage, string> = {
  auto: 'Auto',
  en: 'EN',
  ar: 'ع',
}

/** Full option labels (selector tooltips / accessibility). */
export const LANGUAGE_LABELS: Record<TutorLanguage, string> = {
  auto: 'Auto',
  en: 'English',
  ar: 'العربية',
}

/** Resolve 'auto' for display: follow the last resolved conversation language. */
export function effectiveLanguage(pref: TutorLanguage, lastReply: 'en' | 'ar' | null): 'en' | 'ar' {
  if (pref === 'ar') return 'ar'
  if (pref === 'en') return 'en'
  return lastReply === 'ar' ? 'ar' : 'en'
}

/** Browser speech-recognition language for a resolved tutor language. */
export function speechLanguageFor(lang: 'en' | 'ar'): string {
  return lang === 'ar' ? 'ar-EG' : 'en-US'
}

/** Short personality-appropriate voice preview per tutor (18). */
export function previewFor(tutor: TutorProfile, lang: 'en' | 'ar'): string {
  if (lang === 'ar') {
    const previews: Record<TutorId, string> = {
      nova: 'مرحباً، أنا نوفا. جاهز نبدأ؟',
      axel: 'أنا أكسل. خلّينا نشتغل دلوقتي!',
      sage: 'أنا سيج. كان عندك سؤال نناقشه؟',
      vex: 'أنا فكس. استعد للسؤال الجاي.',
    }
    return previews[tutor.id]
  }
  return `Hi, I'm ${tutor.name}. Ready to learn?`
}

export type LangStrings = ReturnType<typeof uiText>

function uiText(lang: 'en' | 'ar') {
  const ar = lang === 'ar'
  const s = (en: string, a: string) => (ar ? a : en)
  return {
    lang,
    profile: s('Profile', 'الملف الشخصي'),
    languages: s('Language', 'اللغة'),
    lockedTitle: s('Assessment in progress — tutor paused', 'في تقييم نهائي — المعلم متوقف مؤقتاً'),
    lockedBody: s(
      'Your Verified Final Assessment is active, so the tutor is paused to keep the test fair. Chat resumes the moment you submit.',
      'التقييم النهائي الموثّق شغّال دلوقتي، فالمعلم متوقف عشان الاختبار يفضل عادل. المحادثة هترجع أول ما تسلّم.',
    ),
    talkingAbout: s('Talking about', 'نتكلم عن'),
    mockInterviewTitle: s('Mock Interview', 'مقابلة تجريبية'),
    mockInterviewDesc: s('Simulate a real interview on', 'حاكي مقابلة حقيقية على'),
    forYourRole: s('for your target role. Questions adapt to your profile — your assessment data is never shared in the interview.', 'لوظيفتك المستهدفة. الأسئلة بتتكيف مع ملفّك — بيانات تقييمك متتشاركش في المقابلة أبداً.'),
    startMockInterview: s('Start Mock Interview', 'ابدأ مقابلة تجريبية'),
    useVex: s('Use Vex (recommended)', 'استخدم Vex (مُقترح)'),
    openInterviewRoom: s('Open interview room', 'افتح غرفة المقابلة'),
    startingInterview: s('Starting your interview…', 'بنبدأ المقابلة…'),
    questionTag: s('Interviewer · Question', 'المُحاور · سؤال'),
    youTag: s('You', 'إنت'),
    feedbackTag: s('Interviewer · Feedback', 'المُحاور · تعليق'),
    typeYourAnswer: s('Type your answer…', 'اكتب إجابتك…'),
    interviewerSpeaking: s('{name} is speaking...', '{name} بيتكلم...'),
    interviewerSpeakingBody: s('Listen first, then answer when the mic is ready.', 'اسمع الأول، وبعدها جاوب لما الميكروفون يبقى جاهز.'),
    yourTurn: s('Your turn', 'دورك'),
    studentReadyBody: s('Answer by voice when you are ready.', 'جاوب بصوتك لما تكون جاهز.'),
    startAnswer: s('Start Answer', 'ابدأ الإجابة'),
    tapToAnswer: s('Tap to Answer', 'اضغط للإجابة'),
    listening: s('Listening...', 'بنسمع...'),
    stopAnswer: s('Stop Answer', 'أوقف الإجابة'),
    thinking: s('Thinking...', 'بيفكر...'),
    processingAnswer: s('{name} is reviewing your answer.', '{name} بيراجع إجابتك.'),
    liveTranscript: s('Live transcript', 'النص المباشر'),
    typeAnswerInstead: s('Type answer instead', 'اكتب الإجابة بدل الصوت'),
    typedAnswerPlaceholder: s('Type your fallback answer...', 'اكتب إجابتك البديلة...'),
    submitTypedAnswer: s('Submit typed answer', 'إرسال الإجابة المكتوبة'),
    stopAudio: s('Stop audio', 'أوقف الصوت'),
    endInterview: s('End Interview', 'إنهاء المقابلة'),
    interviewComplete: s('Interview complete', 'المقابلة خلصت'),
    interviewCompleteBody: s('{name} stays selected — keep practising or return to normal chat.', '{name} لسه مختار — كمل تدريب أو ارجع للشات العادي.'),
    newInterview: s('New Interview', 'مقابلة جديدة'),
    returnToChat: s('Return to Chat', 'ارجع للمحادثة'),
    greeting: s('Hi, I\'m {name}. {purpose} I already know your profile, target role, and where you are right now — ask me anything.', 'أهلاً، أنا {name}. {purpose} أنا عارف بروفايلك ووظيفتك المستهدفة وواقف فين دلوقتي — اسألني أي حاجة.'),
    askPlaceholder: s('Ask {name} anything...', 'اسأل {name} أي حاجة...'),
    sendAria: s('Send', 'إرسال'),
    modeLabels: {
      chat: s('Chat', 'محادثة'),
      practice: s('Practice', 'تدريب'),
      discuss: s('Discuss', 'نقاش'),
      interview: s('Interview', 'مقابلة'),
    } as Record<TutorMode, string>,
    modeAria: s('Tutor working mode', 'وضع الشغل للمعلم'),
    profileToggle: (open: boolean, name: string) => s(
      `${open ? 'Hide' : 'Show'} ${name} profile`,
      `${open ? 'إخفاء' : 'إظهار'} ملف ${name}`,
    ),
    copilotBar: s('AI Career Copilot', 'المُعلّم الرقمي'),
    langAria: s('Tutor language', 'لغة المعلم'),
    newChat: s('+ New Chat', 'محادثة جديدة +'),
    newChatConfirm: s(
      'Start a new chat with {name}? Your current conversation stays in History.',
      'تبدأ محادثة جديدة مع {name}؟ المحادثة الحالية هتفضل في السجل.',
    ),
    history: s('History', 'السجل'),
    chatHistory: s('Conversation history', 'سجل المحادثات'),
    emptyHistory: s('No saved conversations yet', 'لسه مفيش محادثات محفوظة'),
    historyAria: s('Open conversation history', 'افتح سجل المحادثات'),
    changeMentor: s('Change Mentor', 'غيّر المُعلّم'),
    currentConversation: s('Current conversation', 'المحادثة الحالية'),
    clearChat: s('Clear Chat', 'امسح المحادثة'),
    clearChatTitle: s('Clear this chat?', 'تمسح المحادثة دي؟'),
    clearChatConfirm: s(
      'Clear this conversation with {name}? History from other chats stays saved.',
      'تمسح المحادثة دي مع {name}؟ باقي المحادثات هتفضل محفوظة.',
    ),
    cancel: s('Cancel', 'إلغاء'),
    clear: s('Clear', 'امسح'),
    expand: s('Expand chat', 'وسّع المحادثة'),
    collapse: s('Collapse chat', 'صغّر المحادثة'),
    backToChat: s('Back to Chat', 'ارجع للمحادثة'),
    speak: s('Speak', 'تشغيل'),
    stopSpeak: s('Stop', 'إيقاف'),
    voiceAria: s('Read this reply aloud', 'اقرأ الرد بصوت عالي'),
    voiceUnavailable: s('Voice unavailable', 'الصوت غير متاح'),
    micAria: s('Talk instead of typing', 'تكلّم بدل الكتابة'),
    micListeningAria: s('Stop voice input', 'أوقف الإدخال الصوتي'),
    liveAria: s('Open live voice chat with {name}', 'افتح محادثة صوتية مباشرة مع {name}'),
    interviewPinned: s(
      'The interview is running with {name}. Switch tutors after ending it.',
      'المقابلة شغّالة مع {name}. غيّر المُعلّم بعد إنهائها.',
    ),
    pinnedTitle: s('Switching tutors is paused during an active interview', 'تبديل المُعلّم متوقف أثناء مقابلة نشطة'),
    voiceModeTitle: s('Voice chat', 'شات صوتي'),
    voiceLiveTag: s('Live', 'مباشر'),
    voiceTypeInstead: s('Type instead', 'اكتب بدل الصوت'),
    tapTheMic: s('Tap the mic to talk', 'اضغط المايك لتتكلّم'),
    voiceClose: s('Close voice chat', 'أغلق الشات الصوتي'),
    voiceKeyboard: s('Go back to keyboard', 'ارجع للوحة المفاتيح'),
    voiceReady: s('Ready', 'جاهز'),
    voiceEnd: s('End', 'إنهاء'),
    voiceLanguage: s('Live speech language', 'لغة المحادثة الصوتية'),
    voiceSpeaking: s('{name} is speaking...', '{name} بيتكلم...'),
    voiceBargeIn: s('I heard you — let\'s talk.', 'سمعتك — نتكلم دلوقتي.'),
    voiceStop: s('Stop', 'إيقاف'),
    voiceTranscript: s('Transcript', 'النص'),
    copyAria: s('Copy this reply', 'انسخ الرد'),
    copied: s('Copied', 'تم النسخ'),
    voiceUnsupported: s('Voice input is not supported in this browser.', 'الإدخال الصوتي غير مدعوم في المتصفح ده.'),
    micDeclined: s('Microphone permission required', 'إذن المايكروفون مطلوب'),
    connectionLost: s('Connection lost — try again', 'فقدنا الاتصال — حاول تاني'),
    ready: s('Ready', 'جاهز'),
    copilotTagline: s('Your AI Learning & Career Copilot', 'المُعلّم الرقمي للتعلّم والوظائف'),
    chooseCopilot: s('Choose your AI Copilot', 'اختر المُعلّم الرقمي'),
    active: s('Active', 'نشط'),
    moreOptions: s('More options', 'خيارات إضافية'),
    newChatChip: s('New chat', 'محادثة جديدة'),
    clearChatChip: s('Clear chat', 'امسح المحادثة'),
    profileOf: s('{name} profile', 'ملف {name}'),
    startMockInterviewChip: s('Start mock interview', 'ابدأ مقابلة تجريبية'),
    toolsAria: s('Open chat tools', 'افتح أدوات المحادثة'),
    toolsMenu: s('Chat tools', 'أدوات المحادثة'),
    practiceAction: s('Practice', 'تدريب'),
    quizMeAction: s('Quiz me', 'اختبرني'),
    mockInterviewAction: s('Mock Interview', 'مقابلة تجريبية'),
    explainTopicAction: s('Explain topic', 'اشرح الموضوع'),
    welcomeTitle: s('What can I help you with?', 'أقدر أساعدك بإيه؟'),
    welcomeBody: s(
      'Explain concepts, practice skills, prepare for interviews, or plan your career.',
      'اشرح مفاهيم، تدرّب على مهارات، حضّر للمقابلات، أو خطط لمسارك المهني.',
    ),
    suggExplain: s('Explain a concept', 'اشرح مفهوم'),
    suggExplainSub: s('Break down difficult topics simply', 'بسّط المواضيع الصعبة'),
    suggPractice: s('Practice a skill', 'تدرّب على مهارة'),
    suggPracticeSub: s('Learn through examples and exercises', 'اتعلم بالأمثلة والتمارين'),
    suggInterview: s('Prepare for an interview', 'حضّر لمقابلة'),
    suggInterviewSub: s('Practice realistic questions', 'تدرّب على أسئلة واقعية'),
    suggCareer: s('Plan my career', 'خطط لمسيرتي'),
    suggCareerSub: s('Get guidance for your next step', 'خذ إرشاد لخطوتك الجاية'),
    copy: s('Copy', 'نسخ'),
    liveChip: s('Live', 'مباشر'),
    responseActions: s('Response actions', 'إجراءات الرد'),
    copyResponse: s('Copy response', 'انسخ الرد'),
    rateHelpful: s('Rate response as helpful', 'قيّم الرد كمفيد'),
    rateNotHelpful: s('Rate response as not helpful', 'قيّم الرد كغير مفيد'),
    shareResponse: s('Share response', 'شارك الرد'),
    tryAgain: s('Try again', 'إعادة المحاولة'),
    retrying: s('Retrying…', 'بنعيد المحاولة…'),
    tipHelpful: s('Helpful', 'مفيد'),
    tipNotHelpful: s('Not helpful', 'غير مفيد'),
    tipShare: s('Share', 'مشاركة'),
    tipRetry: s('Try again', 'إعادة المحاولة'),
    readAloud: s('Read response aloud', 'قراءة الرد بصوت عالٍ'),
    stopPlayback: s('Stop playback', 'إيقاف التشغيل'),
    tipReadAloud: s('Read aloud', 'استماع'),
    tipStopAudio: s('Stop', 'إيقاف'),
    learningContextActive: s('Learning context active', 'سياق التعلّم نشط'),
    composerFooter1: s('{name} uses your SkillBridge learning context', '{name} بيستخدم سياق تعلّمك في SkillBridge'),
    composerFooter2: s('AI can make mistakes', 'الذكاء الاصطناعي ممكن يغلط'),
    attachAria: s('Attach a file', 'ارفع ملف'),
    attachmentsUnavailable: s(
      'Attachments are not available yet — the tutor answers by text and voice.',
      'المرفقات لسه مش متاحة — المُعلّم بيرد بالنص والصوت.',
    ),
    tutorRole: {
      nova: s('Adaptive mentor', 'معلّم تكيفي'),
      axel: s('Technical coach', 'مدرب تقني'),
      sage: s('Strategy mentor', 'معلّم استراتيجي'),
      vex: s('Interview challenger', 'منافس مقابلات'),
    } as Record<TutorId, string>,
  }
}

/** Localized quick-action prompts (22). */
export function quickActionsFor(
  lang: 'en' | 'ar',
  tutorId: TutorId,
  mode: TutorMode,
  topicName: string,
): { label: string; prompt: string }[] {
  const ar = lang === 'ar'
  const t = (enLabel: string, arLabel: string) => ({ label: ar ? arLabel : enLabel })
  const prompts = (en: string, arPrompt: string) => ({ prompt: ar ? arPrompt : en })
  const topic = topicName
  const list: { label: string; prompt: string }[] = []
  if (mode === 'chat') {
    list.push(
      { ...t('Explain this topic', 'اشرحلي ده'), ...prompts(`Explain ${topic} simply and step by step for my target role.`, `اشرح ${topic} ببساطة وعلى مراحل لهدفي المهني.`) },
      { ...t('Give me an example', 'اديني مثال'), ...prompts(`Give me a clear example of ${topic} in my target role.`, `اديني مثال واضح لـ ${topic} في وظيفتي المستهدفة.`) },
    )
    const extra: Record<TutorId, { label: string; prompt: string }[]> = {
      nova: [
        { ...t('Explain it differently', 'اشرحه بطريقة تانية'), ...prompts(`Explain ${topic} in a different way with a simple analogy.`, `اشرح ${topic} بطريقة تانية وتشبيه بسيط.`) },
      ],
      axel: [
        { ...t('Practice this', 'درّبني على ده'), ...prompts(`Give me a practical exercise for ${topic}.`, `اديني تمرين عملي على ${topic}.`) },
        { ...t('Give me a challenge', 'اديني تحدي'), ...prompts(`Give me a hands-on challenge for ${topic}.`, `اديني تحدي عملي على ${topic}.`) },
      ],
      sage: [
        { ...t("Let's discuss this", 'نناقش ده'), ...prompts(`Discuss ${topic} with me and guide me with questions.`, `ناقشني في ${topic} ووجّهني بأسئلة.`) },
        { ...t('Ask me why', 'سألني ليه'), ...prompts(`Ask me why ${topic} matters and help me reason through it.`, `اسألني ليه ${topic} مهم وساعدني أفكر فيه.`) },
      ],
      vex: [
        { ...t('Quiz me', 'اختبرني'), ...prompts(`Quiz me on ${topic}.`, `اختبرني في ${topic}.`) },
        { ...t('Prepare me', 'جهّزني'), ...prompts(`Help me prepare to start an assessment for ${topic}.`, `ساعدني أجهّز نفسي لتقييم على ${topic}.`) },
      ],
    }
    list.push(...(extra[tutorId] || []))
    return list
  }
  const modeActions: Record<Exclude<TutorMode, 'chat'>, { label: string; prompt: string }[]> = {
    practice: [
      { ...t('Exercise', 'تمرين'), ...prompts(`Give me a hands-on exercise for ${topic} right now.`, `اديني تمرين عملي على ${topic} دلوقتي.`) },
      { ...t('20-min drill', 'تدريب 20 دقيقة'), ...prompts(`Give me a 20-minute focused drill on ${topic}.`, `اديني تدريب مركّز 20 دقيقة على ${topic}.`) },
      { ...t('Mini-project', 'مشروع صغير'), ...prompts(`Suggest a small project I can build to practice ${topic}.`, `اقترح مشروع صغير أبنيه أتدرب فيه على ${topic}.`) },
    ],
    discuss: [
      { ...t('Guide me', 'وجّهني'), ...prompts(`Guide my thinking on ${topic} with reflective questions.`, `وجّه تفكيري في ${topic} بأسئلة تأملية.`) },
      { ...t('Compare', 'قارن'), ...prompts(`Compare two common approaches to ${topic}; which fits my goal and why?`, `قارن بين طريقتين شائعتين لـ ${topic}؛ إيه الأنسب لهدفي وليه؟`) },
      { ...t('Test my reasoning', 'اختبر تفكيري'), ...prompts(`Ask me why ${topic} matters in my target role and test my reasoning.`, `اسألني ليه ${topic} مهم في وظيفتي المستهدفة واختبر تفكيري.`) },
    ],
    interview: [
      { ...t('Interview me', 'قابلني'), ...prompts(`Interview me on ${topic} like a hiring manager for my target role.`, `قابلني على ${topic} زي مدير توظيف لوظيفتي المستهدفة.`) },
      { ...t('Hard question', 'سؤال صعب'), ...prompts(`Ask me the hardest ${topic} interview question for my target role.`, `اسألني أصعب سؤال مقابلة في ${topic} لوظيفتي المستهدفة.`) },
      { ...t('Judge strictly', 'احكم بدقة'), ...prompts(`Interview me on ${topic} and judge my answers strictly.`, `قابلني على ${topic} واحكم على إجاباتي بدقة.`) },
    ],
  }
  list.push(...modeActions[mode])
  return list
}

/** Resolved-label object exposing the strings for a given language. */
export function tutorUi(lang: 'en' | 'ar'): LangStrings {
  return uiText(lang)
}
