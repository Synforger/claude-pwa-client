// 入力欄 + ⋯ アクションメニュー + 送信/停止ボタン。 App.jsx から切り出した
// プレゼンテーショナルコンポーネント (= 状態とハンドラは props で受ける)。
// terminal 表示中は App 側で描画しない (= activeViewMode のガードは呼び出し側)。
//
// 打鍵中の text は親 App の input dict に毎打鍵書き戻さず、 ChatInput 内部 (= textRef +
// localText state) で抱える (= 1 文字打つたびに App 全体が再 render する jank を解消、
// 2026-06-04 改修)。 親への flush は (a) タブ切替 (= activeSid 変化) と (b) 送信時 のみ。
// 永続化 (localStorage) と sendMessage 経路は flush 後の input dict を参照するので、 ユーザ
// 体感では従来と同じ。 強制リロード時に未 flush の打鍵途中文字は失われる、 これは draft 保存
// しない明示挙動。
import React, { useEffect, useRef, useState } from 'react'

// streaming flush で App が再 render しても、 ChatInput の props が参照同値なら shallow
// equal で skip させる (= 打鍵 jank 対策、 2026-06-22)。 App 側で callback を useCallback、
// 空の currentAttachments を共通 sentinel に揃えてあるので memo が効く。
function ChatInputInner({
  activeSid,
  activeSession,
  input,
  setInput,
  inputDisabled,
  fileInputRef,
  onFileSelect,
  menuRef,
  menuOpen,
  setMenuOpen,
  onOpenTree,
  activeViewMode,
  onToggleView,
  onEndSession,
  showStopButton,
  onStop,
  onSend,
  currentAttachments,
  sendFailedText,
  onSendFailedConsumed,
  stopUnavailable,
  onStopRecovered,
}) {
  // 表示は controlled、 親 input dict ではなく内部 state で更新する。
  const [localText, setLocalText] = useState('')
  // 「ここまでに親に flush 済の sid」 を覚えておき、 activeSid が切り替わった時に前タブの
  // localText を親に書き戻す (= 別タブで戻ってきても draft が残る)。
  const prevSidRef = useRef(null)
  // 親 input dict 最新値の ref。 useEffect の deps で input を持つと打鍵中に effect が走るので、
  // ref で読みつつ deps は activeSid だけにする。
  // F-37: render 中の直接代入は React の純粋 render 規約違反 (= StrictMode 二重 render や
  // 将来の concurrent 機能で挙動が壊れうる)。 input が変わった時の effect で同期する。
  const inputRef = useRef(input)
  useEffect(() => { inputRef.current = input }, [input])

  useEffect(() => {
    const prevSid = prevSidRef.current
    if (prevSid && prevSid !== activeSid) {
      // 別タブへ移る前に、 今まで内部で持ってた打鍵途中を親 input dict に書き戻す。
      const text = localText
      setInput(prev => (prev[prevSid] === text ? prev : { ...prev, [prevSid]: text }))
    }
    // 新タブの初期値を親から取り直す。
    setLocalText(activeSid ? (inputRef.current[activeSid] || '') : '')
    prevSidRef.current = activeSid
    // localText は依存に入れない (= 打鍵のたびに effect が走るのを避ける)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSid, setInput])

  // F-36: useChatStream から「送信失敗で text を返す」 通知を受けたら localText に戻す。
  // 親が sendFailedText を null に戻すまで 1 回だけ apply (= 同 text で連続失敗の race 回避)。
  useEffect(() => {
    if (typeof sendFailedText === 'string') {
      setLocalText(prev => (prev ? prev : sendFailedText))
      onSendFailedConsumed?.()
    }
  }, [sendFailedText, onSendFailedConsumed])

  // F-16: stop が WS 切断で届かなかった時、 useChatStream が背後で復活 polling して
  // 再送を試みる。 ChatInput 側は disable + tooltip で「接続待ち」 を可視化。 復活したら
  // 親が stopUnavailable を false に戻す。
  useEffect(() => {
    if (stopUnavailable && !showStopButton) onStopRecovered?.()
  }, [stopUnavailable, showStopButton, onStopRecovered])

  const handleSend = () => {
    if (!activeSid) return
    // 送信時は textOverride を渡して App→useChatStream の sendMessage に直接届ける。
    // 同時に親 input dict もクリアして次の永続化 (= 500ms debounce) で空になる。
    const text = localText
    setLocalText('')
    setInput(prev => (prev[activeSid] ? { ...prev, [activeSid]: '' } : prev))
    onSend(text)
  }

  const inputAreaRef = useRef(null)
  // 自分の実高さを CSS variable に流す: FilePreviewModal の overlay が下端を ChatInput 上端で
  // 止めるのに使う (= 固定 80px だと送信ボタン + safe-area で足りずプレビューが被る、 実測値で
  // 確実に避ける)。 textarea の rows 変化 / safe-area 変化に追従するため ResizeObserver。
  useEffect(() => {
    const el = inputAreaRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const set = () => {
      document.documentElement.style.setProperty('--chat-input-h', `${el.offsetHeight}px`)
    }
    set()
    const ro = new ResizeObserver(set)
    ro.observe(el)
    return () => { ro.disconnect() }
  }, [])

  return (
    <div className="inputarea" ref={inputAreaRef}>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,text/*,.py,.js,.ts,.jsx,.tsx,.md,.json,.css,.html,.yaml,.yml,.toml,.sh"
        multiple
        style={{ display: 'none' }}
        onChange={onFileSelect}
      />
      <textarea
        value={localText}
        onChange={e => setLocalText(e.target.value)}
        onKeyDown={(e) => {
          // デスクトップ (= 物理キーボード + マウス) のみ Enter を送信に倒す。
          // モバイル (タッチ専用) は Enter = 改行のまま、 送信は明示ボタンのみ
          // (= 音声入力 / IME 変換中の暴発を避ける)。 判定は `pointer: fine` メディア
          // クエリで物理ポインタの有無を見る (UA 文字列より頑健、 iPad Magic Keyboard 等の
          // 例外ケースも自然に拾える)。 Shift+Enter / 日本語 IME 変換中は常に改行。
          if (e.key !== 'Enter') return
          if (e.shiftKey || e.nativeEvent.isComposing) return
          if (!window.matchMedia || !window.matchMedia('(pointer: fine)').matches) return
          if (inputDisabled || !activeSid) return
          e.preventDefault()
          handleSend()
        }}
        placeholder={activeSession ? 'メッセージを入力...' : '左の ☰ から会話を作成してください'}
        rows={2}
        disabled={inputDisabled}
        data-testid="chat-input"
      />
      <div className="buttons" ref={menuRef}>
        {menuOpen && (
          <div className="action-menu">
            <button onClick={() => { fileInputRef.current?.click(); setMenuOpen(false) }} className="menu-item">
              ファイル添付
            </button>
            <button onClick={() => { onOpenTree(); setMenuOpen(false) }} className="menu-item">
              ファイルツリー
            </button>
            <button
              onClick={() => { onToggleView(); setMenuOpen(false) }}
              className="menu-item"
              disabled={!activeSession}
              data-testid="view-toggle"
            >
              {activeViewMode === 'terminal' ? '💬 チャットで表示' : '⌨ ターミナルで表示'}
            </button>
            <button
              onClick={() => { setMenuOpen(false); onEndSession() }}
              className="menu-item end"
              disabled={!activeSession}
            >
              セッション終了
            </button>
          </div>
        )}
        <button
          onClick={() => setMenuOpen(prev => !prev)}
          className={`more ${menuOpen ? 'active' : ''}`}
          aria-label="メニュー"
          data-testid="chat-menu-toggle"
        >
          ⋯
        </button>
        {showStopButton ? (
          <button
            onClick={onStop}
            disabled={stopUnavailable}
            title={stopUnavailable ? '接続復帰待ち (再送中)' : '停止'}
            className={`stop ${stopUnavailable ? 'pending' : ''}`}
            aria-label="停止"
            data-testid="chat-stop-button"
          >■</button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!activeSession || (!localText.trim() && currentAttachments.length === 0)}
            className="send"
            aria-label="送信"
            data-testid="chat-send-button"
          >
            送信
          </button>
        )}
      </div>
    </div>
  )
}

const ChatInput = React.memo(ChatInputInner)
export default ChatInput
