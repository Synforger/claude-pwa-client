"""GENERATED FILE — do not edit by hand.

Source: contracts/schema/http-endpoints.yaml
Generator: contracts/codegen/gen-python.py
Regenerate: cd contracts && python codegen/gen-python.py
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

class GetSessionsResponseItem(BaseModel):
    """GET /sessions response[i]"""
    model_config = ConfigDict(extra="forbid")
    sid: str
    title: str
    agent_id: str
    account_id: Optional[str] = None
    notify_mode: Optional[str] = None
    created_at: Optional[str] = None
    tier: Optional[str] = None  # the tier the tab's agent started in (= its AGENT_TIER), else the tier a tier tab was placed for; null when not known
    tier_tab: Optional[str] = None  # the tier a tier tab was placed for (= its new conversations start in it); null for other tabs
    asleep: Optional[bool] = None  # true while the tab's claude is put to sleep (= it starts again in the same conversation when the tab is opened or written to)
    account_on_wake: Optional[str] = None  # for a sleeping tab, the account it runs on once it is woken (= what the account fallback decides when it wakes it, which can differ from account_id); null for a tab that is awake
    kind: Optional[Literal["api"]] = None  # api = a tab with no Claude Code whose conversation a program outside the client writes to a record file and the client only shows (id api_<name>, account_id = its wallet, tier null, never asleep). A Claude tab's row has no kind
    context_tokens: Optional[int] = None  # API tabs only: how much of the context the conversation holds. A tab of api_tabs counts it from its record (= input_tokens + cache_read_input_tokens + cache_creation_input_tokens of the last answer that carries a usage); a tab an api_tab_sources file lists has the amount its program wrote (0 right after the program rolled the conversation over). null when there is none, never 0 for none
    context_window: Optional[int] = None  # API tabs only: the size of the context window the tab's program says (api_tab_sources); null for a tab of api_tabs, or when the program says none


class GetSessionsOverviewResponse(BaseModel):
    """GET /sessions/overview response"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostSessionsRequest(BaseModel):
    """POST /sessions request body"""
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    title: Optional[str] = None
    account_id: Optional[str] = None


class PostSessionsResponse(BaseModel):
    """POST /sessions response"""
    model_config = ConfigDict(extra="forbid")
    sid: str


class PatchSessionsSidRequest(BaseModel):
    """PATCH /sessions/{sid} request body"""
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    notify_mode: Optional[str] = None  # always / mentions / never


class PostSessionsSidForkRequest(BaseModel):
    """POST /sessions/{sid}/fork request body"""
    model_config = ConfigDict(extra="forbid")
    from_uuid: str  # 分岐起点


class PostSessionsSidForkResponse(BaseModel):
    """POST /sessions/{sid}/fork response"""
    model_config = ConfigDict(extra="forbid")
    sid: str  # 新 session id


class PostSessionsSidAccountRequest(BaseModel):
    """POST /sessions/{sid}/account request body"""
    model_config = ConfigDict(extra="forbid")
    account_id: str  # 移し先 account


class PostSessionsSidAccountResponse(BaseModel):
    """POST /sessions/{sid}/account response"""
    model_config = ConfigDict(extra="forbid")
    id: str
    account_id: str


class PostSessionsSidRestartResponse(BaseModel):
    """POST /sessions/{sid}/restart response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    reason: Optional[str] = None


class GetSessionsSidHistoryResponse(BaseModel):
    """GET /sessions/{sid}/history response"""
    model_config = ConfigDict(extra="forbid")
    entries: Optional[list[dict[str, Any]]] = None


class GetAgentsResponseItem(BaseModel):
    """GET /agents response[i]"""
    model_config = ConfigDict(extra="forbid")
    id: str
    display_name: str


class GetAccountsResponseItem(BaseModel):
    """GET /accounts response[i]"""
    model_config = ConfigDict(extra="forbid")
    id: str
    display_name: str
    is_default: bool  # account_id 未設定の session と等価な account (= env に CLAUDE_CONFIG_DIR を持たない最初のもの)


class PostAccountsAccountContinueResponse(BaseModel):
    """POST /accounts/{account}/continue response"""
    model_config = ConfigDict(extra="forbid")
    continued: list[str]  # 続けたタブの id
    failed: list[str]  # 連絡が届かず、 印が残ったタブの id


class GetSettingsResponse(BaseModel):
    """GET /settings response"""
    model_config = ConfigDict(extra="forbid")
    accounts: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    child_sessions_max: Optional[int] = None  # 1 つのタブが同時に持てる子のタブの数。 null = 上限なし
    notification_title: str
    machine: dict[str, Any]  # version / backend_started_at / loop_stall ({ stood_still_sec, back_at } か null)
    limits: dict[str, Any]  # weekdays / line_pct_min / line_pct_max / ahead_pct_min / ahead_pct_max / context_pct_min / context_pct_max / minutes_min
    api_accounts: Optional[list[dict[str, Any]]] = None  # the API wallets (= the setting api_accounts), read-only. They are not accounts: tabs are never moved to one, stopped by one or continued on one
    api_sources: Optional[list[dict[str, Any]]] = None  # the programs that list API tabs (= the setting api_tab_sources) with the settings each lets the screen change, in the order of the setting


class PutSettingsRequest(BaseModel):
    """PUT /settings request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PutSettingsResponse(BaseModel):
    """PUT /settings response"""
    model_config = ConfigDict(extra="forbid")
    pass


