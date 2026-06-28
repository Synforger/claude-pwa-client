"""GENERATED FILE — do not edit by hand.

Source: contracts/schema/sse-events.yaml
Generator: contracts/codegen/gen-python.py
Regenerate: cd contracts && python codegen/gen-python.py
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class UserMessageEvent(BaseModel):
    """ユーザ発話 (= claude が JSONL の user 行に書いた瞬間)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["user_message"]
    sid: str  # session id (= UI 上のタブ ID)
    uuid: str  # server 生成、 dedup key
    text: str  # ユーザ発話本文
    corr_id: str  # W3C trace_id 頭 8 文字、 log 結合用
    parentUuid: Optional[str] = None  # 親 message uuid (= fork lineage)
    content: Optional[dict[str, Any]] = None  # raw JSONL content (= tool_result 含む list / string 両対応)
    ts: Optional[int] = None  # epoch ms


class AssistantEvent(BaseModel):
    """claude 応答 (= text / thinking / tool_use ブロック含む)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["assistant"]
    sid: str
    uuid: str  # Anthropic message.id (= 同 message の delta frame 集約用)
    corr_id: str
    message: dict[str, Any]
    parentUuid: Optional[str] = None
    meta: Optional[dict[str, Any]] = None  # duration_ms 等の補助メタ


class ResultEvent(BaseModel):
    """ターン完了メタ (= usage / stop_reason / model)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["result"]
    sid: str
    uuid: Optional[str] = None  # 親 assistant bubble の uuid
    corr_id: str
    stop_reason: str  # end_turn / max_tokens / refusal / pause_turn / model_context_window_exceeded 等
    usage: Optional[dict[str, Any]] = None  # input_tokens / output_tokens / cache_*
    modelUsage: Optional[dict[str, Any]] = None  # model 名 -> usage 写像
    stop_details: Optional[dict[str, Any]] = None  # refusal 時の詳細 (= 4.8 で公開化)
    is_error: Optional[bool] = None  # stop_reason == refusal で true
    total_cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    duration_ms: Optional[int] = None


class AskUserQuestionEvent(BaseModel):
    """AskUserQuestion tool 呼び出し (= ユーザに選択肢提示)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["ask_user_question"]
    sid: str
    corr_id: str
    tool_use_id: str  # Anthropic tool_use id (= 回答時の紐付け key)
    input: dict[str, Any]  # AskUserQuestion の questions array を含む


class TaskNotificationEvent(BaseModel):
    """background task (= Monitor / バックグラウンド Bash / ScheduleWakeup / Cron) の完了通知"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["task_notification"]
    sid: str
    uuid: str
    corr_id: str
    taskId: str
    toolUseId: Optional[str] = None
    outputFile: Optional[str] = None
    status: str  # completed / failed / cancelled 等
    summary: Optional[str] = None
    exitCode: Optional[int] = None  # summary 末尾の (exit code N) から抽出


class SystemEvent(BaseModel):
    """system banner (= compact_boundary / init 等の境界情報)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["system"]
    sid: str
    uuid: Optional[str] = None
    corr_id: str
    subtype: Literal["compact_boundary", "init"]
    compactMetadata: Optional[dict[str, Any]] = None  # subtype == compact_boundary のみ
    apiKeySource: Optional[str] = None  # subtype == init のみ (= /login / ANTHROPIC_API_KEY 等)


class SystemErrorEvent(BaseModel):
    """Anthropic API error (= 529 overloaded / 401 unauthorized / network down 等)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["system_error"]
    sid: str
    uuid: Optional[str] = None
    corr_id: str
    level: Literal["info", "warn", "error"]
    formatted: str  # ユーザ向け表示文字列
    status: Optional[int] = None  # HTTP status code
    requestId: Optional[str] = None
    isNetworkDown: Optional[bool] = None
    retryInMs: Optional[int] = None
    retryAttempt: Optional[int] = None
    timestamp: Optional[str] = None


