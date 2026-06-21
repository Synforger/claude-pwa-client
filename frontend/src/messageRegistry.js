// system_* / attachment / task_notification 等のイベント種別ごとに、
// SSE event payload から message オブジェクトを組み立てる純粋関数を集約した registry。
//
// 旧 processStreamEvent は 6 ブロックそれぞれで cancelAndFlush → uuid 既知判定 → setMessages
// → slice(-MAX) のパターンを手書き重複していた。 各 kind の差分は「event の何を読むか」
// だけだったので、 ここに `kind → fromEvent(event)` の table を置き、 共通処理は
// processStreamEvent 側の appendSystemMessage helper に集約する (= F-04 / F-05)。
//
// 設計指針:
// - fromEvent は **event 由来の field のみ**を返す pure function。 `id` (= generateId) や
//   `role: 'system'` / `kind` / `uuid` は共通処理側で付与する (= 重複削減)。
// - 全 kind に共通する shape は `{ role: 'system', id, kind, uuid, ...extra }`。
// - Render 側 (= MessageItem.jsx の <CompactBanner> 等) はこの registry を参照しないが、
//   将来 components 側の switch を統合したくなった時に同じ kind 文字列を流用できる
//   (= W2-D が後追いで MessageItem を refactor する余地を残す API)。
//
// 追加時の手順:
//   1) processStreamEvent で扱いたい新 event.type に対して fromEvent を書く
//   2) `appendSystemMessage(setMessages, sid, kind, fromEvent(event))` を呼ぶ 1 行で配線完了

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
  },
  // local_command (/model 等) / scheduled_task_fire (/loop wakeup) の発火記録。
  system_note: {
    fromEvent: (event) => ({
      subtype: event.subtype || '',
      content: event.content || '',
    }),
  },
  // queued_command / task_reminder / skill_listing 他を折りたたみカードで表示。
  attachment: {
    fromEvent: (event) => ({
      subtype: event.subtype || 'unknown',
      attachment: event.attachment || {},
    }),
  },
  // background task (= Monitor / バックグラウンド Bash) の完了通知。 中央寄せ system カード。
  task: {
    fromEvent: (event) => ({
      summary: event.summary || null,
      status: event.status || null,
      outputFile: event.outputFile || null,
      exitCode: typeof event.exitCode === 'number' ? event.exitCode : null,
    }),
  },
}

export function getMessageEntry(kind) {
  return registry[kind] || null
}

export function listMessageKinds() {
  return Object.keys(registry)
}

export default registry