class PutSettingsApiSourcesSourceRequest(BaseModel):
    """PUT /settings/api-sources/{source} request body"""
    model_config = ConfigDict(extra="forbid")
    values: dict[str, Any]  # key → number, for the keys to change only


class PutSettingsApiSourcesSourceResponse(BaseModel):
    """PUT /settings/api-sources/{source} response"""
    model_config = ConfigDict(extra="forbid")
    pass


class GetExtensionsResponseItem(BaseModel):
    """GET /extensions response[i]"""
    model_config = ConfigDict(extra="forbid")
    id: str  # ^[a-z0-9][a-z0-9-]{0,31}$
    title: str  # 一覧の名前と iframe の title (= 未指定なら id)
    icon: str  # 🧩 の一覧で名前の前に出す文字 (= 未指定なら 🧩)
    path: str  # /ext/<id>/ (= id から導出、 config には書かない)
    view: Literal["band", "page"]  # 開き方。 band = チャットの上の帯、 page = 入力欄の上を全部使う頁 (= 未指定なら band)


class GetFileResponse(BaseModel):
    """GET /file response"""
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class PostFileOsOpenRequest(BaseModel):
    """POST /file/os-open request body"""
    model_config = ConfigDict(extra="forbid")
    path: str  # 押された path (= ~/... も可)


class PostFileOsOpenResponse(BaseModel):
    """POST /file/os-open response"""
    model_config = ConfigDict(extra="forbid")
    opened: bool  # OS に渡したか。 Markdown・HTML・無い path・Mac でない時は false で、 画面は今までどおり開く


class PutFileRequest(BaseModel):
    """PUT /file request body"""
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class PutFileResponse(BaseModel):
    """PUT /file response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool


class GetTaskOutputResponse(BaseModel):
    """GET /task-output response"""
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class GetFilesTreeResponse(BaseModel):
    """GET /files/tree response"""
    model_config = ConfigDict(extra="forbid")
    path: Optional[str] = None
    entries: Optional[list[dict[str, Any]]] = None


class GetFavoritesResponse(BaseModel):
    """GET /favorites response"""
    model_config = ConfigDict(extra="forbid")
    favorites: list[dict[str, Any]]


class PostFavoritesRequest(BaseModel):
    """POST /favorites request body"""
    model_config = ConfigDict(extra="forbid")
    path: str  # 絶対 path or `~/...`


class PostFavoritesResponse(BaseModel):
    """POST /favorites response"""
    model_config = ConfigDict(extra="forbid")
    favorites: list[dict[str, Any]]


class DeleteFavoritesResponse(BaseModel):
    """DELETE /favorites response"""
    model_config = ConfigDict(extra="forbid")
    favorites: list[dict[str, Any]]


class GetSessionsSidNoteResponse(BaseModel):
    """GET /sessions/{sid}/note response"""
    model_config = ConfigDict(extra="forbid")
    path: str  # メモの file の絶対 path (= エージェントには PWA_NOTE で渡る物)
    content: str
    page: Optional[str] = None  # そのタブのトップページ (= メモの隣の index.html) の絶対 path。 まだ無ければ null


class PutSessionsSidNoteRequest(BaseModel):
    """PUT /sessions/{sid}/note request body"""
    model_config = ConfigDict(extra="forbid")
    content: str


class PutSessionsSidNoteResponse(BaseModel):
    """PUT /sessions/{sid}/note response"""
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class GetSessionsSidSubagentsResponse(BaseModel):
    """GET /sessions/{sid}/subagents response"""
    model_config = ConfigDict(extra="forbid")
    subagents: Optional[list[Any]] = None
    workflows: Optional[list[Any]] = None


class GetSessionsSidWorkflowsRunIdAgentsResponse(BaseModel):
    """GET /sessions/{sid}/workflows/{run_id}/agents response"""
    model_config = ConfigDict(extra="forbid")
    agents: Optional[list[Any]] = None


class GetSessionsSidSubagentsAgentIdTranscriptResponse(BaseModel):
    """GET /sessions/{sid}/subagents/{agent_id}/transcript response"""
    model_config = ConfigDict(extra="forbid")
    lines: Optional[list[str]] = None


class PostPtySidSendRequest(BaseModel):
    """POST /pty/{sid}/send request body"""
    model_config = ConfigDict(extra="forbid")
    text: Optional[str] = None
    key: Optional[str] = None  # send-keys 経由の特殊キー名
    enter: Optional[bool] = None  # 末尾 Enter 送信


class PostPtySidSendResponse(BaseModel):
    """POST /pty/{sid}/send response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    delivered: Optional[bool] = None
    incomplete: Optional[bool] = None


