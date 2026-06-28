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
    model_config = ConfigDict(extra="ignore")
    sid: str
    title: str
    agent_id: str
    account_id: Optional[str] = None
    notify_mode: Optional[str] = None
    created_at: Optional[str] = None


class PostSessionsRequest(BaseModel):
    """POST /sessions request body"""
    model_config = ConfigDict(extra="ignore")
    agent_id: str
    title: Optional[str] = None
    account_id: Optional[str] = None


class PostSessionsResponse(BaseModel):
    """POST /sessions response"""
    model_config = ConfigDict(extra="ignore")
    sid: str


class PatchSessionsSidRequest(BaseModel):
    """PATCH /sessions/{sid} request body"""
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    notify_mode: Optional[str] = None  # always / mentions / never


class PostSessionsSidForkRequest(BaseModel):
    """POST /sessions/{sid}/fork request body"""
    model_config = ConfigDict(extra="ignore")
    from_uuid: str


class PostSessionsSidForkResponse(BaseModel):
    """POST /sessions/{sid}/fork response"""
    model_config = ConfigDict(extra="ignore")
    sid: str  # 新 session id


class PostSessionsSidRestartResponse(BaseModel):
    """POST /sessions/{sid}/restart response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool
    reason: Optional[str] = None


class GetSessionsSidHistoryResponse(BaseModel):
    """GET /sessions/{sid}/history response"""
    model_config = ConfigDict(extra="ignore")
    entries: Optional[list[dict[str, Any]]] = None


class GetAgentsResponseItem(BaseModel):
    """GET /agents response[i]"""
    model_config = ConfigDict(extra="ignore")
    id: str
    display_name: str


class GetAccountsResponseItem(BaseModel):
    """GET /accounts response[i]"""
    model_config = ConfigDict(extra="ignore")
    id: str
    display_name: str


class GetFileResponse(BaseModel):
    """GET /file response"""
    model_config = ConfigDict(extra="ignore")
    path: str
    content: str


class PutFileRequest(BaseModel):
    """PUT /file request body"""
    model_config = ConfigDict(extra="ignore")
    path: str
    content: str


class PutFileResponse(BaseModel):
    """PUT /file response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool


class GetTaskOutputResponse(BaseModel):
    """GET /task-output response"""
    model_config = ConfigDict(extra="ignore")
    path: str
    content: str


class GetFilesTreeResponse(BaseModel):
    """GET /files/tree response"""
    model_config = ConfigDict(extra="ignore")
    path: Optional[str] = None
    entries: Optional[list[dict[str, Any]]] = None


class GetSessionsSidSubagentsResponse(BaseModel):
    """GET /sessions/{sid}/subagents response"""
    model_config = ConfigDict(extra="ignore")
    subagents: Optional[list[Any]] = None
    workflows: Optional[list[Any]] = None


class GetSessionsSidWorkflowsRunIdAgentsResponse(BaseModel):
    """GET /sessions/{sid}/workflows/{run_id}/agents response"""
    model_config = ConfigDict(extra="ignore")
    agents: Optional[list[Any]] = None


class GetSessionsSidSubagentsAgentIdTranscriptResponse(BaseModel):
    """GET /sessions/{sid}/subagents/{agent_id}/transcript response"""
    model_config = ConfigDict(extra="ignore")
    lines: Optional[list[str]] = None


class PostPtySidSendRequest(BaseModel):
    """POST /pty/{sid}/send request body"""
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    key: Optional[str] = None  # send-keys 経由の特殊キー名
    enter: Optional[bool] = None  # 末尾 Enter 送信


class PostPtySidSendResponse(BaseModel):
    """POST /pty/{sid}/send response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool
    delivered: Optional[bool] = None
    incomplete: Optional[bool] = None


class PostPtySidSendWithFilesRequest(BaseModel):
    """POST /pty/{sid}/send-with-files request body"""
    model_config = ConfigDict(extra="ignore")
    pass


class PostPtySidSendWithFilesResponse(BaseModel):
    """POST /pty/{sid}/send-with-files response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool
    saved_files: Optional[list[str]] = None


class PostHooksEventRequest(BaseModel):
    """POST /hooks/event request body"""
    model_config = ConfigDict(extra="ignore")
    hook_event_name: str
    session_id: str


class PostHooksEventResponse(BaseModel):
    """POST /hooks/event response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool


class GetPushVapidPublicKeyResponse(BaseModel):
    """GET /push/vapid-public-key response"""
    model_config = ConfigDict(extra="ignore")
    public_key: str


class PostPushSubscribeRequest(BaseModel):
    """POST /push/subscribe request body"""
    model_config = ConfigDict(extra="ignore")
    subscription: dict[str, Any]  # PushSubscription dict (= endpoint / keys / expirationTime)


class PostPushSubscribeResponse(BaseModel):
    """POST /push/subscribe response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool


class PostPushUnsubscribeRequest(BaseModel):
    """POST /push/unsubscribe request body"""
    model_config = ConfigDict(extra="ignore")
    endpoint: str


class PostPushUnsubscribeResponse(BaseModel):
    """POST /push/unsubscribe response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool


class PostNotificationsReadAllResponse(BaseModel):
    """POST /notifications/read-all response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool


class PostNotificationsSyncResponse(BaseModel):
    """POST /notifications/sync response"""
    model_config = ConfigDict(extra="ignore")
    unread_count: int


class PostLogSwRequest(BaseModel):
    """POST /log/sw request body"""
    model_config = ConfigDict(extra="ignore")
    event: str


class PostLogSwResponse(BaseModel):
    """POST /log/sw response"""
    model_config = ConfigDict(extra="ignore")
    ok: bool


class GetJsonlDebugBindingsResponse(BaseModel):
    """GET /jsonl/_debug/bindings response"""
    model_config = ConfigDict(extra="ignore")
    pass


