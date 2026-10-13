// 今見ているタブの agent の、 言い方の印の一覧 (= 声を持たなければ undefined)。
import { useSyncExternalStore } from 'react'
import { subscribe as subscribeVoice, getSnapshot as getVoiceSnapshot } from '../../state/voice.js'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../../state/sessions.js'

export function useVoiceMarks() {
  const voice = useSyncExternalStore(subscribeVoice, getVoiceSnapshot)
  const sessions = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  return sessions.activeId ? voice.marks[sessions.activeId] : undefined
}