class PostPtySidSendWithFilesRequest(BaseModel):
    """POST /pty/{sid}/send-with-files request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostPtySidSendWithFilesResponse(BaseModel):
    """POST /pty/{sid}/send-with-files response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    saved_files: Optional[list[str]] = None


class PostSessionsSidRolloverRequest(BaseModel):
    """POST /sessions/{sid}/rollover request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostSessionsSidRolloverResponse(BaseModel):
    """POST /sessions/{sid}/rollover response"""
    model_config = ConfigDict(extra="forbid")
    rolling: bool


class GetSessionsSidVoiceResponse(BaseModel):
    """GET /sessions/{sid}/voice response"""
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    marks: list[str]  # 言い方の印の名前 (= 設定に書いた順。 最後に予約の印 mute。 声を持たなければ空)
    default: str  # 印の無い文の印 (= 印を 1 つも持たなければ空文字)
    listen: bool  # 人の声を聞き取るか (= 設定に voice.listen が在るか)
    turn: bool  # 言い終えを判定する model を持つか (= 設定に voice.listen.turn が在るか)
    conversation: Optional[dict[str, Any]] = None  # 会話の間の取り方 (= 設定と調整の file の値、 書いていない項目は既定。 声を持たなければ null)
    tuning_error: str  # 調整の file (= voice.tuning) を使えない理由 (= 使えている / 書いていなければ空文字)


class GetSessionsSidVoiceEngineResponse(BaseModel):
    """GET /sessions/{sid}/voice/engine response"""
    model_config = ConfigDict(extra="forbid")
    engine: Optional[Literal["ready", "waking", "asleep", "failed"]] = None  # ready = 繋がる / waking = 起こしている途中 / asleep = 繋がらない・止めている途中 / failed = 起こすのに失敗し、 次に試すまでの間。 使う時だけ起こす engine でなければ null


class PostSessionsSidVoiceUtterancesRequest(BaseModel):
    """POST /sessions/{sid}/voice/utterances request body"""
    model_config = ConfigDict(extra="forbid")
    text: str  # agent の返事の文 (= markdown のまま)


class PostSessionsSidVoiceUtterancesResponse(BaseModel):
    """POST /sessions/{sid}/voice/utterances response"""
    model_config = ConfigDict(extra="forbid")
    utterances: list[dict[str, Any]]


class PostSessionsSidVoiceSynthesisRequest(BaseModel):
    """POST /sessions/{sid}/voice/synthesis request body"""
    model_config = ConfigDict(extra="forbid")
    text: str  # 声にする 1 文 (= utterances が返した文)
    mark: Optional[str] = None  # 言い方の印 (= 省けば既定の印)
    values: Optional[dict[str, Any]] = None  # 印に添えた値 (= utterances が返した values。 省略可)


class PostSessionsSidVoiceReadingRequest(BaseModel):
    """POST /sessions/{sid}/voice/reading request body"""
    model_config = ConfigDict(extra="forbid")
    text: str  # 読みにする文


class PostSessionsSidVoiceReadingResponse(BaseModel):
    """POST /sessions/{sid}/voice/reading response"""
    model_config = ConfigDict(extra="forbid")
    reading: str  # 拍のカナをつなげた物 (= 間の無音は含めない)


class PostSessionsSidVoiceTranscriptionRequest(BaseModel):
    """POST /sessions/{sid}/voice/transcription request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostSessionsSidVoiceTranscriptionResponse(BaseModel):
    """POST /sessions/{sid}/voice/transcription response"""
    model_config = ConfigDict(extra="forbid")
    text: str  # 聞き取った文 (= 1 行。 声が聞き取れなければ空文字)


