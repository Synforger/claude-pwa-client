import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'
import { LS_JSONL_OFFSET } from '../../constants.js'
import { apiFetch } from '../../utils/api.js'
import { lsGet, lsSet } from '../../utils/storage.js'
import { generateId } from '../../utils/id.js'
import { useStreamBuffer } from './useStreamBuffer.js'
import { processStreamEvent } from './processStreamEvent.js'
import { reconcileUserMessage } from './reconcileUserMessage.js'
import { useConnectionStatus } from '../../transport/connectionStatus.js'
import { sseTransport } from '../../transport/sse.ts'

// session_id → JSONL byte offset の永続化。 タブ切替 / リロードを跨いで「ここまで読んだ」 を
// 保持し、 新規 EventSource 接続時に `?from=<sid>:<offset>,...` で渡す (= F-15)。 backend は
// offset 以降の完全行だけ流すので、 初回 replay の重さがほぼゼロになる。
//
// F-15 以前は 1 sid あたり 1 EventSource を張り、 activeSid 切替で接続を張り直していた
// (= 1-3s 待ち)。 F-15 で `/jsonl/stream/all` に統合し、 接続自体を活性 sid 切替で**閉じない**
// ので、 タブ切替時に活性 sid の最新 message が即時表示される。
function loadOffsets() {
  const parsed = lsGet(LS_JSONL_OFFSET)
  return parsed && typeof parsed === 'object' ? parsed : {}
}

function persistOffsets(offsets) {
  lsSet(LS_JSONL_OFFSET, offsets)
}

// W2 Phase F-4 (= 2026-06-29): ChatPanel.jsx 内 useChatStream の戻り値 (= endSession /
// stopMessage 関数) を、 features/dialogs/ConfirmEndDialog.jsx / ConfirmStopDialog.jsx から
// 直接呼べる経路として module-level に export する。 hook 内部 closure (= sid / setMessages /
// offsetRef 等) に access するため、 useChatStream mount 時に下記 ref を実装で wire し、
// unmount で nullify する (= 旧 endSession / stopMessage の useCallback 戻り値そのものを再利用、
// ロジック改変ゼロ)。 ChatPanel.jsx は本 phase で該当 dialog block を退役するので、
// hook 戻り値経由の endSession / stopMessage 参照は features/dialogs 経由に統一される。
let _endSessionImpl = null
let _stopMessageImpl = null
export function endSession() { return _endSessionImpl?.() }
export function stopMessage() { return _stopMessageImpl?.() }

// (= 旧 buildFromQuery / apiUrl 直書きは transport/sse.ts singleton に移管済、 v2 では本 file は
//   subscribe するだけで offset / ?from query 組立を持たない)。

