// VITE_API_BASE が未設定 (undefined) のときだけ環境別フォールバック。
// 空文字 ('') を明示すると同一オリジン相対 (= PWA を配信したホスト) になる。
// 同一オリジン相対にしておくと http/https 両方の URL から問題なく API が叩ける。
//   - 開発時 (vite dev): localhost:8765 (= backend がローカル別ポート起動の前提)
//   - 本番 (vite build): 同一オリジン相対 (= backend が dist を配信、 .env で明示しなくても安全)
export const API_BASE =
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.PROD ? '' : 'http://localhost:8765')

export const SUPPORTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
export const MAX_MESSAGES = 200

// 「このイベントは、いま画面に居る未確定バブルより過去のものか」 を判定する許容差
// (= 2026-07-26 replay 食い潰し根治)。
//
// 背景: GET /jsonl/history は sid 表示のたびに直近 N 行を丸ごと返す (= client=射影)。
// その中の**古い** user_message / assistant が、 送信直後の楽観バブルや推論中の空
// placeholder (= どちらも client 時計の Date.now() を ts に持つ) を「対応する確定」 と
// 誤認して食い潰す事故があった (= 自分の送信が過去の発話に上書きされて消える /
// 最新の返答枠に大昔の応答が入る)。
//
// 物理: 未確定バブルを確定できるのは**その送信より後**に生まれたイベントだけ。 過去の
// イベントは過去に属する。 ただし ts は server (= jsonl 時刻) と client (= Date.now())
// の異なる時計由来なのでズレる。 数分の skew で正規の確定を弾くと逆に二重表示になる
// ため、 余裕を持たせた閾値でガードする (= 履歴 replay は通常 時間〜日 単位に古いので
// 5 分の緩衝でも確実に弾ける)。
export const REPLAY_SKEW_TOLERANCE_MS = 5 * 60 * 1000

// localStorage キー
export const LS_SESSIONS_META = 'cpc_sessions_meta'   // [{id, agent_id, title, created_at}, ...]
export const LS_ACTIVE_SESSION = 'cpc_active_session'  // 現在表示中の session_id
export const LS_MESSAGES = 'cpc_messages'              // {session_id: [...]} (LZString 圧縮)
export const LS_INPUT = 'cpc_input'                    // {session_id: 入力中文字列}
export const LS_SESSION_ACTIVITY = 'cpc_session_activity'  // {session_id: {length, ts}} ドロワー並び順用
export const LS_JSONL_OFFSET = 'cpc_jsonl_offset'      // {session_id: byte_offset} 初回 SSE replay 量を絞る
// 旧キー (マイグレーション用)
export const LS_LEGACY_ACTIVE_AGENT = 'cpc_active_agent'

// 旧 agent ID → 新 session_id (backend の session_meta.json と一致)。
// 起動時マイグレーションで cpc_messages / cpc_input / cpc_active_agent の旧キーを
// 新 session_id にリネームするのに使う。
export const LEGACY_AGENT_TO_SESSION = Object.freeze({
  agent_a: 'ses_legacy_a',
  agent_b: 'ses_legacy_b',
})