class PostSessionsSidVoiceInterruptionResponse(BaseModel):
    """POST /sessions/{sid}/voice/interruption response"""
    model_config = ConfigDict(extra="forbid")
    stopped: bool  # 止めたか (= turn の実行中でなければ false で、 何もしない)


class PostSessionsSidVoiceConversationRequest(BaseModel):
    """POST /sessions/{sid}/voice/conversation request body"""
    model_config = ConfigDict(extra="forbid")
    client: str  # 画面が名乗る名前 (= 英数字と - _ の 64 文字まで。 画面を読み込むたびに作る)


class PostSessionsSidVoiceConversationResponse(BaseModel):
    """POST /sessions/{sid}/voice/conversation response"""
    model_config = ConfigDict(extra="forbid")
    client: str


class DeleteSessionsSidVoiceConversationRequest(BaseModel):
    """DELETE /sessions/{sid}/voice/conversation request body"""
    model_config = ConfigDict(extra="forbid")
    client: str  # 会話を開いた時に名乗った名前


class DeleteSessionsSidVoiceConversationResponse(BaseModel):
    """DELETE /sessions/{sid}/voice/conversation response"""
    model_config = ConfigDict(extra="forbid")
    closed: bool  # 閉じたか (= 別の画面が持っていれば false で、 そのまま)


class PostSessionsSidVoiceCallRequest(BaseModel):
    """POST /sessions/{sid}/voice/call request body"""
    model_config = ConfigDict(extra="forbid")
    sdp: str
    type: str
    pc_id: Optional[str] = None
    restart_pc: Optional[bool] = None


class PostSessionsSidVoiceCallResponse(BaseModel):
    """POST /sessions/{sid}/voice/call response"""
    model_config = ConfigDict(extra="forbid")
    sdp: str
    type: str
    pc_id: str


class PostSessionsSidVoiceCallVolumeRequest(BaseModel):
    """POST /sessions/{sid}/voice/call/volume request body"""
    model_config = ConfigDict(extra="forbid")
    volume: float  # 0 〜 2 (= 1 で engine の音のまま)


class PostSessionsSidVoiceCallVolumeResponse(BaseModel):
    """POST /sessions/{sid}/voice/call/volume response"""
    model_config = ConfigDict(extra="forbid")
    calls: int  # 倍率を伝えた通話の数 (= 通話が無ければ 0)


class PatchSessionsSidVoiceCallRequest(BaseModel):
    """PATCH /sessions/{sid}/voice/call request body"""
    model_config = ConfigDict(extra="forbid")
    pc_id: str
    candidates: list[dict[str, Any]]


class PatchSessionsSidVoiceCallResponse(BaseModel):
    """PATCH /sessions/{sid}/voice/call response"""
    model_config = ConfigDict(extra="forbid")
    status: str


class PostAgentMessagesRequest(BaseModel):
    """POST /agent-messages request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostAgentMessagesResponse(BaseModel):
    """POST /agent-messages response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    delivered: Optional[bool] = None
    to: str  # 届け先のタブの id (= 別の機械のタブは <相手の名前>:<id>)
    operator_said: bool  # 送り主のタブで人が打った発話を封筒に入れたか
    kept: Optional[bool] = None  # 宛先が口座の止める線で止まっていて動ける口座が無いので、 起こさずに預かったか (= 動ける口座ができた時に届く)


class PostSessionsSessionIdAskRequest(BaseModel):
    """POST /sessions/{session_id}/ask request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostSessionsSessionIdAskResponse(BaseModel):
    """POST /sessions/{session_id}/ask response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str  # the asked tab's id
    answer: str  # the last answer of the turn (= last_assistant_message of the Stop hook)


class PostTicketsRequest(BaseModel):
    """POST /tickets request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostTicketsResponse(BaseModel):
    """POST /tickets response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str  # <machine>-<YYMMDD>-<NN>
    place_outside: bool  # true when the ticket is kept outside every boundary of the guard
    operator_said: bool  # whether the operator's words went in as the second line
    operator_said_left_out: Optional[str] = None  # why the words asked for did not go in (= no_operator_words)


