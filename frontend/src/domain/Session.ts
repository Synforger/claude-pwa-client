// Session entity 型 + 純粋ヘルパ。 React / DOM 非依存。
// backend が真値、 frontend は受信した snapshot を本型で扱う。

/** notify mode (= session ごとの push 通知方針)。 backend と enum 一致。 */
export type NotifyMode = 'always' | 'mentions' | 'never'

/** session の永続情報 (= backend GET /sessions の 1 entry)。 */
export interface Session {
  sid: string
  title: string
  agent_id: string
  account_id?: string | null
  notify_mode?: NotifyMode
  created_at?: string
  /** fork lineage の親 sid (= UI で 分岐 表示の depth 計算に使う)。 */
  parent_sid?: string | null
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

/** sortOrder: 作成時刻降順 + sid 安定化の比較関数。 */
export function compareSessionsForList(a: Session, b: Session): number {
  const ta = a.created_at || ''
  const tb = b.created_at || ''
  if (ta !== tb) return ta < tb ? 1 : -1
  return a.sid.localeCompare(b.sid)
}

/** fork lineage 上で a が b の祖先か (= depth 表示の入れ子判定)。 sessions list 全体を渡す。 */
export function isAncestorOf(ancestor: Session, descendant: Session, sessions: Session[]): boolean {
  const bySid = new Map(sessions.map(s => [s.sid, s]))
  let cur: Session | undefined = descendant
  const seen = new Set<string>()
  while (cur && cur.parent_sid) {
    if (seen.has(cur.sid)) return false  // cycle safety
    seen.add(cur.sid)
    if (cur.parent_sid === ancestor.sid) return true
    cur = bySid.get(cur.parent_sid)
  }
  return false
}

/** fork depth (= drawer のインデント幅計算)。 0 = root、 上限 8 (= UI 都合)。 */
export function forkDepth(session: Session, sessions: Session[]): number {
  const bySid = new Map(sessions.map(s => [s.sid, s]))
  let depth = 0
  let cur: Session | undefined = session
  const seen = new Set<string>()
  while (cur && cur.parent_sid && depth < 8) {
    if (seen.has(cur.sid)) return depth
    seen.add(cur.sid)
    cur = bySid.get(cur.parent_sid)
    if (cur) depth += 1
  }
  return depth
}
