"""claude が ~/.claude/projects/<cwd-hash>/<session_id>.jsonl に書く構造化ログの 1 行を、
frontend の processStreamEvent.js が期待する event 形式に変換する純粋関数。

JSONL と旧 SDK-SSE event はほぼ同型 (= message.role + content[] + tool_result + usage)
なので変換は最小限。 差分だけ吸収する:
    - AskUserQuestion: JSONL は tool_use(name="AskUserQuestion") で表現 → ask_user_question
      event を別途 emit (= processStreamEvent 側は assistant の tool から除外して別 bubble)
    - result: JSONL に独立 result 行が無い → assistant の stop_reason=="end_turn" のとき
      usage / model を載せた result event を合成 (= MetaLine の token / model 表示用)
    - user 素プロンプト: JSONL は content=string (= ユーザ発言) → user_message event に変換
    - subagent 出力: isSidechain=True の行は親 chat に混ぜない (= skip)
    - slash command の内部表現: `/clear` 等を tmux 経由で送ると claude は
      `<command-name>/clear</command-name>` 形式の XML を user 行として JSONL に書く。
      これはユーザ発話ではなく claude 内部表現なので chat には出さない (= skip)。
"""
from __future__ import annotations

import re

# claude が JSONL の user 行に書く harness 内部表現を検出するための regex (= 公開)。
# 該当行はユーザ発話ではないので chat には出さない + busy 判定でも除外する
# (jsonl_routes._is_user_prompt が import して使う)。
# 既知パターン (= 2026-05-24 実機 dump で確認):
#   <command-name>/clear</command-name>           ← slash command 起動
#   <command-message>clear</command-message>      ← 上記の続き
#   <command-args>sonnet</command-args>           ← 上記の続き (引数)
#   <local-command-stdout>...ANSI...</local-command-stdout>  ← slash command の応答
#   <local-command-stderr>...</local-command-stderr>         ← 上記の error 版 (将来用)
# 後発の `<local-command-*>` を catch-all で潰すため、 prefix で広めに wildcard 一致。
HARNESS_XML_RE = re.compile(
    r"^\s*<(command-name|command-message|command-args|local-command-[a-z-]+)\b"
)
# 後方互換 (旧 module-private 名)。 新規参照は HARNESS_XML_RE を使う。
_HARNESS_XML_RE = HARNESS_XML_RE


# harness が background task (= Monitor / バックグラウンド Bash 等) の完了時に user 行として
# JSONL に書く `<task-notification>...` ブロック。 これはユーザの発話ではなく harness 通知なので、
# user バブルで右寄せ表示せず専用の system カード (task_notification event) に変換する。
# ただし busy 判定 (jsonl_session_status.is_user_prompt) では除外しない: 完了通知を受けて claude が
# 実際に proactive turn を走らせるため、 その間 busy=True で停止可能なのが公式の正しい挙動。
_TASK_NOTIFICATION_RE = re.compile(r"^\s*<task-notification\b")

# claude TUI が「停止ボタン押下」「Esc」 等で turn を中断した時に user 行として書く marker。
# 公式 claude CLI が string content / list 内 text どちらでも書きうる固定文字列。 これはユーザの
# 発話ではなく「中断が完了した」 という終端 marker。 busy 判定でユーザ発話扱いすると claude プロセスは
# 既に止まっていて応答 (= 終端 stop_reason 行) が来ないため、 busy=True が永遠に落ちず停止ボタンが
# 送信ボタンに戻らない (2026-06-04 真因確定、 これまでの単一権威化 / probe 観測でも消えなかった元凶)。
# 後方 / 前方の空白だけ許容、 大小無視。
INTERRUPT_USER_RE = re.compile(r"^\s*\[request interrupted by user\]\s*$", re.IGNORECASE)


def _extract_tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1).strip() if m else None


def parse_task_notification(text: str) -> dict | None:
    """`<task-notification>` user 行を構造化 dict に parse する。 該当しなければ None。

    抽出: taskId / toolUseId / outputFile / status / summary / exitCode。
    exitCode は summary 末尾の `(exit code N)` から拾う (= 失敗時の赤表示用)。
    """
    if not _TASK_NOTIFICATION_RE.match(text):
        return None
    summary = _extract_tag(text, "summary")
    exit_code: int | None = None
    if summary:
        m = re.search(r"exit code (\d+)", summary)
        if m:
            exit_code = int(m.group(1))
    return {
        "taskId": _extract_tag(text, "task-id"),
        "toolUseId": _extract_tag(text, "tool-use-id"),
        "outputFile": _extract_tag(text, "output-file"),
        "status": _extract_tag(text, "status"),
        "summary": summary,
        "exitCode": exit_code,
    }


