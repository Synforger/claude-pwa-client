// chat 経路の自己完結 owner (= W2 Phase F-1)。 旧 AppShell.jsx に詰まっていた chat slice 群
// (= useChatStorage / useChatStream / useAttachments / useAutoScroll / useViewsWs + 派生 hook +
// handler + JSX) を物理移送、 ロジック改変ゼロ。 ChatPanel が mount/unmount すると chat 状態
// (= messages / input / loading 等) が失われるため、 AppShell は viewMode に関わらず本 component
// を常時 mount し、 表示制御は内部 hidden ラッパで display:none する (= 旧 AppShell の chat 領域
// inline style と同等)。
//
// AppShell 側からの遷移ロジックで触れる必要のあるもの (= confirmDelete dialog + handleDeleteSession)
// は AppShell に残置 (= drawer から開く dialog が terminal 表示時にも見える必要があるため、 hidden な
// ChatPanel 配下に置けない)。 詳細は AppShell.jsx 末尾の F-1 注釈参照。
import { useEffect, useRef, useMemo, useCallback, useState, useSyncExternalStore } from 'react'
import { registerPerfContext } from '../features/app-effects/perfProbe.js'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../state/ui.js'
import {
  subscribe as subscribeEphemeral,
  getSnapshot as getEphemeralSnapshot,
  setSendFailedText as storeSetSendFailedText,
  setStopUnavailableSid as storeSetStopUnavailableSid,
} from '../state/ephemeral.js'
import { apiFetch } from '../utils/api.js'
import { useSessions } from '../features/session-drawer/useSessions.js'
import { useSessionsOverview } from '../features/session-drawer/useSessionsOverview.js'
import { useSessionActivity } from '../features/session-drawer/useSessionActivity.js'
import { useViewsWs } from '../features/session-drawer/useViewsWs.js'
import { useChatStorage } from '../features/chat/useChatStorage.js'
import { useAutoScroll } from '../features/chat/useAutoScroll.js'
import { useChatStream } from '../features/chat/useChatStream.js'
import { useAttachments } from '../features/attachments/useAttachments.js'
import { gcImages } from '../features/attachments/imageStore.js'
import { useStatus } from '../features/status-bar/useStatus.js'
import { useSessionBadges } from '../features/push-notify/useSessionBadges.js'
import { useRunningSubagents } from '../features/chat/useRunningSubagents.js'
import { setBadge } from '../features/push-notify/badge.js'
import ActivityBar from '../features/tasks/ActivityBar.jsx'
import { PromptStateBanner } from '../features/status-bar/PromptStateBanner.jsx'
import ChatInput from '../features/chat/ChatInput.jsx'
import MessageList from '../features/chat/MessageList.jsx'
import { sortByTs } from '../features/chat/sortByTs.js'
import AttachmentsBar from '../features/chat/AttachmentsBar.jsx'
import PlanApprovalBubble from '../features/plan-approval/PlanApprovalBubble.jsx'

// 起動時の初回 GC 遅延 (= localStorage 復元 + 初期 fetch の messages 確定を待つ)。
const IMAGE_GC_INITIAL_MS = 5000

// messages dict から全 imageRefs を抽出するヘルパ (= IndexedDB GC で active 集合作成に使う)。
function collectActiveImageIds(msgDict) {
  const active = new Set()
  for (const sid of Object.keys(msgDict)) {
    for (const m of msgDict[sid] || []) {
      if (m.imageRefs && Array.isArray(m.imageRefs)) {
        for (const id of m.imageRefs) active.add(id)
      }
    }
  }
  return active
}

// ChatInput.currentAttachments の安定 sentinel。 attachments[sid] が空の時に毎 render で
// 新しい `[]` を作ると ChatInput が memo を抜けるので、 共通参照を返す。
const EMPTY_ARR = []

// 一度に DOM に載せる message 数の上限 (= 巨大 session の render 負荷抑制)。
const DISPLAY_LIMIT = 100

// 表示 window の先頭 index。 過去閲覧中 (= scrolledUp) に新着で総数が増えても、 凍結した
// frozenStart を使い続けることで「今読んでいる上方の DOM が slice から抜けて内容が上に
// ジャンプする」 のを防ぐ (= 凍結中は window が末尾方向へだけ伸びる)。 pure 関数に
// 切り出しているのは契約 test 用。
export function displayWindowStart(totalLen, frozenStart, limit = DISPLAY_LIMIT) {
  const tail = Math.max(0, totalLen - limit)
  if (frozenStart === null || frozenStart === undefined) return tail
  return Math.min(frozenStart, tail)
}

