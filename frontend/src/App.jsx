import { useState, useEffect, useRef, useMemo, useCallback, lazy, Suspense } from 'react'
import './App.css'
import MessageItem from './components/MessageItem.jsx'
import Terminal from './components/Terminal.jsx'
import ActivityBar from './components/ActivityBar.jsx'
import StatusBar from './components/StatusBar.jsx'
import StorageWarning from './components/StorageWarning.jsx'
import ConfirmDialog from './components/ConfirmDialog.jsx'
import PlanApprovalBubble from './components/PlanApprovalBubble.jsx'
import { apiFetch } from './utils/api.js'
import { lsGet, lsSet } from './utils/storage.js'
import { useStatus } from './hooks/useStatus.js'
import { useAttachments } from './hooks/useAttachments.js'
import { useChatStorage } from './hooks/useChatStorage.js'
import { useAutoScroll } from './hooks/useAutoScroll.js'
import { useChatStream } from './hooks/useChatStream.js'
import { useSessionsOverview } from './hooks/useSessionsOverview.js'
import { useSessions } from './hooks/useSessions.js'
import { useStorageQuota } from './hooks/useStorageQuota.js'
import {
  useReadOnSessionOpen,
  useDeepLink,
  useSessionActivity,
  useSessionBadges,
  useNotificationClear,
  useMoonlightAvailable,
} from './hooks/useAppEffects.js'
import { setBadge } from './utils/badge.js'
import { gcImages } from './utils/imageStore.js'
import { usePushSubscription } from './hooks/usePushSubscription.js'
import { useViewsWs } from './hooks/useViewsWs.js'
import { enablePush, isPushEnabledLocally } from './utils/push.js'
import ChatInput from './components/ChatInput.jsx'
// session 削除後の IndexedDB orphan 画像掃除を遅延する時間 (= setMessages の state 反映を待つ)。
const IMAGE_GC_AFTER_DELETE_MS = 300
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

const FilePreviewModal = lazy(() => import('./FilePreviewModal.jsx'))
const SubagentsModal = lazy(() => import('./components/SubagentsModal.jsx'))
const FileTreePanel = lazy(() => import('./FileTreePanel.jsx'))
// SessionDrawer は drawerOpen=true の時のみ render = 遅延 load 妥当 (= 初回 paint 早く)
const SessionDrawer = lazy(() => import('./components/SessionDrawer.jsx'))
// 画面共有 (= moonlight-web-stream を iframe 埋め込み)。 開いた時だけ load。
const MoonlightFrame = lazy(() => import('./components/MoonlightFrame.jsx'))