// chat 1 セッションの送受信・状態管理を束ねる公開フック (= TUI / JSONL 版)。
//
// 旧 SDK + proxy 版を置き換えたもの。 App.jsx 側のインターフェース
// (loading / sendMessage / stopMessage / apiKeySource / sendAnswer / fetchLatest /
//  endSession / setLoading / optimisticRef) は維持し、 App.jsx はほぼ無改修で動く。
//
// 受信: 常時 /jsonl/stream を EventSource で購読 (= claude が書く JSONL を backend が tail)。
//       event は processStreamEvent + useStreamBuffer で旧 chat と同じ message state に組む。
// 送信: POST /pty/{sid}/send (= tmux send-keys、 text+Enter / Escape)。
// 表示資産 (MessageItem / scroll / localStorage) は App.jsx 側のものをそのまま使う。
export function useChatStream({
  activeSession,
  setMessages,
  input, setInput,
  attachments, clearAttachments,
  scrollToBottom, isAtBottomRef,
  sendStopIntent,
  // F-36: 送信失敗時に呼ばれる callback (= ChatInput.localText 復元用、 ChatInput が内部
  // state で打鍵を抱えるようになって setInput dict 経由では届かないケースの保険)。
  // 旧来の setInput 経路は二重保険として残す。
  onSendFailed,
  // F-16: stopMessage が WS 切断中 (= sendStopIntent silent fail) で発火した時の通知。
  // ChatInput 側 (= W2-D) で disabled + tooltip 表示に使う。 backend に HTTP POST stop
  // endpoint が無い (= overview.py で「HTTP POST 経由は廃止」) ので fallback として
  // WS 再接続を待ってリトライする必要があるが、 frontend 側だけでは完遂困難なため、
  // ここでは通知 + 楽観的に再試行スケジュールだけ立てる (= partial 対応、 backend 側
  // endpoint 追加は別途)。
  onStopUnavailable,
}) {
  const sid = activeSession?.id || null
  const [loading, setLoading] = useState({})
  const [apiKeySource, setApiKeySource] = useState({})
  // 送信/停止 直後の楽観意図。 `{[sid]: {want:'busy'|'idle', seen}}`。
  //   - 送信時 want='busy' (停止ボタンを出す)、 停止時 want='idle' (送信ボタンを出す)。
  // backend 権威 busy がこの意図に追いつくまで、 逆向きの古い snapshot による上書きを保留する
  // (= applyOverviewSnapshot が確定的にクリア)。 送信/停止を対称に扱い、 どちらも 1 操作で
  // ボタンが確実に切り替わる。 旧来の 1500ms タイマー窓は撤去済。
  const optimisticRef = useRef({})
  // session ごとの最後に受信した byte offset。 タブ切替で再接続する時、 ここから差分だけ
  // 取り直すことで全 replay を避ける (= 切替を軽く + localStorage 即復元と併用)。
  // localStorage に永続化することで、 アプリ再起動 / リロードを跨いでも継続。
  const offsetRef = useRef(loadOffsets())
  const offsetPersistTimerRef = useRef(null)
  // sid → 直近の sendMessage が仕掛けた SEND_TIMEOUT timer id。 SSE で対応する uuid 付き
  // user_message が来たら handleEventRef 側で clearTimeout する (= 2026-06-24 退行 fix、
  // 解除経路が抜けてて 15s 後に failBubble が誤発火 → input に text が戻る + loading 状態
  // 破壊で他タブにも波及していた)。
  const sendTimersRef = useRef({})
  // EventSource 再接続トリガ。 endSession (/clear) で新 claude_sid に切り替わるとき、
  // backend の JSONL 解決を新 sid に向けるためここを +1 して useEffect を再実行させる。
  const [reconnectKey, setReconnectKey] = useState(0)

  const buffer = useStreamBuffer({ setMessages })

  const eventDeps = {
    setMessages,
    setApiKeySource,
    cancelAndFlush: buffer.cancelAndFlush,
    scheduleFlush: buffer.scheduleFlush,
    bufFor: buffer.bufFor,
  }

  // F-45 / 自分が backend と疎通可能か (= 全 SSE / WS 集約)。 stop 押下時の fallback 判定に
  // 使う (F-16)。 1 本でも open ならオンライン。 不明 (= 起動直後) は true 扱い。
  const isOnline = useConnectionStatus()
  const isOnlineRef = useRef(isOnline)

  // event ハンドラを ref に逃がして、 EventSource は sid 変更時だけ張り直す。
  // F-07: ref 同期は paint 前に確定させたいので useLayoutEffect。 ref 代入の useEffect は
  // commit 後に走る = 「最初の paint 直後に届いた event」 で 1 frame 前の closure を読む
  // 微小窓があった。 useLayoutEffect なら commit と同 frame で必ず最新が入る。
  const handleEventRef = useRef(null)
  // loading は backend busy 追随で高頻度更新される。 sendMessage の deps に直入れすると毎回
  // コールバックが再生成されて ChatInput 等が再 render するため、 ref 経由で読む。
  const loadingRef = useRef(loading)
  useLayoutEffect(() => { loadingRef.current = loading }, [loading])
  useLayoutEffect(() => { isOnlineRef.current = isOnline }, [isOnline])
  useLayoutEffect(() => {
    handleEventRef.current = (curSid, event) => {
      if (event.type === 'user_message') {
        buffer.cancelAndFlush(curSid)
        setMessages(prev => {
          const cur = prev[curSid] || []
          const next = reconcileUserMessage(cur, event.text || '', event.uuid)
          return next === cur ? prev : { ...prev, [curSid]: next }
        })
        // 対応する SEND_TIMEOUT watcher を解除 (= server jsonl に user 行が積まれた = 送信成功)。
        // 解除し忘れると 15s 後に failBubble が誤発火して input に text が戻る + loading 状態
        // を破壊する (= 2026-06-24 退行 fix の核)。
        const t = sendTimersRef.current[curSid]
        if (t) {
          clearTimeout(t)
          delete sendTimersRef.current[curSid]
        }
        return
      }
      // 注: ここでは loading (= 停止ボタンの真値) を一切触らない。 loading は backend 権威 busy
      // を overview SSE で受ける useSessionsOverview の**単一ソース**で駆動する。 チャット SSE は
      // メッセージ描画専用 (= assistant/result の取りこぼし・replay で停止ボタンが stuck する
      // dual-driver 構造を根本的に排除)。 result event は processStreamEvent 内で streaming
      // フラグ (=「推論中…」 表示) を落とすのには引き続き使う (ボタン状態とは別軸)。
      try {
        processStreamEvent(eventDeps, curSid, event)
      } catch (e) {
        // 1 event の失敗で stream は落とさないが、 silent skip だと「表示が壊れた」
        // のに grep する手がかりが無くなる。 console.warn で event type + error を残す
        // (= 2026-06-22 silent-failure sweep)。
         
        console.warn('[chat] event handler threw, dropping this event:', event?.type, e)
      }
    }
  })

  // F-15: 全 sid を 1 接続で受ける統合 EventSource。 activeSid 変化では再接続しない
  // (= 接続コスト + 1-3s 待ち を消す)。 接続再構築は明示 trigger (= endSession→reconnectKey
  // 経由) のみ。 event 振分は event.sid を真値とし、 setMessages は event.sid 別キーに対して
  // 行う (= activeSession 以外の sid も backend が publish 次第 frontend に反映される、
  // useStreamBuffer も Map 化済で sid 並走 OK)。
  // F-15 統合 SSE は v2 では transport/sse.ts (= sseTransport singleton) が所有する。
  // offset 管理 + EventSource 再接続 + sid 別 dispatch は本 transport が担当、 ここは
  // subscribe するだけ (= ADR-010 ports/transport 経由、 ADR-012 corr_id envelope global required).
  // 旧 cpc_jsonl_offset (= v1 offsetRef + persistOffsets) は v2 transport/sse.ts 内で
  // cpc_v2_jsonl_offsets に移管済、 useChatStream 内の offsetRef は当面残置 (= 後続 v2 state 連携
  // 深化で state/transport.js の offsets に統合予定、 現状は dead だが無害)。
  useEffect(() => {
    const unsub = sseTransport.subscribe(event => {
      const evSid = event.sid || sid
      if (!evSid) return
      handleEventRef.current?.(evSid, event)
    })
    return () => { unsub() }
  }, [reconnectKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // iOS PWA バックグラウンドからの復帰時に EventSource を強制再接続 (= 2026-06-22)。
  // iOS は PWA を background にすると socket を suspend し、 戻った時に「OPEN のまま実は死んでる」
  // 状態になる事がある。 onerror が発火しないので reconnectKey bump 経路に乗らない →
  // 新着が来ない = チャットが少し前で止まる症状の主因。 visibility が visible に変わったら
  // 確実に新接続を取り直して、 offsetRef ベースで未受信 event を replay 取得する。
  // + 2026-06-23: hidden 遷移時に offsetRef を同期で localStorage に flush する。 旧実装は
  // event 受信ごとに 1s debounce していたため、 bg 突入が debounce 中だと offset が
  // 旧値のまま落ちる → 復帰時の `?from=` が古い offset を渡して replay 始点ズレ →
  // 「最新メッセージが見えない / 古いものに戻る」 事象の主因の 1 つ。
  useEffect(() => {
    const flushOffsets = () => {
      if (offsetPersistTimerRef.current) {
        clearTimeout(offsetPersistTimerRef.current)
        offsetPersistTimerRef.current = null
      }
      try { persistOffsets(offsetRef.current) } catch { /* ignore */ }
    }
    const onVis = () => {
      if (document.visibilityState === 'hidden') {
        flushOffsets()
      } else if (document.visibilityState === 'visible') {
        setReconnectKey(k => k + 1)
      }
    }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('pagehide', flushOffsets)
    window.addEventListener('beforeunload', flushOffsets)
    window.addEventListener('freeze', flushOffsets)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('pagehide', flushOffsets)
      window.removeEventListener('beforeunload', flushOffsets)
      window.removeEventListener('freeze', flushOffsets)
    }
  }, [])

  // activeSid 切替時の buffer reset。 接続自体は閉じない (= F-15 で /all 経路に統合)、
  // ただし activeSid の useStreamBuffer の表示 buffer は新しいタブ用に初期化する。
  useEffect(() => {
    if (!sid) return undefined
    buffer.resetBuf(sid)
    return () => {
      buffer.cancelAndFlush(sid)
    }
  }, [sid]) // eslint-disable-line react-hooks/exhaustive-deps

  // chat UI の操作 → tmux session にキー送信 (= 出力 SSE と分離)。
  const sendToPty = useCallback(async (targetSid, body) => {
    try {
      await apiFetch(`/pty/${encodeURIComponent(targetSid)}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch { /* 送信失敗は握りつぶす (= 次操作で復帰) */ }
  }, [])

  const sendMessage = useCallback(async (textOverride) => {
    if (!sid) return
    // ChatInput が内部 state で打鍵を抱えるようになったので、 送信時には override (= 直近の
    // localText) を優先する。 タブ切替で flush 済の draft を後追い送信するケース等は引数なしで
    // 呼ばれて従来通り input dict を読む。
    const text = (typeof textOverride === 'string' ? textOverride : (input[sid] || '')).trim()
    const files = attachments[sid] || []
    if (!text && files.length === 0) return
    // loading 中 (= 前 turn 未完 or 楽観 busy が stuck) の送信は silent skip しない。
    // 旧実装は ChatInput が text を localText からクリアした後に sendMessage が return →
    // 入力テキストが消失する事故 (2026-06-22)。 入力欄に書き戻し + 1 行 alert で
    // 「届かなかった」 を明示する。 stop ボタンが立ってる状況なので、 ユーザは停止 → 再送が
    // 自然な経路。
    if (loadingRef.current[sid]) {
      setInput(prev => ({ ...prev, [sid]: prev[sid] || text }))
      try { onSendFailed?.(sid, text) } catch { /* ignore consumer error */ }
      alert('前のターンが処理中です。 停止ボタンで止めてから再送してください。')
      return
    }
    const sendText = text
    setInput(prev => ({ ...prev, [sid]: '' }))
    setLoading(prev => ({ ...prev, [sid]: true }))
    optimisticRef.current[sid] = { want: 'busy', startedAt: Date.now() }
    // 楽観 bubble の id は固定して保持。 後段の SEND_TIMEOUT watcher と HTTP fail 経路の
    // 両方が同じ bubble を狙い撃ちで sendFailed 化 / pop できるようにする
    // (= reconcileUserMessage 側で confirm 時に id を popped から継承する設計と整合)。
    const optimisticUserId = generateId()
    // 楽観 user bubble + 空 streaming agent bubble を即挿入。 添付があれば user bubble に
    // 表示用の imageUrls / fileNames を載せる (= MessageItem の user-block 経路で render)。
    // imageUrls は ObjectURL なのでアプリリロード後は消えるが、 当該セッション中は見える。
    setMessages(prev => {
      const cur = prev[sid] || []
      const imageUrls = files.filter(f => f.url).map(f => f.url)
      const imageRefs = files.filter(f => f.imageId).map(f => f.imageId)
      const fileNames = files.map(f => f.file.name)
      return {
        ...prev,
        [sid]: [
          ...cur,
          {
            id: optimisticUserId,
            role: 'user',
            text,
            optimistic: true,
            // imageUrls = ObjectURL (= 一時表示用、 リロードで失効)、
            // imageRefs = IndexedDB key (= 永続、 リロード後 AttachedImages が復元)
            imageUrls: imageUrls.length > 0 ? imageUrls : undefined,
            imageRefs: imageRefs.length > 0 ? imageRefs : undefined,
            fileNames: fileNames.length > 0 ? fileNames : undefined,
          },
          { id: generateId(), role: 'agent', text: '', tools: [], streaming: true },
        ],
      }
    })
    if (isAtBottomRef) isAtBottomRef.current = true
    scrollToBottom()
    // SEND_TIMEOUT_MS: HTTP 200 が返ったのに claude が JSONL に user 行を書かない silent fail
    // 用の保険 (= 2026-06-24 server-of-truth 純化、 即時 HTTP fail は既存 !result.ok / !uploadOk
    // 経路で別途処理されるのでここの timeout は届かない)。 通常 200-500ms で来るので 15s は
    // 余裕、 backend kickstart 直後や busy 時の遅延も吸収する。 timeout 発火時は対象 bubble
    // を id で findIndex して sendFailed 化 (= ephemeral、 localStorage 側 filter で除外)、
    // input に text を戻して再送可能にする。
    const SEND_TIMEOUT_MS = 15000
    const failBubble = (extraInput) => {
      setMessages(prev => {
        const arr = prev[sid] || []
        const idx = arr.findIndex(m => m && m.id === optimisticUserId)
        if (idx < 0) return prev // 既に reconcile で消費済 (= 正常確定)
        const target = arr[idx]
        if (!target.optimistic || target.sendFailed) return prev
        const next = [...arr]
        next[idx] = { ...target, sendFailed: true }
        while (next.length) {
          const tail = next[next.length - 1]
          if (tail.role === 'agent' && tail.streaming && !tail.text && !tail.thinking && (!tail.tools || !tail.tools.length)) {
            next.pop()
          } else break
        }
        return { ...prev, [sid]: next }
      })
      setLoading(prev => ({ ...prev, [sid]: false }))
      optimisticRef.current[sid] = null
      if (extraInput) setInput(prev => ({ ...prev, [sid]: prev[sid] || text }))
      try { onSendFailed?.(sid, text) } catch { /* ignore consumer error */ }
    }
    // 旧 timer が残ってたら解除 (= 連投時の watcher 重複防止、 sid 1 本に最新 1 個だけ持つ)
    if (sendTimersRef.current[sid]) clearTimeout(sendTimersRef.current[sid])
    const failTimerId = setTimeout(() => {
      delete sendTimersRef.current[sid]
      failBubble(true)
    }, SEND_TIMEOUT_MS)
    sendTimersRef.current[sid] = failTimerId
    if (files.length > 0) {
      // multipart: backend がファイルを uploads/tmp に保存して path を本文に追記して
      // tmux に送る (= claude が Read tool で読む)。
      const form = new FormData()
      form.append('text', sendText)
      for (const item of files) {
        form.append('files', item.file)
      }
      let uploadOk = true
      let uploadErrDetail = ''
      try {
        const r = await apiFetch(`/pty/${encodeURIComponent(sid)}/send-with-files`, {
          method: 'POST',
          body: form,
        })
        if (!r || !r.ok) {
          uploadOk = false
          uploadErrDetail = `HTTP ${r?.status ?? '???'}`
          try { uploadErrDetail = (await r.json())?.detail || uploadErrDetail } catch { /* ignore parse */ }
        }
      } catch (e) {
        uploadOk = false
        uploadErrDetail = e?.message || String(e)
      }
      if (uploadOk) {
        clearAttachments(sid)
      } else {
        // 添付送信失敗時の UI 復旧 (= 2026-06-22 lifecycle sweep + 2026-06-24 共通化):
        // 旧実装は alert だけで楽観 user bubble + 空 streaming agent bubble + loading=true が
        // 残ったまま → 「…」 永続表示 + 送信ボタン無効化 stuck で reload しないと回復不能だった。
        // 共通 failBubble へ集約 (= 2026-06-24)、 SEND_TIMEOUT watcher も解除する。
        clearTimeout(failTimerId)
        delete sendTimersRef.current[sid]
        failBubble(true)
        alert(`添付ファイル送信に失敗: ${uploadErrDetail}`)
      }
    } else {
      // 送信本文 (text + Enter): backend が JSONL に user 行が +1 されるかを最大 2s 監視 →
      // なければ 1 回自動再送 → さらに 1.5s 待つ → ok/ng を返す。 ng (= claude TUI に届かなかった)
      // 時は input に text を戻して再送可能にし、 楽観 user bubble に「届かなかった」 マークを付ける。
      let result
      try {
        const r = await apiFetch(`/pty/${encodeURIComponent(sid)}/send`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: sendText, enter: true }),
        })
        result = r ? await r.json().catch(() => ({ ok: false })) : { ok: false }
      } catch {
        result = { ok: false }
      }
      if (!result.ok) {
        // HTTP 即時 fail = 共通 failBubble へ集約 (= 2026-06-24)、 SEND_TIMEOUT watcher も解除。
        // 旧来の setInput 経路は failBubble 内に内包済 (= F-36 ChatInput.localText の onSendFailed
        // callback も同関数内で呼ぶ)。
        clearTimeout(failTimerId)
        delete sendTimersRef.current[sid]
        failBubble(true)
      }
    }
  }, [sid, input, attachments, setInput, setMessages, clearAttachments, scrollToBottom, isAtBottomRef, setLoading, onSendFailed])

  // F-16: WS 切断中に押された stopMessage を最大 N 回 / 一定 backoff で再試行する。
  // backend に HTTP POST stop fallback endpoint が無い (= overview.py で「HTTP POST 経由は
  // 廃止」 と明記) ため、 WS 復活を polling で待つしかない。 復活した瞬間に sendStopIntent
  // を再送 + onStopUnavailable を解除する形 (= partial 対応、 endpoint 追加は backend 課題)。
  const stopRetryTimerRef = useRef(null)
  const scheduleStopRetry = useCallback((targetSid) => {
    if (stopRetryTimerRef.current) clearTimeout(stopRetryTimerRef.current)
    let attempts = 0
    const tick = () => {
      stopRetryTimerRef.current = null
      attempts += 1
      if (isOnlineRef.current && sendStopIntent) {
        try { sendStopIntent(targetSid) } catch { /* ignore */ }
        return
      }
      if (attempts >= 10) return // 約 30s (= 3s * 10) で諦め、 ユーザ操作待ち
      stopRetryTimerRef.current = setTimeout(tick, 3000)
    }
    stopRetryTimerRef.current = setTimeout(tick, 3000)
  }, [sendStopIntent])

  // unmount 時にタイマー解放
  useEffect(() => () => {
    if (stopRetryTimerRef.current) clearTimeout(stopRetryTimerRef.current)
  }, [])

  const stopMessageCb = useCallback(async () => {
    if (!sid) return
    // 並行で 2 つ:
    //   (a) PTY に Esc を送る = claude TUI の中断 (= 物理停止)
    //   (b) /views/ws で Stop 意思を backend に送る = StreamState.user_stopped=true で
    //       busy 強制 false。 WS 経由で TCP 保証付き (= 旧 HTTP POST 経路の到達失敗 race を
    //       根本治療)。 全 client が overview SSE で即時に「停止」 を観測。
    // F-16: WS 切断中なら sendStopIntent は silent fail する (= useViewsWs 内で readyState !==
    // OPEN なら何もしない設計)。 全接続が落ちているならユーザに「stop 反映できなかった」 を
    // 通知 + WS 復活を待って再送するスケジュールを立てる。 (a) の PTY Esc は HTTP なので
    // online なら届くため、 物理停止だけは成功する可能性が高い。
    sendToPty(sid, { key: 'Escape' }).catch(() => {})
    sendStopIntent?.(sid)
    if (!isOnlineRef.current) {
      try { onStopUnavailable?.(sid) } catch { /* ignore consumer error */ }
      scheduleStopRetry(sid)
    }
    setLoading(prev => ({ ...prev, [sid]: false }))
    // 停止意図を楽観保持 (= want:'idle')。 backend が user_stopped→busy=false を返すまで、
    // 古い busy=true snapshot に上書きされて停止ボタンへ戻るのを防ぐ (= 1 押下で送信へ)。
    optimisticRef.current[sid] = { want: 'idle', startedAt: Date.now() }
    // 末尾の streaming bubble (= 「推論中…」 表示の元) を停止扱いに固定。
    setMessages(prev => {
      const arr = prev[sid] || []
      if (arr.length === 0) return prev
      const last = arr[arr.length - 1]
      if (!last?.streaming) return prev
      return { ...prev, [sid]: [...arr.slice(0, -1), { ...last, streaming: false }] }
    })
  }, [sid, sendToPty, sendStopIntent, setMessages, onStopUnavailable, scheduleStopRetry])

  const sendAnswer = useCallback(async (targetSid, tool_use_id, answer, isFree = false, optionCount = 0) => {
    // AskUserQuestion の回答を tmux 経由で claude TUI に送る。
    // 回答 = turn 再開の合図なので、 送信 (sendMessage) と同じく loading を立てて
    // 送信ボタン → 停止ボタンに切り替える (= 楽観フラグも置く、 backend busy が追いつくまで保留)。
    setLoading(prev => ({ ...prev, [targetSid]: true }))
    optimisticRef.current[targetSid] = { want: 'busy', startedAt: Date.now() }
    if (isFree) {
      // 自由記述: claude TUI は選択肢リストの末尾に "Type something"(自由入力) を持つ。
      // フォーカスは先頭選択肢にあるので、 素のテキストを送ると先頭が選ばれてしまう
      // (= 自由記述が届かない原因)。 先に "Type something"(= 選択肢数+1 番) を選んで
      // 自由入力モードに入れてから、 テキスト + Enter を送る。
      const typeNum = String((optionCount || 0) + 1)
      await sendToPty(targetSid, { text: typeNum, enter: false })
      await new Promise(r => setTimeout(r, 150))
      await sendToPty(targetSid, { text: answer, enter: true })
    } else {
      await sendToPty(targetSid, { text: answer, enter: true })
    }
    setMessages(prev => {
      const cur = prev[targetSid] || []
      const msgs = cur.map(m =>
        m.askUserQuestion?.tool_use_id === tool_use_id
          ? { ...m, askUserQuestion: { ...m.askUserQuestion, answered: true, selectedAnswer: answer } }
          : m,
      )
      return { ...prev, [targetSid]: msgs }
    })
  }, [sendToPty, setMessages, setLoading])

  const endSessionCb = useCallback(async () => {
    if (!sid) return
    // セッション終了 = claude プロセスを kill + 新規 spawn する (= /clear と違って
    // プロセスメモリも完全解放、 ターミナル描画の重さ / CPU 高負荷の根本対策)。
    // 新 claude_sid に切り替わるが backend の SessionStart hook で bindings が更新されるので
    // PWA タブはそのまま続けて使える。 旧 JSONL は disk に残るので --resume で復元可能。
    try {
      const r = await apiFetch(`/sessions/${encodeURIComponent(sid)}/restart`, { method: 'POST' })
      if (!r || !r.ok) {
        // セッション終了は backend の kill + spawn 経路、 ここが落ちると claude プロセスが
        // 残ったまま UI だけ「終わったつもり」 になる事故源。 ユーザに見せる
        // (= 2026-06-22 silent-failure sweep)。
        let detail = `HTTP ${r?.status ?? '???'}`
        try { detail = (await r.json())?.detail || detail } catch { /* ignore parse */ }
        alert(`セッション終了に失敗: ${detail}`)
      }
    } catch (e) {
      alert(`セッション終了に失敗: ${e?.message || e}`)
    }
    // 停止フラグを解除 (= 新プロセスで turn を再開できる状態にする)
    // UI 上のセッション区切りを messages に挿入 (= MessageItem の system/kind=session_end 経路)
    setMessages(prev => ({
      ...prev,
      [sid]: [
        ...(prev[sid] || []),
        { id: generateId(), role: 'system', kind: 'session_end', ts: Date.now() },
      ],
    }))
    // 旧 JSONL を読み続けないよう offset をクリア (= 新 claude_sid に切り替わったら新 JSONL の
    // 末尾近くから tail 開始させる)。 SessionStart hook で binding 更新まで少し待つ。
    delete offsetRef.current[sid]
    persistOffsets(offsetRef.current)
    setTimeout(() => {
      setReconnectKey(k => k + 1)
    }, 2000)
  }, [sid, setMessages])

  // 常時 tail + EventSource 自動再接続なので明示 fetch は不要。 scroll だけ最新へ寄せる。
  const fetchLatest = useCallback(() => {
    scrollToBottom()
  }, [scrollToBottom])

  // W2 Phase F-4 (= 2026-06-29): module-level endSession / stopMessage 経路 (= features/dialogs
  // 経由の onConfirm) に最新の hook closure 実装を wire する。 ChatPanel.jsx は本 hook を 1 経路
  // のみ mount するので、 single-writer 前提で wire/unwire を素朴に行う。 unmount で nullify、
  // call 側は `?.()` で no-op に。
  useEffect(() => {
    _endSessionImpl = endSessionCb
    _stopMessageImpl = stopMessageCb
    return () => {
      if (_endSessionImpl === endSessionCb) _endSessionImpl = null
      if (_stopMessageImpl === stopMessageCb) _stopMessageImpl = null
    }
  }, [endSessionCb, stopMessageCb])

  return {
    loading,
    setLoading,
    apiKeySource,
    sendMessage,
    sendAnswer,
    stopMessage: stopMessageCb,
    fetchLatest,
    endSession: endSessionCb,
    optimisticRef,
  }
}