def jsonl_line_to_events(line: dict) -> list[dict]:
    """JSONL 1 行 (parsed dict) を 0 個以上の processStreamEvent event に変換する。

    対象外 (= type が assistant / user 以外、 sidechain、 空) は空リストを返す。
    """
    if not isinstance(line, dict):
        return []
    if line.get("isSidechain"):
        return []
    if line.get("isMeta"):
        # harness が注入するメタメッセージ (= tool call の malformed retry 指示 / caveat 等)。
        # ユーザー発言でも claude の応答でもないので chat には出さない。
        return []
    line_type = line.get("type")
    if line_type == "assistant":
        return _assistant_events(line)
    if line_type == "user":
        return _user_events(line)
    if line_type == "system":
        return _system_events(line)
    if line_type == "attachment":
        return _attachment_events(line)
    if line_type == "queue-operation":
        return _queue_operation_events(line)
    if line_type == "ai-title":
        return [{
            "type": "ai_title",
            "title": line.get("aiTitle") or "",
        }]
    if line_type == "mode":
        return [{
            "type": "mode",
            "mode": line.get("mode") or "",
        }]
    if line_type == "permission-mode":
        return [{
            "type": "permission_mode",
            "permissionMode": line.get("permissionMode") or "",
        }]
    return []


def _attachment_events(line: dict) -> list[dict]:
    """`attachment` 行のうちユーザー文脈に関わるもの (= queued_command / task_reminder /
    skill_listing) を折りたたみカードとして event 化。 deferred_tools_delta / date_change は
    内部メタなので chat には出さない。
    """
    a = line.get("attachment") or {}
    sub = a.get("type")
    if sub in ("queued_command", "task_reminder", "skill_listing"):
        return [{
            "type": "attachment",
            "uuid": line.get("uuid") or line.get("parentUuid"),
            "subtype": sub,
            "attachment": a,
        }]
    return []


def _queue_operation_events(line: dict) -> list[dict]:
    """`queue-operation` の enqueue 行は内容に `<task-notification>` を含むことがある
    (= ScheduleWakeup / Cron / Monitor 等の完了通知)。 これは既存 user 行経由でも来るが、
    Fable 5 で queue-operation 経由のみで来るケースがあるので拾う。
    """
    if line.get("operation") != "enqueue":
        return []
    content = line.get("content") or ""
    task = parse_task_notification(content) if isinstance(content, str) else None
    if task is None:
        return []
    return [{
        "type": "task_notification",
        "uuid": line.get("uuid") or f"queue-op-{line.get('timestamp')}",
        **task,
    }]


def subagent_line_to_events(line: dict) -> list[dict]:
    """サブエージェント (= Task で起動した子 agent、 isSidechain=True) の 1 行を表示用 event に
    変換する。 親 chat 用の jsonl_line_to_events は sidechain を skip するが、 専用ビュー
    (= subagents_routes) では中身を見せたいので sidechain チェックを外して同じ
    assistant / user / system 変換を通す。"""
    if not isinstance(line, dict):
        return []
    if line.get("isMeta"):
        return []
    line_type = line.get("type")
    if line_type == "assistant":
        return _assistant_events(line)
    if line_type == "user":
        return _user_events(line)
    if line_type == "system":
        return _system_events(line)
    return []


