// Views WebSocket (= /views/ws) の port interface。
// 「今どの sid を見てるか」 を全端末に sync するための短命 channel。
// 実装: transport/ws-views.ts (= Phase 5)。
// 関連 ADR: ADR-013 visible 中のみ接続 / heartbeat なし。

export interface ViewsTransport {
  /** visible 中なら接続 + 即現在の activeSid を送信、 hidden なら no-op。 */
  start(): void

  /** 接続を close (= bg / unmount 経路)。 */
  stop(): void

  /** activeSid 変化時に即送信。 null = 全タブ非表示 (= 全 sid 視認なし)。 */
  setActiveSid(sid: string | null): void

  /** stop intent を sid 指定で送信 (= features/terminal の stop ボタン押下時)。 */
  sendStopIntent(sid: string): void

  readonly state: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'
}