export default function ChatPanel({ sid }) {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const { sessions, setActiveId, forkSession } = useSessions()

  const activeSession = useMemo(
    () => sessions.find(s => s.id === sid) || null,
    [sessions, sid],
  )
  const activeSid = activeSession?.id || null

  // タブごとの表示モード ('chat' | 'terminal')。 hidden ラッパは viewMode 派生で gate する。
  const activeViewMode = useMemo(
    () => (activeSid ? (ui.viewModes[activeSid] || 'chat') : 'chat'),
    [activeSid, ui.viewModes],
  )
  const hidden = activeViewMode === 'terminal'

  const { messages, setMessages, input, setInput } = useChatStorage(sessions)
  const { attachments, fileInputRef, handleFileSelect, removeAttachment, clearAttachments } = useAttachments(activeSession)
  const status = useStatus(activeSession)
  const {
    scrollerDomRef,
    isAtBottomRef,
    showScrollBtn,
    hasNew,
    scrollToBottom,
    onScroll,
  } = useAutoScroll({ messages, activeSession, viewMode: activeViewMode })
  // 「今この sid を見てる」 + Stop 意思を WebSocket で backend に通知。
  const { sendStopIntent } = useViewsWs(activeSid)
  // F-36: 送信失敗時に localText を ChatInput 内部 state に戻すための buffer。
  // F-16: stop が WS 切断で届かない時の UI 通知用 flag。
  // Phase J-12 (= 2026-06-29): 旧 useState を state/ephemeral.js singleton に統合
  // (= audit B sweep)。 write は active sid 限定 / consume で null クリア (one-shot)、
  // semantics は旧来通り。 ChatPanel は always-mount で 1 instance なので singleton で安全。
  const ephem = useSyncExternalStore(subscribeEphemeral, getEphemeralSnapshot)
  const sendFailedText = ephem.sendFailedText
  const stopUnavailableSid = ephem.stopUnavailableSid
  // W2 Phase F-4 残 (= 2026-06-29): endSession / stopMessage は features/dialogs/ConfirmEndDialog +
  // ConfirmStopDialog が useChatStream の module-level export 経由で直接呼ぶ経路に移行済。 ChatPanel
  // 内では参照しないので destructure しない (= 同 hook の mount で module-level impl が wire される)。
  const { loading, setLoading, sendMessage, fetchLatest, optimisticRef } = useChatStream({
    activeSession,
    setMessages,
    input, setInput,
    attachments, clearAttachments,
    scrollToBottom, isAtBottomRef,
    sendStopIntent,
    onSendFailed: (s2, text) => { if (s2 === activeSid) storeSetSendFailedText(text) },
    onStopUnavailable: (s2) => storeSetStopUnavailableSid(s2),
  })
  // loading (= 停止ボタンの真値) の唯一のソース。 backend 権威 busy を 1 本の SSE で受け、
  // 全タブの停止/送信ボタン + 青丸/赤丸を駆動する (= dual-driver 排除、 単一権威)。
  const overviewPayloadRef = useRef(null)
  useSessionsOverview({ setLoading, optimisticRef, onPayloadRef: overviewPayloadRef })

  // session 活動時刻の追跡 (= sessionActivity を state/sessions.js store に書込む副作用)。
  useSessionActivity(messages, sessions)

  // planOpen は state/ui.js.overlays.planOpen に統合 (= W2 Phase F-1、 旧 AppShell の useState 退役、
  // topbar の 📑 ボタンが setOverlay('planOpen', true) で開き、 ChatPanel が auto-close を担う)。
  // pending_plan が消えたら自動でダイアログも閉じる (= 承認後に手動で X するのを省く)。
  useEffect(() => {
    if (!status?.pending_plan && ui.overlays.planOpen) setOverlay('planOpen', false)
  }, [status?.pending_plan, ui.overlays.planOpen])

  // Topbar ⋯ メニューの「ファイル添付」 が bump した時 hidden <input type="file"> を発火する。
  // Topbar は fileInputRef を持たない (= 疎結合)、 ephemeral の counter 変化を検知して click。
  const attachmentPickerBump = ephem.attachmentPickerBump
  const prevAttachmentPickerBumpRef = useRef(attachmentPickerBump)
  useEffect(() => {
    if (prevAttachmentPickerBumpRef.current !== attachmentPickerBump) {
      prevAttachmentPickerBumpRef.current = attachmentPickerBump
      fileInputRef.current?.click()
    }
  }, [attachmentPickerBump, fileInputRef])

  // backend 再起動検知: status.backend_start_time が変化したら backend が再起動された
  // (= LaunchAgent KeepAlive で自動復活 or 手動 kickstart)。 中断された turn が
  // 「永遠に推論中」 のまま見えないように、 全 session の最後の streaming bubble を
  // 強制的に停止扱いに固定 + loading state を全 reset する。
  const lastBackendStartRef = useRef(null)
  useEffect(() => {
    if (!status?.backend_start_time) return
    const prev = lastBackendStartRef.current
    lastBackendStartRef.current = status.backend_start_time
    const sameAsLast = prev === status.backend_start_time
    if (sameAsLast) return
    if (prev !== null) {
      setLoading({})
      optimisticRef.current = {}
      setMessages(p => {
        const next = {}
        for (const sidKey of Object.keys(p)) {
          const arr = p[sidKey] || []
          if (arr.length === 0) { next[sidKey] = arr; continue }
          const last = arr[arr.length - 1]
          if (last?.streaming) {
            next[sidKey] = [...arr.slice(0, -1), { ...last, streaming: false }]
          } else {
            next[sidKey] = arr
          }
        }
        return next
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.backend_start_time, setLoading, setMessages])

  // F-01 (= 2026-06-21): dep を `messages` (= 全 sid 入り dict) → `activeMsgs` (= activeSid の
  // slice) に絞り、 他 sid の flush で displayMessages が recompute されないようにする。
  const activeMsgs = activeSid ? (messages[activeSid] || null) : null
  // 未回答の AskUserQuestion がある間、 チャット入力欄を「回答モード」 表示に切り替える
  // (= Type something 選択後は選択肢 banner が消えるので、 誘導は入力欄の placeholder で出す)。
  const answerMode = !!activeMsgs?.some(m => m.askUserQuestion && !m.askUserQuestion.answered)

  // 停止ボタンの表示判定 = backend 権威 loading の派生 (= 旧 AppShell)。
  // pending_plan (= ExitPlanMode 承認待ち) も止められる状態として拾う (2026-07-02)。
  // 質問待ちは Phase 2 (= 2026-07-06) 以降 status.pending_question でなく SSE 由来の
  // messages (= answerMode) で判定する。
  const showStopButton = !!(
    activeSid
    && (loading[activeSid] || answerMode || status?.pending_plan)
  )

  // SW からの「push-received」 メッセージで即座に fetchLatest を発火させる。
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const onMessage = (event) => {
      const d = event.data
      if (d?.type === 'push-received') {
        fetchLatest()
      } else if (d?.type === 'open-session' && d.sid) {
        setActiveId(d.sid)
      }
    }
    navigator.serviceWorker.addEventListener('message', onMessage)
    return () => navigator.serviceWorker.removeEventListener('message', onMessage)
  }, [fetchLatest, setActiveId])

  const handleOpenPath = useCallback((path) => {
    if (path.endsWith('/')) {
      setOverlay('treeOpen', path)
    } else {
      setOverlay('previewPath', path)
    }
  }, [])

  const handleStopClick = useCallback(() => setOverlay('confirmStop', true), [])
  const handleSendClick = useCallback((text) => sendMessage(text), [sendMessage])
  const handleSendFailedConsumed = useCallback(() => storeSetSendFailedText(null), [])
  const handleStopRecovered = useCallback(() => storeSetStopUnavailableSid(null), [])

  const handleOpenSubagents = useCallback((focus) => {
    setOverlay('subagentsFocus', focus || null)
    setOverlay('subagents', true)
  }, [])
  const handleFork = useCallback((uuid) => {
    if (!activeSid) return
    forkSession(activeSid, uuid)
  }, [activeSid, forkSession])
  const activeSubagentTool = status?.subagent?.last_tool || null
  const runningSubagents = useRunningSubagents(activeSid)

  const sids = useMemo(() => sessions.map(s => s.id), [sessions])
  const currentAttachments = (activeSid && attachments[activeSid]) || EMPTY_ARR

  const { unreadCount, onOverviewPayload } = useSessionBadges({ sids, activeSid, messages, loading })
  useEffect(() => { overviewPayloadRef.current = onOverviewPayload }, [onOverviewPayload])

  useEffect(() => {
    setBadge(unreadCount)
  }, [unreadCount])

  // 過去閲覧中 (= ↓ボタンが出ている = 底に居ない) は表示 window の先頭を凍結する。
  // 凍結しないと、 新着で総数が DISPLAY_LIMIT を超えた瞬間に slice(-LIMIT) の先頭 (= 今
  // 読んでいる上方) の DOM が削られて表示位置が上にジャンプする。 底へ戻ったら解除して
  // 通常の末尾 window に収束 (= 凍結中に伸びた DOM も回収)。
  const scrolledUp = ui.scroll.showScrollBtn
  const [frozenStart, setFrozenStart] = useState(null)
  const activeMsgsLen = (activeMsgs || []).length
  useEffect(() => {
    if (!activeSid || !scrolledUp) {
      setFrozenStart(null)
      return
    }
    // 凍結は最初の 1 回だけ確定 (= 以後の新着で動かさない)。 activeMsgsLen が deps に
    // 居ても prev 保持で再計算しない。
    setFrozenStart(prev => (prev !== null ? prev : Math.max(0, activeMsgsLen - DISPLAY_LIMIT)))
  }, [activeSid, scrolledUp, activeMsgsLen])

  const displayMessages = useMemo(() => {
    if (!activeSid) return []
    // **window を切る前に時系列へ整える** (= 2026-07-27 中抜け根治)。
    // messages 配列は末尾 append で溜まるので配列位置 ≠ 時系列。 特に「cache 復元 (= 直近の
    // 会話) が先頭 → GET 履歴取り込みで古い行が末尾に積まれる」 形になるため、 配列位置で
    // 末尾 DISPLAY_LIMIT 件を採ると、 位置の先頭に居る**新しい** cache 由来メッセージが
    // 窓外に落ちて画面から消える (= 実機報告「更新すると履歴が中抜けする」「最新が反映
    // されない」 の直接原因。 state には居るのに描画されない、 を実機で確認)。
    // ソートしてから採れば「時間の最新 N 件」 になり、 中抜けが原理的に起きない。
    const allMsgs = sortByTs(activeMsgs || [])
    const start = displayWindowStart(allMsgs.length, scrolledUp ? frozenStart : null)
    const msgs = start > 0 ? allMsgs.slice(start) : allMsgs
    // Phase 2 (= 2026-07-06): 旧 pending_question 合成 bubble は退役。 質問の真値は
    // SSE `ask_user_question` event → messages の askUserQuestion field、 ライブ回答 UI は
    // prompt detector banner。 「回答待ちで loading placeholder を出さない」 は answerMode で判定。
    return (loading[activeSid] && !msgs.some(m => m.streaming) && !answerMode)
      ? [...msgs, { id: '__loading__', role: '__loading__' }]
      : msgs
  }, [activeMsgs, loading, activeSid, answerMode, scrolledUp, frozenStart])

  // 発熱調査 段階 2 (= 2026-07-13): 毎分の perf beacon に「その時描画してた transcript の
  // 規模」 を同乗させる。 getter 登録方式なので集計 (= O(n) の文字数合計) は beacon が
  // 呼ぶ毎分 1 回だけ、 render 経路には ref 更新以外のコストを足さない。
  const perfCtxRef = useRef({ msgs: 0, total_msgs: 0 })
  perfCtxRef.current = {
    msgs: displayMessages.length,
    total_msgs: activeMsgsLen,
  }
  const displayMessagesRef = useRef([])
  displayMessagesRef.current = displayMessages
  useEffect(() => {
    return registerPerfContext(() => {
      let chars = 0
      for (const m of displayMessagesRef.current || []) chars += (m.text || '').length
      return { ...perfCtxRef.current, chars }
    })
  }, [])

  // W2 Phase F-4 残 (= 2026-06-29): handleEndSession は features/dialogs/ConfirmEndDialog.jsx に
  // 物理移送、 ChatPanel からは参照ゼロ化。 confirmEnd / confirmStop ダイアログ本体も同様に
  // OverlayHost 経由 render へ移行 (= 末尾 ConfirmDialog 2 件退役)。

  // IndexedDB 画像の orphan GC: 起動時 1 回 + セッション削除トリガで増分掃除。
  // dep は [] でよい (= 起動時 1 回しか走らせない、 起動から 5 秒待って messages 確定後に実行)。
  const messagesRefForGc = useRef(messages)
  useEffect(() => { messagesRefForGc.current = messages }, [messages])
  useEffect(() => {
    const id = setTimeout(() => {
      gcImages([...collectActiveImageIds(messagesRefForGc.current)]).catch(() => {})
    }, IMAGE_GC_INITIAL_MS)
    return () => clearTimeout(id)
  }, [])

  // 入力欄は active session が無い時だけ disabled。
  const inputDisabled = !activeSid

  return (
    <div
      className="cpc-chat-panel"
      data-sid={activeSid || ''}
      style={hidden ? { display: 'none' } : { display: 'contents' }}
    >

      {/* メッセージ一覧 + ↓ 最新へ。 旧 AppShell の `<div className="messages-container">` 配下を
        F-1 で features/chat/MessageList.jsx に移送 (= ロジック改変ゼロ)。 messages-container CSS
        class は drop (= App.css に該当 rule 無し、 layout 影響なし)。 */}
      <MessageList
        scrollerDomRef={scrollerDomRef}
        onScroll={onScroll}
        viewMode={activeViewMode}
        displayMessages={displayMessages}
        onOpenFile={handleOpenPath}
        activeSubagentTool={activeSubagentTool}
        runningSubagents={runningSubagents}
        onOpenSubagents={handleOpenSubagents}
        onFork={activeSid ? handleFork : null}
        showScrollBtn={showScrollBtn}
        hasNew={hasNew}
        scrollToBottom={scrollToBottom}
      />

      <AttachmentsBar
        activeSid={activeSid}
        currentAttachments={currentAttachments}
        removeAttachment={removeAttachment}
      />

      {/* tmux pane 入力待ち banner (= 2026-07-05 StatusBar chip から移設)。 待ち系
          state の時だけ出現、 excerpt + quick-reply button を入力欄の直上に出す。 */}
      <PromptStateBanner sid={activeSid} />

      <ActivityBar status={status} />

      {/* ChatInput は常時 mount。 terminal view では CSS hide で消すだけにする
          (= 2026-06-22)。 旧実装は条件レンダで unmount していたので、 chat → terminal →
          chat と戻ると ChatInput 内部 state (= localText) が消えて書きかけが失われていた。 */}
      <div style={{ display: activeViewMode === 'terminal' ? 'none' : undefined }}>
        {/* 2026-07-02: ⋯ メニュー Topbar 移設で、 hidden <input type="file"> を ChatPanel に
            引き上げ。 添付起動は Topbar → ephemeral(attachmentPickerBump) → ChatPanel effect が
            fileInputRef.click() を発火する経路 (= ChatInput が picker を知らずに済む疎結合)。 */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp,text/*,.py,.js,.ts,.jsx,.tsx,.md,.json,.css,.html,.yaml,.yml,.toml,.sh"
          multiple
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />
        <ChatInput
          activeSid={activeSid}
          activeSession={activeSession}
          input={input}
          setInput={setInput}
          inputDisabled={inputDisabled}
          showStopButton={showStopButton}
          onStop={handleStopClick}
          onSend={handleSendClick}
          currentAttachments={currentAttachments}
          sendFailedText={sendFailedText}
          onSendFailedConsumed={handleSendFailedConsumed}
          stopUnavailable={stopUnavailableSid === activeSid}
          onStopRecovered={handleStopRecovered}
          answerMode={answerMode}
        />
      </div>

      {/* ExitPlanMode 承認プロンプト。 topbar の 📑 ボタンタップで開く明示 open 制御
          (= setOverlay('planOpen', true))。 pending_plan が消えたら ChatPanel 内 effect が
          自動 close。 */}
      {ui.overlays.planOpen && status?.pending_plan && (
        <PlanApprovalBubble
          pendingPlan={status.pending_plan}
          onClose={() => setOverlay('planOpen', false)}
          onChoose={async (key) => {
            if (!activeSid) return
            await apiFetch(`/pty/${encodeURIComponent(activeSid)}/send`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text: key, enter: true }),
            }).catch(() => {})
            setOverlay('planOpen', false)
          }}
        />
      )}

      {/* W2 Phase F-4 残 (= 2026-06-29): confirmEnd / confirmStop ダイアログは
          features/dialogs/ConfirmEndDialog.jsx + ConfirmStopDialog.jsx + OverlayHost 経由
          に物理移送、 ChatPanel からは render ゼロ。 useChatStream の module-level export
          (= endSession / stopMessage) を hook mount 時に wire することで、 dialog 側から直呼出可能。 */}
    </div>
  )
}