def _system_events(line: dict) -> list[dict]:
    """system 行のうち frontend にとって意味があるものだけを event 化する。

    対応 subtype:
    - compact_boundary: 会話圧縮の境界 → CompactBanner 用 metadata
    - api_error: Anthropic API 側のエラー (= 529 overloaded / 401 / network down 等)。
      ブラックボックス化させない (= 2026-06-12 確定、 Fable 5 で多発するため必須)
    - turn_duration: 1 ターンの処理時間メタ。 直近 assistant bubble に紐付け表示
    - stop_hook_summary / away_summary / scheduled_task_fire 等は chat 非表示で skip
    """
    sub = line.get("subtype")
    if sub == "compact_boundary":
        return [{
            "type": "system",
            "subtype": "compact_boundary",
            "uuid": line.get("uuid"),
            "compactMetadata": {
                "trigger": line.get("trigger"),
                "preTokens": line.get("preTokens"),
                "postTokens": line.get("postTokens"),
                "durationMs": line.get("durationMs"),
            },
        }]
    if sub == "api_error":
        err = line.get("error") or {}
        return [{
            "type": "system_error",
            "uuid": line.get("uuid"),
            "level": line.get("level") or "error",
            "formatted": err.get("formatted") or err.get("message") or "API error",
            "status": err.get("status"),
            "requestId": err.get("requestId"),
            "isNetworkDown": bool(err.get("isNetworkDown")),
            "retryInMs": line.get("retryInMs"),
            "retryAttempt": line.get("retryAttempt"),
            "timestamp": line.get("timestamp"),
        }]
    if sub == "turn_duration":
        return [{
            "type": "turn_duration",
            "uuid": line.get("uuid"),
            "parentUuid": line.get("parentUuid"),
            "durationMs": line.get("durationMs"),
            "messageCount": line.get("messageCount"),
            "timestamp": line.get("timestamp"),
        }]
    return []


def _assistant_events(line: dict) -> list[dict]:
    msg = line.get("message") or {}
    content = msg.get("content") or []
    if not isinstance(content, list):
        return []

    # claude は 1 Anthropic message を複数 JSONL 行に分けて書く (= 同 message.id で
    # tool_use ブロックを別行で出す等)。 frontend の useStreamBuffer は uuid 単位で
    # bubble を dedup / merge するので、 行固有の line uuid ではなく message.id を
    # 使うことで「同じ assistant 発言」 を 1 bubble に集約させる。
    bubble_uuid = msg.get("id") or line.get("uuid")
    events: list[dict] = [{
        "type": "assistant",
        "message": {"content": content},
        "uuid": bubble_uuid,
    }]

    # AskUserQuestion は専用 bubble 用に別 event でも出す (= assistant 側は tool から除外される)
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
            events.append({
                "type": "ask_user_question",
                "tool_use_id": block.get("id"),
                "input": block.get("input") or {},
            })

    # turn 完了時のメタ (= 直近 agent bubble に token / model を埋める)。
    # tool_use は turn 継続中 (= 次の assistant 行で続く) なので result を合成しない。
    # それ以外の確定 stop_reason (end_turn / max_tokens / refusal / pause_turn /
    # model_context_window_exceeded 等) は全部 result として送って、 MessageItem の
    # StopReasonChip / MetaLine / streaming flag を正しく落とす。
    stop_reason = msg.get("stop_reason")
    if stop_reason and stop_reason != "tool_use":
        model = msg.get("model")
        events.append({
            "type": "result",
            "usage": msg.get("usage"),
            "stop_reason": stop_reason,
            "modelUsage": {model: {}} if model else None,
            # refusal は MessageItem 側で danger chip を出させる。
            "is_error": stop_reason == "refusal",
            # 4.8 で公開化された refusal の理由詳細 (= stop_details)。 refusal 時のみ載せ、
            # MessageItem が danger chip に理由を inline 表示する。
            "stop_details": msg.get("stop_details") if stop_reason == "refusal" else None,
        })

    return events


def _user_events(line: dict) -> list[dict]:
    msg = line.get("message") or {}
    content = msg.get("content")

    # 素のプロンプト (= ユーザ発言) は content=string で来る
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return []
        # background task の完了通知は専用 system カードに変換 (= user バブルにしない)
        task = parse_task_notification(text)
        if task is not None:
            return [{"type": "task_notification", "uuid": line.get("uuid"), **task}]
        # claude TUI の slash command / stdout 内部表現は user 発話ではないので chat には出さない
        if _HARNESS_XML_RE.match(text):
            return []
        return [{"type": "user_message", "text": content, "uuid": line.get("uuid")}]

    if isinstance(content, list):
        has_tool_result = any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
        if has_tool_result:
            # 既存 tool_use に結果を紐付ける経路 (= processStreamEvent が処理)
            return [{"type": "user", "message": {"content": content}}]
        # tool_result でない array (= text block のユーザ発言) は user_message に畳む
        texts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        joined = "".join(texts).strip()
        if joined:
            return [{"type": "user_message", "text": "".join(texts), "uuid": line.get("uuid")}]

    return []