export default function App() {
  // セッション (= UI 上のタブ = 1 議題) 管理
  const {
    sessions,
    activeId,
    setActiveId,
    agents,
    createSession,
    removeSession,
    renameSession,
  } = useSessions()

  const activeSession = useMemo(
    () => sessions.find(s => s.id === activeId) || null,
    [sessions, activeId],
  )
  // 全箇所共通の active セッション ID。 activeSession?.id を毎度書かない統一形。
  const activeSid = activeSession?.id || null

  const { messages, setMessages, input, setInput } = useChatStorage(sessions)
  // タブごとの表示モード (= 'chat' | 'terminal')。 デバッグ用に生 xterm を見たいタブだけ
  // terminal にし、 localStorage で永続化する (= そのタブはターミナル、 別タブは chat)。
  const [viewModes, setViewModes] = useState(() => lsGet('cpc_view_modes') || {})
  useEffect(() => { lsSet('cpc_view_modes', viewModes) }, [viewModes])
  const activeViewMode = activeSid ? (viewModes[activeSid] || 'chat') : 'chat'
  // toggle ヘルパは「現在 mode → 反転 mode」 を計算する純粋関数として残し、
  // 実際の setViewModes 呼出は呼び出し側で行う (= topbar の 💬 戻るボタンと同じ
  // 「set 直書き」 経路に統一して、 useCallback closure 経由で動かない疑惑を消す)。
  const flippedViewMode = activeViewMode === 'terminal' ? 'chat' : 'terminal'
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
  // Stop は HTTP POST から WS 経由に移行 (= 失敗時 race の根本治療)。 useChatStream より
  // 先に呼ぶ必要があるのは sendStopIntent を stopMessage に渡すため。
  const { sendStopIntent } = useViewsWs(activeSid)
  const { loading, setLoading, apiKeySource, sendMessage, sendAnswer, stopMessage, fetchLatest, endSession, pendingSendRef } = useChatStream({
    activeSession,
    setMessages,
    input, setInput,
    attachments, clearAttachments,
    scrollToBottom, isAtBottomRef,
    sendStopIntent,
  })
  // loading (= 停止ボタンの真値) の唯一のソース。 backend 権威 busy を 1 本の SSE で受け、
  // 全タブの停止/送信ボタン + 青丸/赤丸を駆動する (= dual-driver 排除、 単一権威)。
  useSessionsOverview({ setLoading, pendingSendRef })

  const storageInfo = useStorageQuota()

  // ドロワー並び順 / session 活動時刻
  const { sortedSessions } = useSessionActivity(messages, sessions)

  const [storageWarnDismissed, setStorageWarnDismissed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [desktopOpen, setDesktopOpen] = useState(false)  // 画面共有 (Mac デスクトップ) overlay
  const [menuOpen, setMenuOpen] = useState(false)
  const [previewPath, setPreviewPath] = useState(null)
  const [treeOpen, setTreeOpen] = useState(null)
  const [subagentsOpen, setSubagentsOpen] = useState(false)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null) // 削除確認中の session_id
  const [confirmStop, setConfirmStop] = useState(false)
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000))
  // 30 秒ごとに時刻表示を更新。 ただし hidden 中は止める (= 見えてないので無駄、 iOS は
  // background でも setInterval が呼ばれる時間帯があり電力消費要因になる)。
  // visible 復帰時は即同期して、 ユーザが古い数字を見る瞬間を作らない。
  useEffect(() => {
    let id = null
    const tick = () => setNowSec(Math.floor(Date.now() / 1000))
    const start = () => {
      if (id != null) return
      tick()
      id = setInterval(tick, 30000)
    }
    const stop = () => {
      if (id != null) { clearInterval(id); id = null }
    }
    const onVis = () => { document.hidden ? stop() : start() }
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVis)
    return () => { stop(); document.removeEventListener('visibilitychange', onVis) }
  }, [])

  // 画面共有 (= Sunshine ストリーム) は見てる間だけ生かす。 PWA がバックグラウンド /
  // 画面ロックに入ったら iframe を unmount して WebRTC を切る (= moonlight streamer が
  // 終了し Sunshine のエンコードが止まる)。 これをしないと閉じ忘れたまま放置で
  // Sunshine が延々エンコードし続け CPU + メモリを食い潰す (= ゾンビストリーム観測実績
  // あり)。 復帰時は自動再開せず、 ユーザが 🖥 を再タップして開き直す。
  useEffect(() => {
    const onHidden = () => { if (document.hidden) setDesktopOpen(false) }
    document.addEventListener('visibilitychange', onHidden)
    return () => document.removeEventListener('visibilitychange', onHidden)
  }, [])
  const menuRef = useRef(null)

  // backend / 通知 / deep link 系の effect を hook に集約 (= useAppEffects.js)
  useReadOnSessionOpen(activeSid)
  useDeepLink(setActiveId)
  useNotificationClear()
  const moonlightAvailable = useMoonlightAvailable()

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
    // backend 再起動 or 初回 mount の同期化処理。 既存処理は backend 再起動時のみ意味
    // を持つので prev !== null ガードを残す:
    //   - loading 全 reset
    //   - 楽観的 pendingSend deadline も全 reset (= 残ってると停止ボタンが居座る)
    //   - 各 session 末尾の streaming bubble を false に固定 (= 永遠の推論中表示を消す)
    if (prev !== null) {
      setLoading({})
      pendingSendRef.current = {}
      setMessages(p => {
        const next = {}
        for (const sid of Object.keys(p)) {
          const arr = p[sid] || []
          if (arr.length === 0) { next[sid] = arr; continue }
          const last = arr[arr.length - 1]
          if (last?.streaming) {
            next[sid] = [...arr.slice(0, -1), { ...last, streaming: false }]
          } else {
            next[sid] = arr
          }
        }
        return next
      })
    }
    // PushSubscription の再発行は初回 mount 時も実行する (= リロード後に backend と
    // subscription が乖離してても自動で同期する)。 enablePush は idempotent (= 同 endpoint
    // なら backend 側で upsert) なので mount のたびに呼んでも害なし。
    if (isPushEnabledLocally()) {
      enablePush().catch(() => { /* 失敗時は UI ボタンで手動再有効化 */ })
    }
    // pendingSendRef は ref なので deps 不要 (= ref.current 書き込みは再 render を起こさない)。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.backend_start_time, setLoading, setMessages])

  // 停止ボタンの表示判定 = backend 権威 loading の**派生**(参照実装の「ボタンは導出、 独立
  // boolean を持たない」 原則)。 loading[sid] は useSessionsOverview が backend busy + 送信直後
  // の楽観フラグから唯一管理する。 旧来の now タイマー / isPendingSend (= 1500ms 窓) は撤去。
  //   - loading[activeSid]        : ターン進行中 (= 推論中) → 停止
  //   - status?.pending_question  : AskUserQuestion 回答待ち → 停止 (= 質問中の誤送信を防ぐ)
  const showStopButton = !!(
    activeSid
    && (loading[activeSid] || status?.pending_question)
  )

  // SW からの「push-received」 メッセージで即座に fetchLatest を発火させる。
  // status polling (idle 30 秒) の隙間で proactive turn が完了/進行してても、
  // Web Push 受信 → SW postMessage → ここで fetchLatest → SSE 接続で取得、 のフローで
  // 取りこぼしを防ぐ。
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const onMessage = (event) => {
      const d = event.data
      if (d?.type === 'push-received') {
        fetchLatest()
      } else if (d?.type === 'open-session' && d.sid) {
        // 通知タップで送られてくる。 該当 session をフォアグラウンドに切替。
        setActiveId(d.sid)
      }
    }
    navigator.serviceWorker.addEventListener('message', onMessage)
    return () => navigator.serviceWorker.removeEventListener('message', onMessage)
  }, [fetchLatest, setActiveId])

  // 今 active で見ている session を SW に伝える (= sw.js の LINE 流抑制で使う)。
  // visibility=hidden の時は sid=null を送って「見てない」 扱いにする (= bg/別アプリ時に
  // 通知が届くべき状態を明示)。 SW direct postMessage で backend は介さない。
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return
    const post = () => {
      const ctrl = navigator.serviceWorker.controller
      if (!ctrl) return
      ctrl.postMessage({
        type: 'active-session',
        sid: document.visibilityState === 'visible' ? (activeSid || null) : null,
      })
    }
    post()
    document.addEventListener('visibilitychange', post)
    return () => document.removeEventListener('visibilitychange', post)
  }, [activeSid])

  const handleOpenPath = useCallback((path) => {
    if (path.endsWith('/')) {
      setTreeOpen(path)
    } else {
      setPreviewPath(path)
    }
  }, [])

  const handleAnswer = useCallback((tool_use_id, answer, isFree, optionCount) => {
    if (!activeSid) return
    sendAnswer(activeSid, tool_use_id, answer, isFree, optionCount)
  }, [sendAnswer, activeSid])

  // click-outside listener: menu open/close で add/remove を繰り返さず、 mount 時 1 回登録。
  // menuOpen の値は ref 経由で読み取り、 dep 変化での listener 付け外し race を消す。
  const menuOpenRef = useRef(menuOpen)
  useEffect(() => { menuOpenRef.current = menuOpen }, [menuOpen])
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (!menuOpenRef.current) return
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const sids = useMemo(() => sessions.map(s => s.id), [sessions])
  const currentAttachments = (activeSid && attachments[activeSid]) || []

  // session ごとの新着 / 処理中 / 質問待ちバッジ計算 (= active session は常に既読)
  const { sessionBadges, unreadCount, markAsSeen } = useSessionBadges({ sids, activeSid, messages, loading })

  // アプリアイコンのバッジ数字 = サイドバーで赤丸が立ってる session 数 と同期。
  // frontend が真理 (= backend の unread_count は SW push 経由の近似値、 起動後は
  // frontend が即座に正値で上書き)。
  useEffect(() => {
    setBadge(unreadCount)
  }, [unreadCount])
  // session を tap した時に activeSid 切替と同時に markAsSeen を呼ぶことで、
  // useEffect の遅延を待たずに「赤丸が確実に消える」 状態を作る。
  const selectSession = useCallback((sid) => {
    setActiveId(sid)
    markAsSeen(sid)
  }, [setActiveId, markAsSeen])

  const displayMessages = useMemo(() => {
    if (!activeSid) return []
    // 直近 N 件のみ render する。 古い履歴は state / localStorage には残っているが DOM に
    // 出さない (= 過去が積み上がって scrollHeight が膨らみ、 scroll が途中で止まる /
    // 「↓ボタン」 で底まで届かない症状の根本対策)。 N は実体感で調整可能。
    const DISPLAY_LIMIT = 100
    const allMsgs = messages[activeSid] || []
    const msgs = allMsgs.length > DISPLAY_LIMIT ? allMsgs.slice(-DISPLAY_LIMIT) : allMsgs
    // AskUserQuestion のライブ表示: backend が PreToolUse hook で立てた pending_question を
    // messages 末尾にバブルとして差し込む (= overlay でなく既存の chat 流れに乗せる)。
    // 回答後は JSONL flush で本物の回答済みバブルが messages に入り、 同時に backend が
    // pending_question を clear するので、 このライブバブルは自然に消える。
    const pq = status?.pending_question
    const base = (loading[activeSid] && !msgs.some(m => m.streaming) && !pq)
      ? [...msgs, { id: '__loading__', role: '__loading__' }]
      : msgs
    if (pq) {
      return [...base, {
        id: '__pending_question__',
        role: 'agent',
        text: '',
        tools: [],
        streaming: false,
        askUserQuestion: {
          tool_use_id: pq.tool_use_id,
          questions: pq.questions,
          answered: false,
          selectedAnswer: null,
        },
      }]
    }
    return base
  }, [messages, loading, activeSid, status?.pending_question])

  const handleEndSession = () => {
    setMenuOpen(false)
    setConfirmEnd(false)
    endSession()
  }

  const handleDeleteSession = async () => {
    if (!confirmDelete) return
    const sid = confirmDelete
    setConfirmDelete(null)
    await removeSession(sid)
    setMessages(prev => {
      const next = { ...prev }
      delete next[sid]
      return next
    })
    // セッション削除で参照が一気に消えるので IndexedDB の orphan 画像も掃除する。
    // 削除後 messagesRefForGc が反映されるのを少し待ってから走らせる。
    setTimeout(() => {
      gcImages([...collectActiveImageIds(messagesRefForGc.current)]).catch(() => {})
    }, IMAGE_GC_AFTER_DELETE_MS)
  }

  // Web Push 購読状態 (= 環境制約・トグル・連打防止) は専用 hook に集約。
  const { pushEnabled, pushBroken, pushBusy, pushAvailable, handleTogglePush } = usePushSubscription({
    onCloseMenu: () => setMenuOpen(false),
  })

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

  // 入力欄は active session が無い時だけ disabled。 loading[activeSid] (= 推論中) でも
  // ユーザーは次に送る文を編集しておけるように許可 — 送信ボタンは loading 中は停止ボタン
  // に切り替わるので、 推論完了 → 自動で送信ボタンに戻る → ユーザーが押す、 で流れる。
  const inputDisabled = !activeSid

  return (
    <div className="app">
      <StatusBar
        status={status}
        nowSec={nowSec}
      />
      <StorageWarning
        info={storageInfo}
        dismissed={storageWarnDismissed}
        onDismiss={() => setStorageWarnDismissed(true)}
      />

      {/* ヘッダ: ハンバーガー + セッション名 + 画面共有 */}
      <header className="topbar">
        <button className="hamburger" onClick={() => setDrawerOpen(true)} aria-label="会話一覧">
          ☰
        </button>
        <span className="topbar-title">{activeSession?.title || '会話なし'}</span>
        {/* terminal モード時の chat 復帰ボタン: ⋯メニュー経由が hit test 等で詰まっても
            ここから確実に戻れるよう topbar に独立表示。 chat モード時は出さない
            (= ターミナル表示への切替は ⋯メニュー側でやる、 戻る経路だけ常駐保証する設計)。 */}
        {activeViewMode === 'terminal' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => setViewModes(prev => ({ ...prev, [activeSid]: 'chat' }))}
            aria-label="チャット表示に戻す"
            title="チャット表示に戻す"
          >
            💬
          </button>
        )}
        {/* サブエージェント (= Task で起動した子 agent) の一覧 + transcript を見るモーダル。
            親 chat には sidechain を出さないので、 中身を遡りたい時はここから開く。 */}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => setSubagentsOpen(true)}
            aria-label="サブエージェント"
            title="サブエージェント一覧"
          >
            🧩
          </button>
        )}
        {/* 画面共有 (= moonlight-web-stream を iframe で埋め込み) ON/OFF。
            backend で /moonlight/ プロキシが有効な場合 (= Path B セットアップ済) だけ
            表示。 chat + 通知だけのユーザにはアイコン自体出さない (= 押しても 404)。 */}
        {moonlightAvailable && (
          <button
            className={`screen-toggle ${desktopOpen ? 'active' : ''}`}
            onClick={() => setDesktopOpen(prev => !prev)}
            aria-label="画面共有"
            title={desktopOpen ? '画面共有を閉じる' : '画面共有を開く (Sunshine 経由、 ペア済前提)'}
          >
            🖥
          </button>
        )}
      </header>

      {/* 画面共有 iframe (= moonlight-web-stream を埋め込み、 Mac の Sunshine と
          連携)。 desktopOpen=true かつ moonlightAvailable の時だけ render。 */}
      {desktopOpen && moonlightAvailable && (
        <Suspense fallback={null}>
          <MoonlightFrame />
        </Suspense>
      )}

      {drawerOpen && (
        <Suspense fallback={null}>
          <SessionDrawer
            open={drawerOpen}
            onClose={() => setDrawerOpen(false)}
            sessions={sortedSessions}
            agents={agents}
            activeId={activeId}
            onSelect={selectSession}
            onCreate={(agentId) => createSession(agentId)}
            onRename={renameSession}
            onDelete={(sid) => setConfirmDelete(sid)}
            sessionBadges={sessionBadges}
            pushAvailable={pushAvailable}
            pushEnabled={pushEnabled}
            pushBroken={pushBroken}
            pushBusy={pushBusy}
            onTogglePush={handleTogglePush}
          />
        </Suspense>
      )}

      {/* メッセージ一覧。 .messages は通常 flex-direction: column、 古い→新しい が上→下。
        起動 / 新着時は useAutoScroll が JS で scrollTop = scrollHeight に送って底辺維持。 */}
      <div className="messages-container">
        {activeViewMode === 'terminal' && activeSid ? (
          /* デバッグ用 生 xterm (= このタブだけ terminal 表示、 設定は localStorage 永続)。
             key=activeSid で session 単位に独立 instance を保つ。 */
          <Terminal key={activeSid} sessionId={activeSid} />
        ) : (
          <div ref={scrollerDomRef} className="messages" onScroll={onScroll}>
            {displayMessages.map((msg) => (
              <MessageItem
                key={msg.id}
                msg={msg}
                onOpenFile={handleOpenPath}
                onAnswer={handleAnswer}
                apiKeySource={activeSid ? apiKeySource[activeSid] : null}
                activeSubagentTool={status?.subagent?.last_tool || null}
              />
            ))}
          </div>
        )}

        {activeViewMode !== 'terminal' && showScrollBtn && (
          <button className="scroll-btn" onClick={() => scrollToBottom()} aria-label="最新メッセージへ">
            ↓
            {hasNew && <span className="scroll-dot" />}
          </button>
        )}
      </div>

      {currentAttachments.length > 0 && (
        <div className="attachments-bar">
          {currentAttachments.map((item, i) => (
            <div key={i} className="attach-chip">
              {item.url ? (
                <img src={item.url} className="attach-thumb" alt="" />
              ) : (
                <span className="attach-name">📄 {item.file.name}</span>
              )}
              <button className="attach-remove" onClick={() => removeAttachment(activeSid, i)} aria-label="添付を削除">×</button>
            </div>
          ))}
        </div>
      )}

      <ActivityBar status={status} />

      {activeViewMode !== 'terminal' && (
        <ChatInput
          activeSid={activeSid}
          activeSession={activeSession}
          input={input}
          setInput={setInput}
          inputDisabled={inputDisabled}
          fileInputRef={fileInputRef}
          onFileSelect={handleFileSelect}
          menuRef={menuRef}
          menuOpen={menuOpen}
          setMenuOpen={setMenuOpen}
          onOpenTree={() => setTreeOpen('~')}
          activeViewMode={activeViewMode}
          onToggleView={() => { if (activeSid) setViewModes(prev => ({ ...prev, [activeSid]: flippedViewMode })) }}
          onEndSession={() => setConfirmEnd(true)}
          showStopButton={showStopButton}
          onStop={() => setConfirmStop(true)}
          onSend={() => sendMessage()}
          currentAttachments={currentAttachments}
        />
      )}

      {/* claude が ExitPlanMode で出した承認プロンプトを overlay として表示。
          backend がアクティブ session の agent_status.pending_plan を SSE で流す。 */}
      {status?.pending_plan && (
        <PlanApprovalBubble
          pendingPlan={status.pending_plan}
          onChoose={async (key) => {
            if (!activeSid) return
            await apiFetch(`/pty/${encodeURIComponent(activeSid)}/send`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text: key, enter: true }),
            }).catch(() => {})
          }}
        />
      )}

      <ConfirmDialog
        open={confirmEnd}
        text="このセッションを終了しますか?"
        onCancel={() => setConfirmEnd(false)}
        onConfirm={handleEndSession}
      />
      <ConfirmDialog
        open={confirmStop}
        text="推論を停止しますか?"
        onCancel={() => setConfirmStop(false)}
        onConfirm={() => { setConfirmStop(false); stopMessage() }}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        text={
          <>
            この会話を削除しますか？
            <br />
            <span className="dim">会話履歴も削除されます。 元に戻せません。</span>
          </>
        }
        onCancel={() => setConfirmDelete(null)}
        onConfirm={handleDeleteSession}
      />

      <Suspense fallback={null}>
        {previewPath && (
          <FilePreviewModal path={previewPath} onClose={() => setPreviewPath(null)} />
        )}
        {treeOpen && (
          <FileTreePanel
            initialPath={treeOpen}
            onOpenFile={handleOpenPath}
            onClose={() => setTreeOpen(null)}
          />
        )}
        {subagentsOpen && activeSid && (
          <SubagentsModal sid={activeSid} onClose={() => setSubagentsOpen(false)} />
        )}
      </Suspense>
    </div>
  )
}
