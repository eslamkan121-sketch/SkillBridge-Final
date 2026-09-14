import React from 'react'
import type { LangStrings } from '../lib/tutorI18n'
import { IconBolt, IconBook, IconHeadset, IconTrendingUp } from './Icons'

export function SuggestionGrid({ ui, onPick }: {
  ui: LangStrings
  onPick: (prompt: string) => void
}) {
  const cards: { icon: React.ReactNode; title: string; sub: string; prompt: string }[] = [
    {
      icon: <IconBook size={17} />,
      title: ui.suggExplain,
      sub: ui.suggExplainSub,
      prompt: 'Explain a concept simply and step by step.',
    },
    {
      icon: <IconBolt size={17} />,
      title: ui.suggPractice,
      sub: ui.suggPracticeSub,
      prompt: 'Give me a practical exercise to practice a skill.',
    },
    {
      icon: <IconHeadset size={17} />,
      title: ui.suggInterview,
      sub: ui.suggInterviewSub,
      prompt: 'Interview me like a hiring manager for my target role.',
    },
    {
      icon: <IconTrendingUp size={17} className="icon-directional" />,
      title: ui.suggCareer,
      sub: ui.suggCareerSub,
      prompt: 'Plan my next career step based on my profile.',
    },
  ]
  return (
    <div className="suggestion-grid">
      {cards.map((c) => (
        <button key={c.title} type="button" className="suggestion-card" onClick={() => onPick(c.prompt)}>
          <span className="suggestion-icon">{c.icon}</span>
          <span>
            <strong>{c.title}</strong>
            <span>{c.sub}</span>
          </span>
        </button>
      ))}
    </div>
  )
}