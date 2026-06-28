// W3C Trace Context 互換の corr_id / traceparent を発行する共通 helper。
// 設計判断: ADR-012。 trace_id 32 hex の頭 8 文字を corr_id として運用、 将来 OTLP backend
// に流す path を開けておく。 OTel SDK フル採用は overkill のため自前発行のみ。
//
// 「使ってる corr_id ↔ HTTP path / status」 マップは listRecent() で開発時 inspector が読む。

interface RecentEntry { path: string; status: number; ts: number }

const recent = new Map<string, RecentEntry>()
const MAX_RECENT = 200

function hex(n: number): string {
  // crypto.randomUUID() は 32 hex + 4 dash の string、 dash を除いて 32 hex を切り出す
  return crypto.randomUUID().replace(/-/g, '').slice(0, n)
}

/** 8 hex の corr_id を発行 (= 32-bit 乱数、 W3C trace_id の頭 8 文字相当)。 */
export function newCorrId(): string {
  return hex(8)
}

/** W3C Trace Context format: "00-<32 hex trace_id>-<16 hex span_id>-01"。 全部新規発行。 */
export function newTraceparent(): string {
  const traceId = hex(32)
  const spanId = hex(16)
  return `00-${traceId}-${spanId}-01`
}

/** 既存 corr_id (= 8 hex) を埋め込んだ traceparent を作る (= 上流 corr_id を伝搬したい場合)。 */
export function traceparentFromCorrId(corrId: string): string {
  // corr_id 8 hex + 残り 24 hex で trace_id 32 hex を埋める
  const traceId = corrId.padEnd(8, '0') + hex(24)
  return `00-${traceId}-${hex(16)}-01`
}

/** corr_id ↔ {path, status, ts} を recent map に記録する (= 開発時 inspector 用)。 */
export function registerCorr(corrId: string, meta: { path: string; status: number }): void {
  recent.set(corrId, { ...meta, ts: nowMs() })
  if (recent.size > MAX_RECENT) {
    // 最古を 1 件削除 (= Map 挿入順イテレーション)
    const firstKey = recent.keys().next().value as string | undefined
    if (firstKey !== undefined) recent.delete(firstKey)
  }
}

/** 直近 corr_id を新しい順で返す (= debug inspector が叩く)。 */
export function listRecent(): Array<[string, RecentEntry]> {
  return Array.from(recent.entries()).reverse()
}

function nowMs(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? Math.floor(performance.timeOrigin + performance.now())
    : Date.now()
}