class PostTicketsTicketEntriesRequest(BaseModel):
    """POST /tickets/{ticket}/entries request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostTicketsTicketEntriesResponse(BaseModel):
    """POST /tickets/{ticket}/entries response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str
    status: str  # open, waiting-operator or closed


class PostTicketsTicketAsksRequest(BaseModel):
    """POST /tickets/{ticket}/asks request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostTicketsTicketAsksResponse(BaseModel):
    """POST /tickets/{ticket}/asks response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str
    status: str  # waiting-operator


class PostTicketsTicketAnswerRequest(BaseModel):
    """POST /tickets/{ticket}/answer request body"""
    model_config = ConfigDict(extra="forbid")
    asked_at: str  # the `at` of the `asked` line the screen was showing
    text: Optional[str] = None  # the operator's words (= not read when recommend is true)
    recommend: Optional[bool] = None  # true takes the recommendation of that `asked` line as the answer


class PostTicketsTicketAnswerResponse(BaseModel):
    """POST /tickets/{ticket}/answer response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str
    queued: bool  # true: the answer is written and waits for the tab that holds the ticket


class PostTicketsTicketCloseRequest(BaseModel):
    """POST /tickets/{ticket}/close request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostTicketsTicketCloseResponse(BaseModel):
    """POST /tickets/{ticket}/close response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str
    status: str  # closed


class PostTicketsTicketPassRequest(BaseModel):
    """POST /tickets/{ticket}/pass request body"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostTicketsTicketPassResponse(BaseModel):
    """POST /tickets/{ticket}/pass response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str
    to: str  # the receiving tab's id
    kept: Optional[bool] = None  # the tab is stopped by the account hold, so the line is kept and delivered once an account is clear


class GetTicketsTicketResponse(BaseModel):
    """GET /tickets/{ticket} response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    id: str
    status: str
    wants: Optional[str] = None  # decide, mac or report; null when the ticket asks nothing of the operator
    holder: str  # the tab that holds the ticket
    opener: str  # the tab that asked first
    place_outside: Optional[bool] = None
    entries: list[dict[str, Any]]  # the lines; one the reader may not read is {kind, at, hidden: true, text} (= ticket_read_check)


class GetTicketsResponse(BaseModel):
    """GET /tickets response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    tickets: list[dict[str, Any]]


class PostAgentMessagesRelayedRequest(BaseModel):
    """POST /agent-messages/relayed request body"""
    model_config = ConfigDict(extra="forbid")
    to: str  # 宛先のタブの id か名前 (= この機械のタブ)
    from_title: str  # 送り主のタブの名前
    from_session: str  # 送り主のタブの id (= 相手の機械での id)
    text: str  # 本文


class PostAgentMessagesRelayedResponse(BaseModel):
    """POST /agent-messages/relayed response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    delivered: Optional[bool] = None
    to: str  # 届け先のタブの id
    operator_said: bool  # 常に false (= 人の発話は機械を跨がない)
    kept: Optional[bool] = None  # 宛先が口座の止める線で止まっていて動ける口座が無いので、 起こさずに預かったか


class GetAgentMessagesTabsResponse(BaseModel):
    """GET /agent-messages/tabs response"""
    model_config = ConfigDict(extra="forbid")
    tabs: list[dict[str, Any]]


class GetAgentMessagesLocalTabsResponse(BaseModel):
    """GET /agent-messages/local-tabs response"""
    model_config = ConfigDict(extra="forbid")
    tabs: list[dict[str, Any]]


class GetAgentMessagesPeersResponse(BaseModel):
    """GET /agent-messages/peers response"""
    model_config = ConfigDict(extra="forbid")
    peers: list[dict[str, Any]]


class PostPtySidSendRawKeyRequest(BaseModel):
    """POST /pty/{sid}/send-raw-key request body"""
    model_config = ConfigDict(extra="forbid")
    key: str  # 単一 printable char は literal、 Up/Down/Enter 等は tmux キー名
    enter: Optional[bool] = None  # key 送信後に Enter を続けるか (= shell prompt 用、 Ink dialog は不要)


class PostPtySidSendRawKeyResponse(BaseModel):
    """POST /pty/{sid}/send-raw-key response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool


class PostHooksEventRequest(BaseModel):
    """POST /hooks/event request body"""
    model_config = ConfigDict(extra="forbid")
    hook_event_name: str
    session_id: str
    prompt: Optional[str] = None  # UserPromptSubmit の発話


class PostHooksEventResponse(BaseModel):
    """POST /hooks/event response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    context: Optional[str] = None  # agent へ渡す 1 行 (= 在る時だけ)


