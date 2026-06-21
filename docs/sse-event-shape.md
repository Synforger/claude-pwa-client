# SSE event shape (= jsonl_line_to_events ↔ processStreamEvent の中央仕様)

backend `backend/jsonl/events.py::jsonl_line_to_events` が JSONL 1 行から組み立て、 SSE で配信する event 群の wire shape を一括宣言する。 frontend `frontend/src/hooks/internal/processStreamEvent.js` がこれを type で分岐して描画する。 backend と frontend のどちらか片方だけ変更すると drift して silent な未描画になるため、 新規 event type を追加する時は **本ファイル → backend → frontend** の順で更新する。

## 共通フィールド

全 event は SSE `data:` line に 1 JSON object として乗る。 type 別の payload に加えて、 ほぼ全 event が以下を含む:

| field | 型 | 説明 |
|---|---|---|
| `type` | string | event 種別 (= 下表参照) |
| `uuid` | string? | JSONL 1 行に対応する UUID、 dedup key として使う |
| `parent_tool_use_id` | string? | subagent / Task の親 tool_use_id (= subagent stream を親 turn に紐付ける) |

## event type 一覧

### chat / assistant 系

| type | 必須 field | 説明 |
|---|---|---|
| `assistant` | `message.content[]` | assistant 1 turn の content blocks (= text / tool_use / thinking)。 frontend で streaming append |
| `user` | `message.content` | user 行の content (= text or tool_result list)。 `parent_tool_use_id` 持ちは subagent 内 |
| `user_message` | `text` | user 発話を text-only に正規化した shorthand (= UI の bubble 描画用) |
| `result` | `subtype`, `is_error?`, `total_cost_usd?` | claude session の最終 result event (= `subtype: success | error_max_turns | ...`) |
| `ask_user_question` | `question`, `options[]`, `multi`, `tool_use_id` | AskUserQuestion tool 起動時の選択肢、 frontend で AskUserQuestionBubble 描画 |

### システム / メタ系

| type | 必須 field | 説明 |
|---|---|---|
| `system` | `subtype` | system 行。 subtype = `init` (= session 開始 + cwd / model) / `compact_boundary` (= compact 実行) |
| `system_error` | `error` | api_error / 内部エラー (= ⚠️ 赤カード) |
| `system_note` | `kind`, `text` | scheduled_task_fire / local_command 等の補助通知 |
| `hook_error` | `event`, `error` | hook script 失敗 (= ⚠️ 黄カード) |
| `turn_duration` | `duration_ms` | 1 turn 所要時間 |
| `mode` | `mode` | claude TUI mode 切替 (= 通常 / plan 等) |
| `permission_mode` | `mode` | permission mode 切替 (= acceptEdits / plan / bypassPermissions) |
| `pr_link` | `url` | turn 中に言及された PR URL (= StatusBar 🔗 chip 集約用) |
| `budget` | `remaining_usd` | サブスク残予算 (= StatusBar 描画) |

### 添付 / タスク系

| type | 必須 field | 説明 |
|---|---|---|
| `attachment` | `kind`, `payload` | 添付ファイル (= 画像 / pdf 等)。 `kind` で種別、 chat に 1 行折りたたみ表示 |
| `task_notification` | `tool_name`, `task_id`, `status`, `description?` | TaskCreate / TaskUpdate 由来 task 通知。 frontend は task_id で merge して TaskNotification card 描画 |

### 接続管理

| type | 必須 field | 説明 |
|---|---|---|
| `request_id` | `request_id` | SSE 接続初回に backend が割振る connection ID (= debug 用、 frontend で log)。 jsonl 由来でなく backend route 側で injected |

## 命名規約

- type は **snake_case**、 hyphen / camelCase 禁止
- 同じ概念で複数 event 出る場合 (= `task_notification` の status 違い) は status field で分岐、 type を分けない
- 廃止 type は backend 側 1 round 削除、 frontend は次 round で対応 (= 旧 type を silently 無視する一時 fallback 経路を残さない)

## 変更時の手順

1. 本ファイルに新 type 行を追加 / 既存 type の field 追加 (= 仕様確定)
2. `backend/jsonl/events.py::jsonl_line_to_events` で emit を追加 / 修正
3. `backend/tests/integration/test_sse_event_snapshot.py` (= 後続 finding F-36 で scaffold) に snapshot 追加
4. `frontend/src/hooks/internal/processStreamEvent.js` で消費分岐を追加
5. `frontend/src/types.d.ts` の shape 宣言を更新

## 参考

- backend 実装: `backend/jsonl/events.py`
- frontend 消費: `frontend/src/hooks/internal/processStreamEvent.js`
- 関連: `docs/streams.md` (= 後続 finding F-26 で 4 SSE/WS 経路の責任分担図)
