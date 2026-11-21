import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { subscribe as subscribeMessages, getSnapshot as getMessagesSnapshot } from '../../state/messages.js'
import { subscribe as subscribeSessions, getSnapshot as getSessionsSnapshot } from '../../state/sessions.js'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'
import { lsGet, lsSet } from '../../_common/storage.js'
import { useOutsideClick } from '../../_common/useOutsideClick.js'
import { useT } from '../../i18n/t.js'
import { parseRollover } from '../chat/agentMessage.js'
import MessageRenderer from '../chat/MessageRenderer.jsx'
import { openLinkedPath } from '../file-preview/openPath.js'
import { hideMarks, hideVoiceInputMark, useVoiceMarks } from '../voice/index.js'
import { lastOperatorReply, replyKeyOf } from './lastOperatorReply.js'
import './OperatorReplyDock.css'

// 右上の引き出し (= 🔖)。 操作者 に返した最後の答えを、 連絡が届いてチャットが流れても読めるように留める。
// 見ているタブの会話 (= state/messages.js) から選ぶだけで、 backend にも Claude にも何も足さない。
// 前に開いた時より新しい答えが来ている間は、 つまみに点を付ける (= 開いた答えの印は localStorage、 読めなくても壊れない)。

const SEEN_KEY_PREFIX = 'cpc_operator_reply_seen_'

const firstLine = (text) => (text.split('\n').find((line) => line.trim() !== '') || '').trim()

function clockOf(ts) {
  if (typeof ts !== 'number') return null
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function OperatorReplyDock() {
  const t = useT()
  const activeSid = useSyncExternalStore(subscribeSessions, getSessionsSnapshot).activeId
  const conversation = useSyncExternalStore(subscribeMessages, getMessagesSnapshot)[activeSid]
  const chatShown = useSyncExternalStore(subscribeUi, getUiSnapshot).viewModes[activeSid] !== 'terminal'
  const voiceMarks = useVoiceMarks()
  const [open, setOpen] = useState(false)
  const [seenKeys, setSeenKeys] = useState({})   // { [sid]: 開いて見た答えの印 }。 無ければ localStorage から
  const rootRef = useRef(null)
  useOutsideClick(rootRef, () => setOpen(false), { enabled: open })

  const found = useMemo(() => lastOperatorReply(conversation), [conversation])
  const replyKey = replyKeyOf(found?.reply)
  const seenKey = activeSid ? (seenKeys[activeSid] ?? lsGet(SEEN_KEY_PREFIX + activeSid, null)) : null

  // 開いている間に届いた答えも、 見たものとして覚える
  useEffect(() => {
    if (!open || !activeSid || replyKey === null) return
    setSeenKeys((prev) => (prev[activeSid] === replyKey ? prev : { ...prev, [activeSid]: replyKey }))
    lsSet(SEEN_KEY_PREFIX + activeSid, replyKey)
  }, [open, activeSid, replyKey])

  // タブを替えたら閉じる (= 別のタブの答えを開いたまま見せない)
  useEffect(() => { setOpen(false) }, [activeSid])

  if (!found || !chatShown) return null
  const { prompt, reply, ongoing, before } = found
  const rollover = parseRollover(prompt.text)
  const promptLine = rollover ? t('chat.rollover_start') : firstLine(hideVoiceInputMark(prompt.text))
  const promptClock = clockOf(prompt.ts)
  const unseen = !open && replyKey !== seenKey

  return (
    <div className="operator-reply" ref={rootRef} data-testid="operator-reply">
      <button
        type="button"
        className="operator-reply-knob"
        onClick={() => setOpen((v) => !v)}
        aria-label={t('operator_reply.knob')}
        aria-expanded={open}
        title={t('operator_reply.knob')}
        data-testid="operator-reply-knob"
      >
        🔖{unseen && <span className="operator-reply-dot" data-testid="operator-reply-dot" />}
      </button>
      {open && (
        <div className="operator-reply-panel" data-testid="operator-reply-panel">
          <div className="operator-reply-head">
            <span className="operator-reply-title">{t('operator_reply.title')}</span>
            {ongoing && <span className="operator-reply-writing" data-testid="operator-reply-writing">{t('operator_reply.still_writing')}</span>}
            <span className="operator-reply-prompt" data-testid="operator-reply-prompt">{promptLine}</span>
            {promptClock && <span className="operator-reply-clock">{promptClock}</span>}
          </div>
          <div className="operator-reply-body">
            {/* markdown の見た目は .bubble の下に掛かっているので、 吹き出しと同じ class で包む */}
            <div className="bubble operator-reply-bubble">
              <MessageRenderer
                text={hideMarks(reply.text, voiceMarks)}
                onOpenFile={(path) => openLinkedPath(path, { onLeave: () => setOpen(false) })}
                streaming={ongoing}
              />
            </div>
            {/* 入れ替えの後: 前の会話の最後の答えも、 書き直させずにここに残す */}
            {before && (
              <div className="operator-reply-before" data-testid="operator-reply-before">
                <div className="operator-reply-head">
                  <span className="operator-reply-title">{t('operator_reply.before_rollover')}</span>
                  <span className="operator-reply-prompt">{firstLine(hideVoiceInputMark(before.prompt.text))}</span>
                  {clockOf(before.prompt.ts) && <span className="operator-reply-clock">{clockOf(before.prompt.ts)}</span>}
                </div>
                <div className="bubble operator-reply-bubble">
                  <MessageRenderer
                    text={hideMarks(before.reply.text, voiceMarks)}
                    onOpenFile={(path) => openLinkedPath(path, { onLeave: () => setOpen(false) })}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
