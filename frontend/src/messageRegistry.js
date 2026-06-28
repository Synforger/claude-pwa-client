// system_* / attachment / task_notification 等のイベント種別ごとに、
// SSE event payload から message オブジェクトを組み立てる純粋関数 + 表示コンポーネント
// (= Render) を 1 箇所に集約した registry。
//
// 旧 processStreamEvent は 6 ブロックそれぞれで cancelAndFlush → uuid 既知判定 → setMessages
// → slice(-MAX) のパターンを手書き重複していた。 各 kind の差分は「event の何を読むか」
// だけだったので、 ここに `kind → fromEvent(event)` の table を置き、 共通処理は
// processStreamEvent 側の appendSystemMessage helper に集約する (= F-04 / F-05)。
//
// F-04 consumer (= 2026-06-21): MessageItem.jsx 側も「system + kind 毎に if 分岐 →
// 専用 component を返す」 という巨大 switch を持っていた。 Render field を足して
// `<Entry.Render msg={msg} />` 1 行で済むよう一本化する (= 新 system kind は registry に
// fromEvent + Render を 1 ペア足すだけで配線完結)。 session_end は SDK 由来の build 経路を
// 持たない (= MessageItem 内で role=system + kind=session_end として直接挿入される) ので
// fromEvent: null。
//
// 設計指針:
// - fromEvent は **event 由来の field のみ**を返す pure function。 `id` (= generateId) や
//   `role: 'system'` / `kind` / `uuid` は共通処理側で付与する (= 重複削減)。
// - 全 kind に共通する shape は `{ role: 'system', id, kind, uuid, ...extra }`。
// - Render は `{ msg }` を受ける関数 component。 msg.role / msg.kind は前提として既に判定
//   済みなので、 component 内で再判定する必要なし。
//
// 追加時の手順:
//   1) processStreamEvent で扱いたい新 event.type に対して fromEvent を書く (= 不要なら null)
//   2) Render に表示 component を書く
//   3) (build 経路がある時のみ) `appendSystemMessage(setMessages, sid, kind, fromEvent(event))`
//      を呼ぶ 1 行で配線完了
import TaskNotification from './features/tasks/TaskNotification.jsx'
import {
  CompactBanner,
  SessionEndBanner,
  ApiErrorCard,
  AttachmentCard,
  HookErrorCard,
  SystemNoteCard,
} from './features/chat/SystemMessages.jsx'

const registry = {
  // 会話圧縮タイミング。 SDK からは事後通知しか来ない (= 結果カードのみ)。
  compact: {
    fromEvent: (event) => {
      const meta = event.compactMetadata || {}
      return {
        trigger: meta.trigger || null,
        preTokens: typeof meta.preTokens === 'number' ? meta.preTokens : null,
        postTokens: typeof meta.postTokens === 'number' ? meta.postTokens : null,
        durationMs: typeof meta.durationMs === 'number' ? meta.durationMs : null,
      }
    },
    Render: CompactBanner,
  },
  // セッション終了の区切りバナー。 SDK event 由来ではなく、 backend tail が JSONL 末尾で
  // session 切れを検知したら role=system + kind=session_end を直接挿入する (= fromEvent 不要)。
  session_end: {
    fromEvent: null,
    Render: SessionEndBanner,
  },
  // Anthropic API エラー (= 529 overloaded / 401 / network down 等)。 赤い inline カード。
  api_error: {
    fromEvent: (event) => ({
      formatted: event.formatted || 'API error',
      status: event.status ?? null,
      requestId: event.requestId || null,
      isNetworkDown: !!event.isNetworkDown,
      retryInMs: typeof event.retryInMs === 'number' ? event.retryInMs : null,
      retryAttempt: typeof event.retryAttempt === 'number' ? event.retryAttempt : null,
      timestamp: event.timestamp || null,
    }),
    Render: ApiErrorCard,
  },
  // hooks 実行が non-blocking で失敗した記録。 黄色 inline 警告。
  hook_error: {
    fromEvent: (event) => ({
      hookName: event.hookName || '',
      hookEvent: event.hookEvent || '',
      exitCode: event.exitCode ?? null,
      stderr: event.stderr || '',
      stdout: event.stdout || '',
      command: event.command || '',
      durationMs: event.durationMs ?? null,
    }),
    Render: HookErrorCard,
  },
  // local_command (/model 等) / scheduled_task_fire (/loop wakeup) の発火記録。
  system_note: {
    fromEvent: (event) => ({
      subtype: event.subtype || '',
      content: event.content || '',
    }),
    Render: SystemNoteCard,
  },
  // queued_command / task_reminder / skill_listing 他を折りたたみカードで表示。
  attachment: {
    fromEvent: (event) => ({
      subtype: event.subtype || 'unknown',
      attachment: event.attachment || {},
    }),
    Render: AttachmentCard,
  },
  // background task (= Monitor / バックグラウンド Bash) の完了通知。 中央寄せ system カード。
  task: {
    fromEvent: (event) => ({
      summary: event.summary || null,
      status: event.status || null,
      outputFile: event.outputFile || null,
      exitCode: typeof event.exitCode === 'number' ? event.exitCode : null,
    }),
    Render: TaskNotification,
  },
}

export function getMessageEntry(kind) {
  return registry[kind] || null
}

export function listMessageKinds() {
  return Object.keys(registry)
}

export default registry
