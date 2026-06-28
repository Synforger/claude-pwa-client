// HTTP 経路の port interface。
// 全 fetch は本 interface 経由とする。 lint で `fetch(` / `new Request` 直書きを transport/ 配下以外で禁止する (= Phase 6)。
// 実装: transport/http.ts (= Phase 5)。
// 関連 ADR: ADR-012 corr_id (= W3C traceparent) header 付与 / Server-Timing 読取り。

export interface ApiFetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /** body は string (= JSON.stringify 済) / FormData / Blob / null。 dict を直接渡したい場合は jsonBody を使う。 */
  body?: BodyInit | null
  /** dict をそのまま渡すと Content-Type: application/json + JSON.stringify される糖衣。 */
  jsonBody?: unknown
  /** 既存 header に上書きマージ。 corr_id / traceparent は実装側で自動付与されるので呼び出し側で書かない。 */
  headers?: Record<string, string>
  /** 既定 10000ms、 0 で無効化。 AbortController に変換される。 */
  timeout?: number
  /** 上流 AbortSignal (= React unmount 等)。 timeout signal と any 合成される。 */
  signal?: AbortSignal
  /** 既定で実装側が new した corr_id を使う。 明示渡しで上流 trace との結合に使う。 */
  corrId?: string
}

export interface HttpClient {
  /** path は `/sessions` 等の絶対 path (= API_BASE は実装内で連結)。 必ず本関数経由とする。 */
  apiFetch(path: string, opts?: ApiFetchOptions): Promise<Response>

  /** 直近 N 件の corr_id ↔ {path, status, ts} を返す (= 開発時 inspector 用、 Phase 6 debug/ で使う)。 */
  listRecentCorrIds(): Array<[string, { path: string; status: number; ts: number }]>
}