class HookErrorEvent(BaseModel):
    """claude CLI hook 実行の non-blocking 失敗記録"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["hook_error"]
    sid: str
    uuid: Optional[str] = None
    corr_id: str
    hookName: str
    hookEvent: str  # PreToolUse / PostToolUse / UserPromptSubmit 等
    toolUseID: Optional[str] = None
    exitCode: Optional[int] = None
    stderr: Optional[str] = None
    stdout: Optional[str] = None
    command: Optional[str] = None
    durationMs: Optional[int] = None
    timestamp: Optional[str] = None


class SystemNoteEvent(BaseModel):
    """slash command (/model 等) / scheduled task fire (/loop wakeup 等) の発火記録"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["system_note"]
    sid: str
    uuid: Optional[str] = None
    corr_id: str
    subtype: Literal["local_command", "scheduled_task_fire"]
    content: str
    level: Optional[Literal["info", "warn", "error"]] = None
    timestamp: Optional[str] = None


class AttachmentEvent(BaseModel):
    """ユーザ手動ファイル添付 (= user メッセージに紐付く file 添付)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["attachment"]
    sid: str
    uuid: str
    corr_id: str
    subtype: Literal["file"]
    attachment: dict[str, Any]  # raw attachment dict (= path / mime / size 等)


class BudgetEvent(BaseModel):
    """予算情報 (= 5h / 7d limit に対する現在使用額)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["budget"]
    sid: str
    corr_id: str
    used: Optional[float] = None  # 現在使用 USD
    total: Optional[float] = None  # 上限 USD
    remaining: Optional[float] = None  # 残 USD


class ModeEvent(BaseModel):
    """/plan on / off 等のモード切替"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["mode"]
    sid: str
    corr_id: str
    mode: str  # default / plan / 等


class PermissionModeEvent(BaseModel):
    """permission mode 切替 (= acceptAll / acceptEdits / plan / default)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["permission_mode"]
    sid: str
    corr_id: str
    permissionMode: str


class PrLinkEvent(BaseModel):
    """PR 作成 / 紐付け記録 (= 親 turn で PR 操作が発生した記録)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["pr_link"]
    sid: str
    uuid: str
    corr_id: str
    prNumber: int
    prUrl: str
    prRepository: str
    timestamp: Optional[str] = None


class TurnDurationEvent(BaseModel):
    """1 ターンの処理時間メタ (= Fable 5 で result event の duration_ms 欠落分の代替経路)"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["turn_duration"]
    sid: str
    uuid: Optional[str] = None
    corr_id: str
    parentUuid: Optional[str] = None  # 親 agent bubble uuid (= meta 反映先)
    durationMs: int
    messageCount: Optional[int] = None
    timestamp: Optional[str] = None


class StopHookSummaryEvent(BaseModel):
    """stop hook (= turn 完了時の集約 hook) の summary、 batch メタ"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["stop_hook_summary"]
    sid: str
    corr_id: str
    summary: Optional[str] = None


class AwaySummaryEvent(BaseModel):
    """away (= 離席中) hook の集約 summary、 batch メタ"""
    model_config = ConfigDict(extra="forbid")
    type: Literal["away_summary"]
    sid: str
    corr_id: str
    summary: Optional[str] = None


AnyEvent = Union[UserMessageEvent, AssistantEvent, ResultEvent, AskUserQuestionEvent, TaskNotificationEvent, SystemEvent, SystemErrorEvent, HookErrorEvent, SystemNoteEvent, AttachmentEvent, BudgetEvent, ModeEvent, PermissionModeEvent, PrLinkEvent, TurnDurationEvent, StopHookSummaryEvent, AwaySummaryEvent]

EVENT_BY_TYPE: dict[str, type[BaseModel]] = {
    "user_message": UserMessageEvent,
    "assistant": AssistantEvent,
    "result": ResultEvent,
    "ask_user_question": AskUserQuestionEvent,
    "task_notification": TaskNotificationEvent,
    "system": SystemEvent,
    "system_error": SystemErrorEvent,
    "hook_error": HookErrorEvent,
    "system_note": SystemNoteEvent,
    "attachment": AttachmentEvent,
    "budget": BudgetEvent,
    "mode": ModeEvent,
    "permission_mode": PermissionModeEvent,
    "pr_link": PrLinkEvent,
    "turn_duration": TurnDurationEvent,
    "stop_hook_summary": StopHookSummaryEvent,
    "away_summary": AwaySummaryEvent,
}
