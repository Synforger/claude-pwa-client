// Session entity 型 + 純粋ヘルパ。 React / DOM 非依存。
// backend が真値、 frontend は受信した snapshot を本型で扱う。
//
// キー命名は runtime (= state/sessions.js + backend /sessions response) と完全一致:
// session.id / session.parent_id (= Phase J-1 で state setter API も .id に統一済、 ADR-026)。

/** notify mode (= session ごとの push 通知方針)。 backend と enum 一致。 */
export type NotifyMode = 'always' | 'mentions' | 'never'

/** session の永続情報 (= backend GET /sessions の 1 entry)。 */
export interface Session {
  id: string
  title: string
  agent_id: string
  account_id?: string | null
  notify_mode?: NotifyMode
  created_at?: string
  /** fork lineage の親 id (= UI で 分岐 表示の depth 計算に使う)。 */
  parent_id?: string | null
}

/** 新規 session 作成時の入力 (= POST /sessions request body 互換)。 */
export interface NewSessionInput {
  agent_id: string
  title?: string
  account_id?: string | null
}

/** agent_id が空文字 / 空白文字を含まないかの最低限の検証 (= backend が真値だが、 送信前に弾く)。 */
export function isValidAgentId(agent_id: string | null | undefined): boolean {
  if (typeof agent_id !== 'string') return false
  if (agent_id.length === 0) return false
  // 空白 / タブ / 改行を含む agent_id は invalid
  if (/\s/.test(agent_id)) return false
  return true
}

/** sortOrder: 作成時刻降順 + id 安定化の比較関数。 */
export function compareSessionsForList(a: Session, b: Session): number {
  const ta = a.created_at || ''
  const tb = b.created_at || ''
  if (ta !== tb) return ta < tb ? 1 : -1
  return a.id.localeCompare(b.id)
}

/** fork lineage 上で a が b の祖先か (= depth 表示の入れ子判定)。 sessions list 全体を渡す。 */
export function isAncestorOf(ancestor: Session, descendant: Session, sessions: Session[]): boolean {
  const byId = new Map(sessions.map(s => [s.id, s]))
  let cur: Session | undefined = descendant
  const seen = new Set<string>()
  while (cur && cur.parent_id) {
    if (seen.has(cur.id)) return false  // cycle safety
    seen.add(cur.id)
    if (cur.parent_id === ancestor.id) return true
    cur = byId.get(cur.parent_id)
  }
  return false
}

/** fork depth (= drawer のインデント幅計算)。 0 = root、 上限 8 (= UI 都合)。 */
export function forkDepth(session: Session, sessions: Session[]): number {
  const byId = new Map(sessions.map(s => [s.id, s]))
  let depth = 0
  let cur: Session | undefined = session
  const seen = new Set<string>()
  while (cur && cur.parent_id && depth < 8) {
    if (seen.has(cur.id)) return depth
    seen.add(cur.id)
    cur = byId.get(cur.parent_id)
    if (cur) depth += 1
  }
  return depth
}
