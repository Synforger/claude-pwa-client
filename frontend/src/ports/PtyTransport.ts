// PTY WebSocket (= /ws/pty/{sid}) の port interface。
// 実装: transport/ws-pty.ts (= Phase 5)。
// 関連 ADR: ADR-013 heartbeat 25s + timeout 60s + bytes 直渡し主経路。
// 関連 contract: contracts/schema/ws-channels.yaml § pty。

/** PTY frame: 主経路は binary (= xterm.js writeUtf8 直渡し)、 副次経路として decoded text も渡す。 */
export type PtyDataFrame = {
  kind: 'data'
  /** PTY stdout の raw bytes (= UTF-8 multi-byte boundary 保持のため Uint8Array)。 */
  bytes: Uint8Array
  /** decoder で stream=true デコードした text (= ANSI escape boundary で部分切断ありうる)。 */
  text: string
}

/** PTY control frame: heartbeat (= pong)、 exit、 error 等。 ws-channels.yaml と一致。 */
export type PtyControlFrame = {
  kind: 'control'
  data: { type: 'pong'; ts: number } | { type: 'exit' | 'error'; message?: string }
}

export type PtyFrame = PtyDataFrame | PtyControlFrame

export type PtyFrameHandler = (frame: PtyFrame) => void

/** subscriber が返す cleanup 関数。 */
export type Unsubscribe = () => void

export interface PtyTransport {
  /** sid 単位の接続を取得 (= 同 sid は idempotent、 既存接続を返す)。 listener を add する。 */
  connect(sid: string, handler: PtyFrameHandler): Unsubscribe

  /** stdin bytes を送信 (= ユーザキーボード入力、 UTF-8 sequence)。 */
  sendBytes(sid: string, bytes: Uint8Array): void

  /** terminal resize (= rows/cols、 control frame text)。 */
  resize(sid: string, rows: number, cols: number): void

  /** 接続切断 (= unmount / 明示 stop)。 heartbeat も停止。 */
  disconnect(sid: string): void

  /** デバッグ用: sid ごとの現在状態 (= ws-channels.yaml lifecycle と一致)。 */
  stateOf(sid: string): 'idle' | 'connecting' | 'open' | 'degraded' | 'reconnecting' | 'closed'
}
