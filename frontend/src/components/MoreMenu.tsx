import React from 'react'
import type { LangStrings } from '../lib/tutorI18n'
import { IconPlus, IconTrash, IconTutor } from './Icons'

export function MoreMenu({ ui, tutorName, disabled, onNewChat, onClearChat, onProfile }: {
  ui: LangStrings
  tutorName: string
  disabled: boolean
  onNewChat: () => void
  onClearChat: () => void
  onProfile: () => void
}) {
  return (
    <div className="more-menu">
      <div className="mm-inner">
        <button type="button" className="mm-item" disabled={disabled} onClick={onNewChat}>
          <IconPlus size={15} /> {ui.newChatChip}
        </button>
        <button type="button" className="mm-item" disabled={disabled} onClick={onClearChat}>
          <IconTrash size={15} /> {ui.clearChatChip}
        </button>
        <button type="button" className="mm-item" disabled={disabled} onClick={onProfile}>
          <IconTutor size={15} /> {ui.profileOf.replace('{name}', tutorName)}
        </button>
      </div>
    </div>
  )
}
