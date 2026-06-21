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
import { useStatus } from './hooks/useStatus.js'
import { useOverlays } from './hooks/useOverlays.js'
import { useViewMode } from './hooks/useViewMode.js'
import { useOutsideClick } from './hooks/useOutsideClick.js'
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
import ChatInput from './components/ChatInput.jsx'
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

const FilePreviewModal = lazy(() => import('./overlays/FilePreviewModal.jsx'))
const SubagentsModal = lazy(() => import('./components/SubagentsModal.jsx'))
const FileTreePanel = lazy(() => import('./overlays/FileTreePanel.jsx'))
const FavoritesQuickPicker = lazy(() => import('./overlays/FavoritesQuickPicker.jsx'))
const TasksModal = lazy(() => import('./overlays/TasksModal.jsx'))
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
    forkSession,
    removeSession,
    renameSession,
    setNotifyMode,
  } = useSessions()

  const activeSession = useMemo(
    () => sessions.find(s => s.id === activeId) || null,
    [sessions, activeId],
  )
  // 全箇所共通の active セッション ID。 activeSession?.id を毎度書かない統一形。
  const activeSid = activeSession?.id || null

  const { messages, setMessages, input, setInput } = useChatStorage(sessions)
  // タブごとの表示モード (= 'chat' | 'terminal') + localStorage 永続化を hook 化 (= F-03)。
  const { activeViewMode, flippedViewMode, setActiveViewMode } = useViewMode(activeSid)
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
  const { loading, setLoading, apiKeySource, sendMessage, sendAnswer, stopMessage, fetchLatest, endSession, optimisticRef } = useChatStream({
    activeSession,
    setMessages,
    input, setInput,
    attachments, clearAttachments,
    scrollToBottom, isAtBottomRef,
    sendStopIntent,
  })
  // loading (= 停止ボタンの真値) の唯一のソース。 backend 権威 busy を 1 本の SSE で受け、
  // 全タブの停止/送信ボタン + 青丸/赤丸を駆動する (= dual-driver 排除、 単一権威)。
  // onPayloadRef は useSessionBadges が後段で wire する未読同期経路 (= last_seen_at)。
  const overviewPayloadRef = useRef(null)
  useSessionsOverview({ setLoading, optimisticRef, onPayloadRef: overviewPayloadRef })

  const storageInfo = useStorageQuota()

  // ドロワー並び順 / session 活動時刻
  const { sortedSessions } = useSessionActivity(messages, sessions)

  const [storageWarnDismissed, setStorageWarnDismissed] = useState(false)
  // overlay / modal / dialog 系 local state を 1 hook に集約 (= F-03、 useOverlays.js)。
  // desktopOpen / planOpen は派生制御 (= visibility 連動 / status auto-close) があるので
  // hook には入れず App.jsx に残置 (= 設計判断は useOverlays.js 冒頭 docstring 参照)。
  const ov = useOverlays()
  const [desktopOpen, setDesktopOpen] = useState(false)  // 画面共有 (Mac デスクトップ) overlay
  // ExitPlanMode 承認ダイアログの開閉。 旧仕様は pending_plan が出た瞬間に全画面 overlay
  // が自動展開する設計だったが、 「画面を遮らずにヘッダーに常駐して、 開きたい時だけ開く」
  // 形に変更 (2026-06-04)。 topbar の 📑 ボタンが pending_plan の在席を示し、
  // タップでこのダイアログを開く。 pending_plan が消えたら自動で閉じる。
  const [planOpen, setPlanOpen] = useState(false)
  // pending_plan が消えたら自動でダイアログも閉じる (= 承認後に手動で X するのを省く)。
  // この useEffect は planOpen 宣言より後に置くこと。 依存配列はレンダー中に同期評価される
  // ので、 宣言前に書くと planOpen が TDZ に入り ReferenceError で全画面クラッシュする。
  useEffect(() => {
    if (!status?.pending_plan && planOpen) setPlanOpen(false)
  }, [status?.pending_plan, planOpen])
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
  //
  // F-22 (= 2026-06-21): この effect は chat reset 専任に絞る (= push 関連は usePushSubscription
  // に一本化、 backend 再起動による subscription 同期は usePushSubscription の visibility +
  // interval ping が拾うので二重呼出不要)。
  const lastBackendStartRef = useRef(null)
  useEffect(() => {
    if (!status?.backend_start_time) return
    const prev = lastBackendStartRef.current
    lastBackendStartRef.current = status.backend_start_time
    const sameAsLast = prev === status.backend_start_time
    if (sameAsLast) return
    // backend 再起動時のみ意味を持つので prev !== null ガードを残す:
    //   - loading 全 reset
    //   - 楽観的 pendingSend deadline も全 reset (= 残ってると停止ボタンが居座る)
    //   - 各 session 末尾の streaming bubble を false に固定 (= 永遠の推論中表示を消す)
    if (prev !== null) {
      setLoading({})
      optimisticRef.current = {}
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
    // optimisticRef は ref なので deps 不要 (= ref.current 書き込みは再 render を起こさない)。
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

  // 通知タップで PWA が完全終了状態から起動された場合、 SW の openWindow が
  // /?ses=<sid> 付きで起動するので、 ここで URL param を読んで activeId に反映する。
  // postMessage 経路 (= 既存 PWA をフォアに戻す) と並走する fallback (= プロセス毎新規起動)。
  useEffect(() => {
    try {
      const sid = new URLSearchParams(window.location.search).get('ses')
      if (sid) {
        setActiveId(sid)
        // URL から消す (= reload で復活しないように)
        const url = new URL(window.location.href)
        url.searchParams.delete('ses')
        window.history.replaceState({}, '', url.pathname + (url.search || '') + url.hash)
      }
    } catch { /* ignore */ }
  }, [setActiveId])


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
      ov.setTreeOpen(path)
    } else {
      ov.setPreviewPath(path)
    }
  }, [ov])

  const handleAnswer = useCallback((tool_use_id, answer, isFree, optionCount) => {
    if (!activeSid) return
    sendAnswer(activeSid, tool_use_id, answer, isFree, optionCount)
  }, [sendAnswer, activeSid])

  // click-outside listener: ChatInput 内の ⋯ メニューを外側 click/tap で閉じる。
  // 旧手書き useEffect (= menuOpenRef 経由で listener を mount 時 1 回張替) を W2-C で
  // 用意した useOutsideClick hook 経由に置換 (= F-29 集約済 hook を活用、 enabled で
  // menu 閉時は listener 自体張らない)。
  useOutsideClick(menuRef, () => ov.setMenu(false), { enabled: ov.menu })

  const sids = useMemo(() => sessions.map(s => s.id), [sessions])
  const currentAttachments = (activeSid && attachments[activeSid]) || []

  // session ごとの新着 / 処理中 / 質問待ちバッジ計算 (= active session は常に既読)
  const { sessionBadges, unreadCount, markAsSeen, onOverviewPayload } = useSessionBadges({ sids, activeSid, messages, loading })
  // useSessionsOverview の payload を未読同期経路に流すための ref wire (= 順序逆転を吸収)。
  useEffect(() => { overviewPayloadRef.current = onOverviewPayload }, [onOverviewPayload])

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
    ov.setMenu(false)
    ov.setConfirmEnd(false)
    endSession()
  }

  const handleDeleteSession = async () => {
    if (!ov.confirmDelete) return
    const sid = ov.confirmDelete
    ov.setConfirmDelete(null)
    await removeSession(sid)
    // F-35 (= 2026-06-21): setMessages updater 内で「sid 削除後」 の全 messages から
    // imageIds snapshot を取り、 そのまま gcImages に渡す。 旧実装は setMessages 後に
    // 300ms setTimeout で messagesRefForGc.current を読んでいたが、 同 tick で別 sid が
    // streaming flush して ref が更新されると、 setTimeout 内では sid 削除前の状態を
    // 見てしまい (= 削除済 sid の画像 ref を active 扱いして) GC が無効化される race
    // があった。 updater 内 snapshot なら sid 削除と active 集合の計算が必ず同 state で
    // 揃う (= sid 削除前後どちらでも一貫した snapshot)。
    let activeAfterDelete = null
    setMessages(prev => {
      const next = { ...prev }
      delete next[sid]
      activeAfterDelete = [...collectActiveImageIds(next)]
      return next
    })
    if (activeAfterDelete) {
      gcImages(activeAfterDelete).catch(() => {})
    }
  }

  // Web Push 購読状態 (= 環境制約・トグル・連打防止) は専用 hook に集約。
  const { pushEnabled, pushBroken, pushBusy, pushAvailable, handleTogglePush } = usePushSubscription({
    onCloseMenu: () => ov.setMenu(false),
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
        <button className="hamburger" onClick={() => ov.setDrawer(true)} aria-label="会話一覧">
          ☰
        </button>
        <span className="topbar-title">{activeSession?.title || '会話なし'}</span>
        {/* terminal モード時の chat 復帰ボタン: ⋯メニュー経由が hit test 等で詰まっても
            ここから確実に戻れるよう topbar に独立表示。 chat モード時は出さない
            (= ターミナル表示への切替は ⋯メニュー側でやる、 戻る経路だけ常駐保証する設計)。 */}
        {activeViewMode === 'terminal' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => setActiveViewMode('chat')}
            aria-label="チャット表示に戻す"
            title="チャット表示に戻す"
          >
            💬
          </button>
        )}
        {/* topbar 右側のアイコン群。 並びは左→右で ⭐ お気に入り → 📋 タスク →
            🤖 サブエージェント → (📑 plan 承認、 条件付き) → 🖥 モニター。 つまり右からは
            モニター / サブエージェント / タスク / お気に入りの順 (2026-06-12 確定)。 */}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => ov.setFavs(true)}
            aria-label="お気に入り"
            title="お気に入りに飛ぶ"
          >
            ⭐
          </button>
        )}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => ov.setTasks(true)}
            aria-label="タスク"
            title="タスク一覧"
          >
            📋
          </button>
        )}
        {/* サブエージェント (= Task で起動した子 agent) の一覧 + transcript を見るモーダル。
            親 chat には sidechain を出さないので、 中身を遡りたい時はここから開く。 */}
        {activeViewMode === 'chat' && activeSid && (
          <button
            className="topbar-icon-btn"
            onClick={() => { ov.setSubagentsFocus(null); ov.setSubagents(true) }}
            aria-label="サブエージェント"
            title="サブエージェント一覧"
          >
            🤖
          </button>
        )}
        {/* ExitPlanMode 承認待ち: 🤖 の隣に常駐する 📑 ボタン。 pending_plan がある時のみ表示、
            脈動ドットで承認待ちを示し、 タップで PlanApprovalBubble を開く。 旧来の自動全画面
            overlay は画面を遮るのでやめた (2026-06-04 改修)。 */}
        {activeViewMode === 'chat' && activeSid && status?.pending_plan && (
          <button
            className="topbar-icon-btn topbar-plan-btn"
            onClick={() => setPlanOpen(true)}
            aria-label="plan 承認待ち"
            title="plan 承認"
          >
            📑<span className="topbar-plan-dot" />
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

      {ov.drawer && (
        <Suspense fallback={null}>
          <SessionDrawer
            open={ov.drawer}
            onClose={() => ov.setDrawer(false)}
            sessions={sortedSessions}
            agents={agents}
            activeId={activeId}
            onSelect={selectSession}
            onCreate={(agentId, accountId) => createSession(agentId, accountId)}
            onRename={renameSession}
            onSetNotifyMode={setNotifyMode}
            onDelete={(sid) => ov.setConfirmDelete(sid)}
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
        {/* 各 sid の Terminal を mount しっぱなしにして display で切替する。
            sid 切替 / view 切替で xterm.js + WebSocket が温存されるので、 タブを
            戻した時の「起動 1-2 秒」 待ちがゼロになる (= 2026-06-10 改修)。
            非 active な Terminal は display:none で隠れてるだけで WS は維持、
            backend へ受信 stdout が flow し続けて scrollback も自然に伸びる。 */}
        {sids.map(sid => (
          <div
            key={sid}
            style={{
              display: (activeViewMode === 'terminal' && sid === activeSid) ? 'block' : 'none',
              position: 'absolute',
              inset: 0,
            }}
          >
            <Terminal sessionId={sid} />
          </div>
        ))}
        {/* chat も Terminal と対称に mount しっぱなしで display 切替する。
            terminal モードへ行っても DOM が unmount されないので、 戻った時に
            scroll 位置 / 画像 / プレビューの内部状態がそのまま残る (= 2026-06-16)。 */}
        <div
          ref={scrollerDomRef}
          className="messages"
          onScroll={onScroll}
          style={activeViewMode === 'terminal' ? { display: 'none' } : undefined}
        >
          {displayMessages.map((msg) => (
            <MessageItem
              key={msg.id}
              msg={msg}
              onOpenFile={handleOpenPath}
              onAnswer={handleAnswer}
              apiKeySource={activeSid ? apiKeySource[activeSid] : null}
              activeSubagentTool={status?.subagent?.last_tool || null}
              onOpenSubagents={(focus) => { ov.setSubagentsFocus(focus || null); ov.setSubagents(true) }}
              onFork={activeSid ? ((uuid) => forkSession(activeSid, uuid)) : null}
            />
          ))}
        </div>

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
          menuOpen={ov.menu}
          setMenuOpen={ov.setMenu}
          onOpenTree={() => ov.setTreeOpen('~')}
          activeViewMode={activeViewMode}
          onToggleView={() => setActiveViewMode(flippedViewMode)}
          onEndSession={() => ov.setConfirmEnd(true)}
          showStopButton={showStopButton}
          onStop={() => ov.setConfirmStop(true)}
          onSend={(text) => sendMessage(text)}
          currentAttachments={currentAttachments}
        />
      )}

      {/* ExitPlanMode 承認プロンプト。 topbar の 📑 ボタンタップで開く明示 open 制御。
          pending_plan が消えたら自動で閉じる (= 承認が反映されたら片付ける)。 */}
      {planOpen && status?.pending_plan && (
        <PlanApprovalBubble
          pendingPlan={status.pending_plan}
          onClose={() => setPlanOpen(false)}
          onChoose={async (key) => {
            if (!activeSid) return
            await apiFetch(`/pty/${encodeURIComponent(activeSid)}/send`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text: key, enter: true }),
            }).catch(() => {})
            setPlanOpen(false)
          }}
        />
      )}

      <ConfirmDialog
        open={ov.confirmEnd}
        text="このセッションを終了しますか?"
        onCancel={() => ov.setConfirmEnd(false)}
        onConfirm={handleEndSession}
      />
      <ConfirmDialog
        open={ov.confirmStop}
        text="推論を停止しますか?"
        onCancel={() => ov.setConfirmStop(false)}
        onConfirm={() => { ov.setConfirmStop(false); stopMessage() }}
      />
      <ConfirmDialog
        open={!!ov.confirmDelete}
        text={
          <>
            この会話を削除しますか？
            <br />
            <span className="dim">会話履歴も削除されます。 元に戻せません。</span>
          </>
        }
        onCancel={() => ov.setConfirmDelete(null)}
        onConfirm={handleDeleteSession}
      />

      <Suspense fallback={null}>
        {ov.previewPath && (
          <FilePreviewModal path={ov.previewPath} onClose={() => ov.setPreviewPath(null)} />
        )}
        {ov.treeOpen && (
          <FileTreePanel
            initialPath={ov.treeOpen}
            onOpenFile={handleOpenPath}
            onClose={() => ov.setTreeOpen(null)}
          />
        )}
        {ov.subagents && activeSid && (
          <SubagentsModal sid={activeSid} focus={ov.subagentsFocus} onClose={() => ov.setSubagents(false)} />
        )}
        {ov.favs && (
          <FavoritesQuickPicker
            onOpenFile={(path) => ov.setPreviewPath(path)}
            onOpenDir={(path) => ov.setTreeOpen(path)}
            onClose={() => ov.setFavs(false)}
          />
        )}
        {ov.tasks && (
          <TasksModal
            tasks={status?.tasks || []}
            onClose={() => ov.setTasks(false)}
          />
        )}
      </Suspense>
    </div>
  )
}