class GetPushVapidPublicKeyResponse(BaseModel):
    """GET /push/vapid-public-key response"""
    model_config = ConfigDict(extra="forbid")
    public_key: str


class PostPushSubscribeRequest(BaseModel):
    """POST /push/subscribe request body"""
    model_config = ConfigDict(extra="forbid")
    subscription: dict[str, Any]  # PushSubscription dict (= endpoint / keys / expirationTime)


class PostPushSubscribeResponse(BaseModel):
    """POST /push/subscribe response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool


class PostPushUnsubscribeRequest(BaseModel):
    """POST /push/unsubscribe request body"""
    model_config = ConfigDict(extra="forbid")
    endpoint: str


class PostPushUnsubscribeResponse(BaseModel):
    """POST /push/unsubscribe response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool


class PostNotificationsReadAllResponse(BaseModel):
    """POST /notifications/read-all response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool


class PostNotificationsSyncResponse(BaseModel):
    """POST /notifications/sync response"""
    model_config = ConfigDict(extra="forbid")
    unread_count: int


class PostLogSwRequest(BaseModel):
    """POST /log/sw request body"""
    model_config = ConfigDict(extra="forbid")
    event: str


class PostLogSwResponse(BaseModel):
    """POST /log/sw response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool


class GetJsonlDebugBindingsResponse(BaseModel):
    """GET /jsonl/_debug/bindings response"""
    model_config = ConfigDict(extra="forbid")
    pass


class PostStreamUnifiedConnControlRequest(BaseModel):
    """POST /stream/unified/{conn}/control request body"""
    model_config = ConfigDict(extra="forbid")
    op: Literal["jsonl", "view", "voice", "stop", "subagents"]
    sid: Optional[str] = None
    sids: Optional[list[Any]] = None


class PostStreamUnifiedConnControlResponse(BaseModel):
    """POST /stream/unified/{conn}/control response"""
    model_config = ConfigDict(extra="forbid")
    ok: Optional[bool] = None
    subscribed: Optional[list[Any]] = None
    voice: Optional[list[Any]] = None


class PostDeviceOpsRequest(BaseModel):
    """POST /device/ops request body"""
    model_config = ConfigDict(extra="forbid")
    op: str  # <種類>.<操作> (= app の一覧の名前)
    args: Optional[dict[str, Any]] = None  # 操作の引数 (= 一覧の params に従う)
    timeout_s: Optional[float] = None  # 答えを待つ秒 (= 省けば操作が名乗る長さ、 名乗らなければ 30)


class PostDeviceOpsResponse(BaseModel):
    """POST /device/ops response"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    result: Optional[Any] = None  # app の答え (= 大きい答えは files に path の並びで入る)


class PostDeviceScreenResponse(BaseModel):
    """POST /device/screen response"""
    model_config = ConfigDict(extra="forbid")
    bytes: int


class PostDeviceScreenStateRequest(BaseModel):
    """POST /device/screen/state request body"""
    model_config = ConfigDict(extra="forbid")
    live: bool


class PostDeviceScreenStateResponse(BaseModel):
    """POST /device/screen/state response"""
    model_config = ConfigDict(extra="forbid")
    live: bool


class GetDeviceScreenSettingsResponse(BaseModel):
    """GET /device/screen/settings response"""
    model_config = ConfigDict(extra="forbid")
    interval_s: float  # 1 枚を送る間隔 (秒)
    max_side: int  # 長辺の上限 (px)
    quality: float  # JPEG の質 (= 0 より大きく 1 以下)


class GetDeviceScreenResponse(BaseModel):
    """GET /device/screen response"""
    model_config = ConfigDict(extra="forbid")
    live: bool  # 配信中で、 最後の 1 枚が 5 秒より新しい
    path: Optional[str] = None
    at: Optional[float] = None  # 最後の 1 枚の時刻 (= unix 秒)
    age_s: Optional[float] = None
    bytes: Optional[int] = None


class GetDeviceCatalogResponse(BaseModel):
    """GET /device/catalog response"""
    model_config = ConfigDict(extra="forbid")
    connected: bool
    device: Optional[str] = None
    app: Optional[str] = None  # app の版
    since: Optional[float] = None  # つないだ時刻 (= unix 秒)
    catalog: list[Any]  # 操作の並び (= name / kind / summary / params / timeout_s / foreground)


