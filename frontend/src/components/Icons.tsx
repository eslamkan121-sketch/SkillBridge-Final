import React from 'react'

interface IconProps {
  size?: number
  className?: string
  style?: React.CSSProperties
}

const base = (size = 18, className = '', style?: React.CSSProperties) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  className,
  style,
  'aria-hidden': true,
})

export const IconDashboard = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" />
  </svg>
)
export const IconRoles = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M8 8h11" /><path d="M8 12h11" /><path d="M8 16h11" />
    <circle cx="4.5" cy="8" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="4.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="4.5" cy="16" r="1.2" fill="currentColor" stroke="none" />
  </svg>
)
export const IconLearning = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 3l8 4-8 4-8-4 8-4z" /><path d="M4 11v5c0 1.5 3.6 3 8 3s8-1.5 8-3v-5" /><path d="M20 11v5" />
  </svg>
)
export const IconAssessment = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M9 3h6a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
    <path d="M12 7v4" /><circle cx="12" cy="15" r=".6" fill="currentColor" />
  </svg>
)
export const IconUniversity = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M3 9l9-5 9 5-9 5-9-5z" /><path d="M6 11v5c0 1 2.7 2 6 2 3.3 0 6-1 6-2v-5" />
    <path d="M21 9v6" />
  </svg>
)
export const IconCheck = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M20 6L9 17l-5-5" />
  </svg>
)
export const IconVerified = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 2l2.1 1.6 2.6-.3 1 2.4 2.4 1-.3 2.6L21.4 12l-1.6 2.1.3 2.6-2.4 1-1 2.4-2.6-.3L12 22l-2.1-1.6-2.6.3-1-2.4-2.4-1 .3-2.6L2.6 12 4.2 9.9l-.3-2.6 2.4-1 1-2.4 2.6.3L12 2z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
)
export const IconPlus = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}><path d="M12 5v14M5 12h14" /></svg>
)
export const IconEdit = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
  </svg>
)
export const IconTrash = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M3 6h18" /><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
  </svg>
)
export const IconUpload = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <path d="M17 8l-5-5-5 5" /><path d="M12 3v12" />
  </svg>
)
export const IconSend = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" />
  </svg>
)
export const IconMic = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" />
    <path d="M12 18v3" />
  </svg>
)
export const IconStop = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none" />
  </svg>
)
export const IconVolume = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M11 5L6 9H3v6h3l5 4V5z" /><path d="M16 9l4 4M20 9l-4 4" />
  </svg>
)
export const IconVolumeOff = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M11 5L6 9H3v6h3l5 4V5z" />
    <path d="M15.5 9l4.5 4.5M20 9l-4.5 4.5" />
  </svg>
)
export const IconFlag = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M4 22V4" /><path d="M4 4c5-3 6 3 10 0 5-3 6 3 6 3v9c-3 2-6-2-10 0-3 1.5-6 0-6 0z" />
  </svg>
)
export const IconAlert = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 3L2 21h20L12 3z" /><path d="M12 10v4M12 17.5v.01" />
  </svg>
)
export const IconLogout = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <path d="M16 17l5-5-5-5M21 12H9" />
  </svg>
)
export const IconCompany = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M3 21h18" /><path d="M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16" />
    <path d="M19 21V9a1 1 0 0 0-1-1h-3" /><path d="M9 7h2M9 11h2M9 15h2" />
  </svg>
)
export const IconUser = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
  </svg>
)
export const IconChat = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5z" />
  </svg>
)
export const IconArrowRight = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}><path d="M5 12h14M13 6l6 6-6 6" /></svg>
)
export const IconFilter = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}><path d="M4 6h16M7 12h10M10 18h4" /></svg>
)
export const IconMinus = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}><path d="M5 12h14" /></svg>
)
export const IconChevron = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}><path d="M6 9l6 6 6-6" /></svg>
)
export const IconSearch = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" />
  </svg>
)
export const IconGoogle = (p: IconProps) => (
  <svg width={p.size || 18} height={p.size || 18} viewBox="0 0 24 24" fill="none" className={p.className} style={p.style} aria-hidden>
    <path d="M21.35 12.2c0-.7-.06-1.4-.18-2H12v3.8h5.3c-.2 1.2-.9 2.3-1.9 3v2.5h3c1.8-1.7 2.95-4.2 2.95-7.3z" fill="#4285F4" />
    <path d="M12 22c2.55 0 4.7-.85 6.3-2.3l-3-2.5c-.85.55-1.9.9-3.3.9-2.5 0-4.65-1.7-5.4-4H3.56v2.55C5.15 20.2 8.35 22 12 22z" fill="#34A853" />
    <path d="M6.6 14.1c-.2-.55-.3-1.15-.3-1.75s.1-1.2.3-1.75V8.05H3.56C3.2 8.7 3 9.55 3 10.35s.2 1.65.56 2.3L6.6 14.1z" fill="#FBBC05" />
    <path d="M12 5.9c1.4 0 2.65.48 3.65 1.4l2.7-2.7C16.75 3.05 14.6 2 12 2 8.35 2 5.15 3.8 3.56 8.05l3.04 2.3c.75-2.3 2.9-4.45 5.4-4.45z" fill="#EA4335" />
  </svg>
)
export const IconShield = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 2l8 3v6c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V5l8-3z" />
    <path d="M8.5 12l2.5 2.5L15.5 9.5" />
  </svg>
)
export const IconExternal = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M14 4h6v6" /><path d="M20 4l-9 9" /><path d="M19 13v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h6" />
  </svg>
)
export const IconRoadmap = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <circle cx="5" cy="6" r="2" /><circle cx="5" cy="18" r="2" />
    <path d="M7 6h14M7 18h10" /><circle cx="19" cy="6" r="1.4" fill="currentColor" stroke="none" />
  </svg>
)
export const IconTrophy = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M8 4h8v4a4 4 0 0 1-8 0V4z" /><path d="M8 5H4v1a3 3 0 0 0 3 3" /><path d="M16 5h4v1a3 3 0 0 1-3 3" />
    <path d="M8 7h8" /><path d="M12 12v3" /><path d="M9 20h6M10 17h4l.5 3h-5l.5-3z" />
  </svg>
)
export const IconFlame = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 21c4.5 0 7-2.6 7-6.2 0-2.7-1.6-4.6-3.1-6.3C17.4 10.5 15.5 12 14.5 12 14.9 9.5 13.4 6 10.5 4c.4 2-.4 3.4-1.6 5C7.7 10.6 6 12.1 6 14.9 6 18.3 8.5 21 12 21z" />
    <path d="M12 21c-1.4 0-2.4-1-2.4-2.5 0-1.4.9-2.3 2.4-3.5 1.5 1.2 2.4 2.1 2.4 3.5 0 1.5-1 2.5-2.4 2.5z" />
  </svg>
)
export const IconBolt = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" />
  </svg>
)
export const IconLeaderboard = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="4" y="13" width="4" height="7" rx="1" /><rect x="10" y="7" width="4" height="13" rx="1" />
    <rect x="16" y="10" width="4" height="10" rx="1" /><path d="M6 13V8h2v5" />
  </svg>
)
export const IconClock = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
  </svg>
)
export const IconMail = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" />
  </svg>
)
export const IconLock = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
)
export const IconEye = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z" /><circle cx="12" cy="12" r="3" />
  </svg>
)
export const IconLightbulb = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M9 18h6M10 22h4" /><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1V17h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z" />
  </svg>
)
export const IconBook = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M4 4h6a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H4V4z" /><path d="M20 4h-6a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h6V4z" />
  </svg>
)
export const IconClipboard = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" />
    <path d="M9 11l2 2 4-4" />
  </svg>
)
export const IconStar = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 3l2.6 5.5 6 .8-4.4 4.3 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.3l6-.8L12 3z" />
  </svg>
)
export const IconSparkles = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3z" />
    <path d="M18.5 14l.8 2.2L21.5 17l-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" />
  </svg>
)
export const IconTarget = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.2" fill="currentColor" />
  </svg>
)
export const IconUsers = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <circle cx="9" cy="8" r="3.2" /><path d="M3 20c0-3.3 2.7-5 6-5s6 1.7 6 5" /><path d="M16 4.5a3.2 3.2 0 0 1 0 6.3M18 15.5c1.7.8 3 2.2 3 4.5" />
  </svg>
)
export const IconBell = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M6 9a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 13 6 9z" /><path d="M10 18a2 2 0 0 0 4 0" />
  </svg>
)
export const IconTutor = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M4 6h16M4 12h10M4 18h7" /><path d="M18 18l-2 4 4-2 3 1 1-4-4-1-2 2z" />
  </svg>
)
export const IconExpand = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5" />
  </svg>
)
export const IconCollapse = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M8 8H3v-5M16 8h5V3M8 16H3v5M16 16h5v5" />
  </svg>
)
export const IconBack = (p: IconProps) => (
  <svg {...base(p.size, p.className, p.style)}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </svg>
)
