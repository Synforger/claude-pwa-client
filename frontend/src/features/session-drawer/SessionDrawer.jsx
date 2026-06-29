import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { apiFetch } from '../../utils/api.js'
import { useOutsideClick } from '../../hooks/useOutsideClick.js'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
  setActiveId as storeSetActiveId,
  clearUnreadDone,
} from '../../state/sessions.js'
import {
  subscribe as subscribeMessages,
  getSnapshot as getMessagesSnapshot,
} from '../../state/messages.js'
import {
  subscribe as subscribeEphemeral,
  getSnapshot as getEphemeralSnapshot,
} from '../../state/ephemeral.js'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../../state/ui.js'
import {
  createSession,
  renameSession,
  setNotifyMode,
} from './useSessions.js'
import { deriveSessionBadges } from '../push-notify/useSessionBadges.js'
import { usePushSubscription } from '../push-notify/usePushSubscription.js'
import './SessionDrawer.css'

// ⋯ メニューを押した時、 viewport 下端からどれくらい離れていれば「上方向に展開する」 と
// 判定するか (= px)。 近すぎると下に展開した popup が画面外に出るので flip-up に切替。
const MENU_FLIP_UP_THRESHOLD_PX = 140

// 左サイドからスライドインする会話一覧ドロワー (ChatGPT 風)。
// - 上部: 「+ 新規会話」 → agent を選ぶ → createSession
// - リスト: 会話項目をタップで activeSession 切替、 ⋯ メニューでリネーム / 削除
// - badges: pending(?)、 processing(●青)、 new(●赤) を項目右に表示
// - ヘッダの ⋯ : ドロワー総合メニュー (通知 ON/OFF、 リセット等の PWA レベル設定)
//
// W2 Phase E-2 (= 2026-06-29): props 自己解決化。 OverlayHost が引数なしで lazy + Suspense で
// render し、 本 component は state/sessions.js + state/messages.js + state/ephemeral.js +
// state/ui.js を直接 subscribe する。 mutation API (= createSession / renameSession /
// setNotifyMode) は useSessions.js export を直呼出。 push 系は usePushSubscription を内蔵。
export default function SessionDrawer() {
  // store 直接 subscribe (= sessions list / activeId / agents / sessionActivity / unreadDone)
  const sessionsSnap = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const messages = useSyncExternalStore(subscribeMessages, getMessagesSnapshot)
  const ephem = useSyncExternalStore(subscribeEphemeral, getEphemeralSnapshot)
  // ui state: overlays.drawer は OverlayHost が gating するので render 時点で常に truthy。
  // ただし内部 effect (= popup 閉じる等) は本来の open prop と同じ意味付けで使うため、 別名で持つ。
  const uiSnap = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const open = !!uiSnap.overlays.drawer

  const sessions = sessionsSnap.sessions
  const activeId = sessionsSnap.activeId
  const agents = sessionsSnap.agents
  const sessionActivity = sessionsSnap.sessionActivity
  const unreadDone = sessionsSnap.unreadDone
  const loading = ephem.loading

  // 並び順: 「最終活動時刻」 降順、 未活動は created_at fallback (= useSessionActivity から移送)
  const sortedSessions = useMemo(
    () => [...sessions].sort((a, b) => {
      const ta = (sessionActivity[a.id]?.ts) || ((a.created_at || 0) * 1000)
      const tb = (sessionActivity[b.id]?.ts) || ((b.created_at || 0) * 1000)
      return tb - ta
    }),
    [sessions, sessionActivity]
  )

  // sessionBadges: AppShell の useSessionBadges が持つ副作用 (= POST seen / loading→flip /
  // localStorage 永続化 / boot settle) は AppShell 側で実行され続けるため、 ここでは派生のみ。
  const sids = useMemo(() => sortedSessions.map(s => s.id), [sortedSessions])
  const sessionBadges = useMemo(
    () => deriveSessionBadges({ sids, activeSid: activeId, messages, loading, unreadDone }).sessionBadges,
    [sids, activeId, messages, loading, unreadDone]
  )

  // 各種 callback (= 旧 AppShell からの props を内蔵化)
  const onClose = useCallback(() => setOverlay('drawer', false), [])
  const onSelect = useCallback((sid) => {
    storeSetActiveId(sid)
    // markAsSeen 等価 (= 旧 selectSession の即時赤丸消し、 AppShell useSessionBadges の
    // 150ms debounce useEffect より先に sync で落とす)
    const cur = getSessionsSnapshot().unreadDone
    if (cur[sid]) clearUnreadDone(sid)
  }, [])
  const onCreate = useCallback((agentId, accountId) => createSession(agentId, accountId), [])
  const onRename = useCallback((id, title) => renameSession(id, title), [])
  const onSetNotifyMode = useCallback((id, mode) => setNotifyMode(id, mode), [])
  const onDelete = useCallback((sid) => setOverlay('confirmDelete', sid), [])

  // Push 状態を本 component で直接 hook (= usePushSubscription)。 onCloseMenu は SessionDrawer
  // の global メニューを閉じる callback を渡す。 mountEffects 未指定 (= default false) で
  // 副作用 listener は AppEffects.jsx 側 1 instance に集約 (= J-2、 state/push.js singleton store
  // 経由で state を共有)、 本 instance は subscribe + toggle 呼出のみ。
  const [globalMenuOpen, setGlobalMenuOpen] = useState(false)  // ヘッダ ⋯ の総合メニュー
  const {
    pushEnabled, pushBroken, pushBusy, pushAvailable, handleTogglePush,
  } = usePushSubscription({ onCloseMenu: () => setGlobalMenuOpen(false) })
  const onTogglePush = handleTogglePush

  const [agentPicker, setAgentPicker] = useState(false) // + ボタン押下後の agent 選択メニュー
  const [accounts, setAccounts] = useState([])
  // accounts fetch の失敗状態 (= F-40)。 null = まだ試してない / 'loading' / 'error' / 'ok'。
  // 失敗時に retry ボタンを出し、 30 秒経過したら自動 1 回 retry する。
  const [accountsStatus, setAccountsStatus] = useState(null)
  const [menuFor, setMenuFor] = useState(null)          // ⋯ メニュー出してる session_id
  const [menuFlipUp, setMenuFlipUp] = useState(false)   // 画面下端なら上方向に展開
  const [renameFor, setRenameFor] = useState(null)      // リネーム inline 編集中の session_id
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef(null)
  const [resetBusy, setResetBusy] = useState(false)
  const globalMenuRef = useRef(null)
  const isLastSession = sessions.length <= 1
  // リセット (= SW を新版に差し替え + cache 全消し + reload)。
  // PWA 化すると Safari の cache クリア UI に届かなくなるための救済。
  // localStorage / IndexedDB / 通知許可は触らない (= 状態は保持)。
  // 注: registration.unregister() は紐づく PushSubscription を無効化する (W3C 仕様)。
  // 過去にこれを呼んでいたため backend に古い endpoint が大量に残った。 update() で
  // 新版 SW を install (= sw.js の skipWaiting + clients.claim で即時反映) して、
  // 既存 PushSubscription は維持する。
  const handleReset = async () => {
    setResetBusy(true)
    try {
      // 1. Cache Storage を全削除 (= 新 sw.js の fetch ハンドラが管理する shell キャッシュを一掃)。
      if (typeof caches !== 'undefined') {
        const keys = await caches.keys()
        await Promise.all(keys.map(k => caches.delete(k).catch(() => {})))
      }
      // 2. 新 sw.js を取得し、 install → activate が完了するまで待つ (= 待たずに reload すると
      //    古い SW のままリロードして「効かない」 race があった)。 unregister はしない
      //    (= PushSubscription を維持、 update() で新版に差し替える)。 最大 5s で打ち切り。
      if ('serviceWorker' in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations()
        await Promise.all(regs.map(async (r) => {
          try {
            await r.update()
            const incoming = r.installing || r.waiting
            if (incoming && incoming.state !== 'activated') {
              await new Promise((resolve) => {
                const done = setTimeout(resolve, 5000)
                incoming.addEventListener('statechange', () => {
                  if (incoming.state === 'activated') { clearTimeout(done); resolve() }
                })
              })
            }
          } catch { /* ignore */ }
        }))
      }
    } catch { /* ignore */ }
    // 3. cache-bust クエリ付きでハードリロード (= navigation を必ず新規リクエスト化)。
    //    新 SW の network-first (cache:'reload') と合わさって最新 index.html → 最新 assets を取る。
    const url = new URL(window.location.href)
    url.searchParams.set('_r', String(Date.now()))
    window.location.replace(url.toString())
  }
  // global popup に出す項目があるか (= ⋯ ボタン自体の表示条件)。
  // リセットは常時あるので、 ⋯ ボタンは常に表示される。
  const hasGlobalMenuItems = true

  useEffect(() => {
    if (renameFor && renameInputRef.current) {
      renameInputRef.current.focus()
      renameInputRef.current.select()
    }
  }, [renameFor])

  // ドロワー閉じる時にメニュー類もクリア
  useEffect(() => {
    if (!open) {
      setAgentPicker(false)
      setMenuFor(null)
      setRenameFor(null)
      setGlobalMenuOpen(false)
    }
  }, [open])

  // 総合メニュー外クリックで閉じる (= F-29 集約)
  useOutsideClick(globalMenuRef, () => setGlobalMenuOpen(false), { enabled: globalMenuOpen })

  const [pickedAgent, setPickedAgent] = useState(null)

  // 新規会話ダイアログを開いた時にアカウント候補を取得 (= /accounts、 通常 personal 1 つ
  // しか無ければ選択肢自体をスキップして agent → 即作成のフロー)。
  // F-40: 失敗時は error 状態を残し、 ユーザに retry ボタンを出す。 同時に 30 秒経過で
  // 1 回だけ自動 retry を試みる (= 一時的な network 切れを救う)。
  // useCallback で参照固定 → useEffect deps に安全に入れられる。
  const fetchAccounts = useCallback((signal) => {
    setAccountsStatus('loading')
    return apiFetch('/accounts', signal ? { signal } : undefined)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(a => {
        if (signal?.aborted) return
        setAccounts(Array.isArray(a) ? a : [])
        setAccountsStatus('ok')
      })
      .catch(e => {
        if (e?.name === 'AbortError') return
        setAccounts([])
        setAccountsStatus('error')
      })
  }, [])
  useEffect(() => {
    if (!agentPicker) return undefined
    // 初回 (= 未試行) だけここで fetch する。 error からの再試行は (a) 30 秒 timer or
    // (b) ユーザの再試行ボタン (= picker UI) で別経路から呼ぶ。
    if (accountsStatus !== null) return undefined
    const controller = new AbortController()
    fetchAccounts(controller.signal)
    return () => controller.abort()
    // deps は agentPicker のみ。 accountsStatus を入れると fetchAccounts 内の
    // setAccountsStatus('loading') でこの effect が再実行され、 cleanup の abort() が fetch
    // 自身を中断 → status が 'loading' で固定し「アカウント取得中…」 から進めなくなる
    // (= 2026-06-22 実機で発覚した abort race)。 fetch トリガーは picker が開いた瞬間で十分。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentPicker])
  // 失敗から 30 秒経ったら自動 retry を 1 回だけ。 連続失敗時は手動 retry に委ねる。
  useEffect(() => {
    if (accountsStatus !== 'error' || !agentPicker) return undefined
    const id = setTimeout(() => {
      const controller = new AbortController()
      fetchAccounts(controller.signal)
    }, 30000)
    return () => clearTimeout(id)
  }, [accountsStatus, agentPicker, fetchAccounts])

  const handleAgentPick = (agentId) => {
    // account 選択を省いて即作成するのは「fetch 完了済 (= 'ok') かつ候補 0/1 件」 の時だけ。
    // loading / 未試行 (null) / error / 複数候補は picker 画面に進める。 これにより、 fetch が
    // まだ完了してない状態で agent をタップした時に accounts=[] を「候補 0 件」 と誤判定して
    // 即作成してしまう race を防ぐ (= account が複数あるのに選択が出ない原因だった。 agent が
    // 1 つだと開いた直後にタップするので特に起きやすい)。 picker 進入後の自動判定は下の useEffect。
    if (accountsStatus === 'ok' && accounts.length <= 1) {
      handleCreate(agentId, null)
      return
    }
    setPickedAgent(agentId)
  }
  const handleCreate = (agentId, accountId) => {
    setAgentPicker(false)
    setPickedAgent(null)
    onCreate(agentId, accountId)
    onClose()
  }
  // picker 画面に進んだ後 (= loading 中にタップした) で accounts fetch が完了し、 候補が
  // 0/1 件だった場合は account 選択を出さず自動で作成する (= race 救済)。 候補が複数なら
  // 何もせず picker のアカウント一覧を見せる。
  useEffect(() => {
    if (pickedAgent !== null && accountsStatus === 'ok' && accounts.length <= 1) {
      handleCreate(pickedAgent, null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedAgent, accountsStatus, accounts.length])

  const handleSelect = (sid) => {
    if (renameFor) return // リネーム中は切替させない
    onSelect(sid)
    onClose()
  }

  const startRename = (sid, currentTitle) => {
    setMenuFor(null)
    setRenameFor(sid)
    setRenameValue(currentTitle || '')
  }

  const commitRename = () => {
    if (renameFor) {
      const t = renameValue.trim()
      if (t) onRename(renameFor, t)
    }
    setRenameFor(null)
  }

  // フォークタブ (= parent_id を持つ) を親の直下にインデント表示する (= C 案)。 兄弟内の
  // 並びは渡された順 (= created_at 降順) を保つ。 親が消えてる孤児はトップレベル扱い。
  // F-38: sessions が変わった時だけ tree を組み直す (= 再 render 毎の object 構築を回避)。
  const orderedSessions = useMemo(() => {
    const idSet = new Set(sortedSessions.map(s => s.id))
    const childrenByParent = {}
    for (const s of sortedSessions) {
      const key = (s.parent_id && idSet.has(s.parent_id)) ? s.parent_id : '__root__'
      if (!childrenByParent[key]) childrenByParent[key] = []
      childrenByParent[key].push(s)
    }
    const result = []
    const walkTree = (list, depth) => {
      for (const s of list) {
        result.push({ session: s, depth })
        if (childrenByParent[s.id]) walkTree(childrenByParent[s.id], depth + 1)
      }
    }
    walkTree(childrenByParent['__root__'] || [], 0)
    return result
  }, [sortedSessions])

  return (
    <>
      {open && <div className="drawer-overlay" onClick={onClose} />}
      <aside className={`drawer ${open ? 'open' : ''}`} data-testid="session-drawer">
        <div className="drawer-header">
          <span className="drawer-title">会話</span>
          <div className="drawer-header-actions" ref={globalMenuRef}>
            {hasGlobalMenuItems && (
              <button
                className="drawer-global-menu"
                onClick={() => setGlobalMenuOpen(prev => !prev)}
                aria-label="設定"
                title="設定"
              >
                ⋯
              </button>
            )}
            <button className="drawer-close" onClick={onClose} aria-label="閉じる">×</button>
            {globalMenuOpen && hasGlobalMenuItems && (
              <div className="drawer-global-popup" onClick={e => e.stopPropagation()}>
                {pushAvailable && onTogglePush && (
                  <button
                    onClick={() => { setGlobalMenuOpen(false); onTogglePush() }}
                    disabled={pushBusy}
                  >
                    {pushEnabled
                      ? '🔔 通知 ON (タップで無効化)'
                      : pushBroken
                        ? '⚠ 通知が失効しています (タップで再有効化)'
                        : '🔕 通知 OFF (タップで有効化)'}
                  </button>
                )}
                <button
                  onClick={() => { setGlobalMenuOpen(false); handleReset() }}
                  disabled={resetBusy}
                  title="最新コードに更新 (履歴・通知許可は保持)"
                >
                  ↺ アプリを更新
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="drawer-create">
          {!agentPicker ? (
            <button className="drawer-new" onClick={() => setAgentPicker(true)} data-testid="new-session-button">
              + 新規会話
            </button>
          ) : pickedAgent === null ? (
            <div className="agent-picker">
              <div className="agent-picker-label">agent を選択:</div>
              {agents.map(a => (
                <button
                  key={a.id}
                  className="agent-picker-item"
                  onClick={() => handleAgentPick(a.id)}
                >
                  {a.display_name}
                </button>
              ))}
              <button className="agent-picker-cancel" onClick={() => setAgentPicker(false)}>
                キャンセル
              </button>
            </div>
          ) : (
            <div className="agent-picker">
              <div className="agent-picker-label">アカウントを選択:</div>
              {(accountsStatus === 'loading' || accountsStatus === null) && (
                <div className="agent-picker-loading">アカウント取得中…</div>
              )}
              {accountsStatus === 'error' && (
                <div className="agent-picker-error">
                  <span>アカウント一覧を取得できませんでした</span>
                  <button
                    className="agent-picker-retry"
                    onClick={() => {
                      const controller = new AbortController()
                      fetchAccounts(controller.signal)
                    }}
                    disabled={accountsStatus === 'loading'}
                  >
                    {accountsStatus === 'loading' ? '取得中…' : '再試行'}
                  </button>
                </div>
              )}
              {accounts.map(acc => (
                <button
                  key={acc.id}
                  className="agent-picker-item"
                  onClick={() => handleCreate(pickedAgent, acc.id)}
                >
                  {acc.display_name}
                </button>
              ))}
              {accountsStatus === 'error' && (
                <button
                  className="agent-picker-item"
                  onClick={() => handleCreate(pickedAgent, null)}
                  title="アカウント指定なしで作成 (= backend が default を選ぶ)"
                >
                  既定アカウントで作成
                </button>
              )}
              <button className="agent-picker-cancel" onClick={() => setPickedAgent(null)}>
                戻る
              </button>
            </div>
          )}
        </div>

        <div className="drawer-list">
          {sessions.length === 0 && (
            <div className="drawer-empty">会話がありません。 上の「+ 新規会話」 から作成してください。</div>
          )}
          {orderedSessions.map(({ session: s, depth }) => {
            const badge = sessionBadges[s.id]
            const isActive = s.id === activeId
            const isMenuOpen = menuFor === s.id
            const isRenaming = renameFor === s.id
            const isFork = depth > 0
            return (
              <div
                key={s.id}
                className={`drawer-item ${isActive ? 'active' : ''} ${isFork ? 'fork' : ''}`}
                style={depth > 0 ? { paddingLeft: `${depth * 16}px` } : undefined}
                data-testid="session-list-item"
                data-cpc-sid={s.id}
                data-cpc-active={isActive ? '1' : '0'}
              >
                {isRenaming ? (
                  <input
                    ref={renameInputRef}
                    className="drawer-rename-input"
                    value={renameValue}
                    onChange={e => setRenameValue(e.target.value)}
                    onBlur={commitRename}
                    onKeyDown={e => {
                      if (e.key === 'Enter') commitRename()
                      else if (e.key === 'Escape') setRenameFor(null)
                    }}
                    data-testid="session-rename-input"
                  />
                ) : (
                  <button
                    className="drawer-item-main"
                    onClick={() => handleSelect(s.id)}
                    data-testid="session-list-item-select"
                  >
                    {isFork && <span className="drawer-item-fork-mark" title="フォーク">⑂</span>}
                    <span className="drawer-item-title">{s.title}</span>
                    {badge && <span className={`tab-badge ${badge.kind}`}>{badge.label}</span>}
                  </button>
                )}

                {!isRenaming && (
                  <button
                    className="drawer-item-menu"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (isMenuOpen) {
                        setMenuFor(null)
                        return
                      }
                      // 画面下端に近い場合は上方向に展開
                      const rect = e.currentTarget.getBoundingClientRect()
                      const spaceBelow = window.innerHeight - rect.bottom
                      setMenuFlipUp(spaceBelow < MENU_FLIP_UP_THRESHOLD_PX)
                      setMenuFor(s.id)
                    }}
                    aria-label="メニュー"
                  >
                    ⋯
                  </button>
                )}

                {isMenuOpen && (
                  <div
                    className={`drawer-item-popup ${menuFlipUp ? 'flip-up' : ''}`}
                    onClick={e => e.stopPropagation()}
                  >
                    <button onClick={() => startRename(s.id, s.title)}>リネーム</button>
                    {onSetNotifyMode && (
                      <>
                        <div className="drawer-popup-sep" />
                        <div className="drawer-popup-label">通知</div>
                        {[
                          ['both', '🔔 音 + バナー'],
                          ['banner', '🔕 バナーのみ'],
                          ['off', '⛔ オフ'],
                        ].map(([mode, label]) => {
                          const cur = s.notify_mode || 'both'
                          return (
                            <button
                              key={mode}
                              className={`drawer-popup-radio ${cur === mode ? 'on' : ''}`}
                              onClick={() => { onSetNotifyMode(s.id, mode); setMenuFor(null) }}
                            >
                              <span className="drawer-popup-check">{cur === mode ? '✓' : ''}</span>
                              {label}
                            </button>
                          )
                        })}
                        <div className="drawer-popup-sep" />
                      </>
                    )}
                    <button
                      className="danger"
                      disabled={isLastSession}
                      onClick={() => {
                        if (isLastSession) return
                        setMenuFor(null)
                        onDelete(s.id)
                      }}
                      title={isLastSession ? '最後の 1 個は削除できません' : ''}
                    >
                      {isLastSession ? '削除 (最後の 1 個)' : '削除'}
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </aside>
    </>
  )
}
