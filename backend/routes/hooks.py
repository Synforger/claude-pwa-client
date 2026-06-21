"""claude CLI hooks の受信エンドポイント (= Web Push 接続経路)。

claude CLI は `~/.claude/settings.json` の `hooks` 配下に登録された command を、
イベント発生時に shell で起動し、 JSON payload を stdin で渡す
(= https://code.claude.com/docs/en/hooks)。

設定側 (= ユーザ環境) で `Stop` / `Notification` 等の hook に
    curl -sS -X POST http://localhost:8765/hooks/event --data-binary @-
を仕込めば、 本エンドポイントが受け取って Web Push に翻訳する。 PTY 経由で動かしてる
claude でも、 turn 完了 / 通知ダイアログ等の契機を PWA 側に届けられる。

session_id 解決:
    claude payload の `session_id` は claude 内部の uuid であり PWA session
    (= chat タブ識別子) とは別。 PWA session への解決は payload の `cwd` →
    AGENTS[<pwa_id>].cwd の逆引きで行う。 マッチしなければ「default」 (= 最初の
    agent) にフォールバック。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from backend.config import AGENTS, TMUX_SESSION_MAP_DIR
from backend.core.push import broadcast_push, notification_title_for
import backend.jsonl.watcher as jsonl_watcher  # backend-F-40: 旧版は関数内 import で循環回避
from backend.jsonl.session_status import (
    apply_immediate_stop as _apply_immediate_stop,
    apply_pending_question as _apply_pending_question,
)
from backend.state import sessions_meta

# backend-F-40 注記: jsonl_watcher は hooks を import しない (= confirm_bind → _save_bindings
# のみ、 hook 経路と無関係) ので module-level import で循環しない。 旧版は防御的に関数内
# import していたが、 結果として hot path で毎回 module lookup を払い、 import error の
# 発見も遅らせていた。 module-level に上げて 1 度だけ評価する。

logger = logging.getLogger(__name__)

router = APIRouter()


_TMUX_MAP = Path(TMUX_SESSION_MAP_DIR).expanduser() if TMUX_SESSION_MAP_DIR else None


def _pwa_session_for_claude_sid(claude_sid: str | None) -> str | None:
    """claude が hook payload で渡してくる claude session_id (= JSONL ファイル名と一致)
    を逆引きして、 PWA タブ識別子 (= `ses_xxxx`) を返す。

    逆引き元は `jsonl_watcher` の confirmed bindings。 これは SessionStart hook 経由で
    X-PWA-SID header 付き curl が来た時のみ書き込まれる確定経路で、 Desktop App /
    ターミナル直叩きの claude は PWA_SID env を持たず SessionStart で弾かれるため
    bindings に入らない (= 構造的に紐付け不可)。 旧実装の statusline map 逆引きは
    map ファイルが古い claude_sid を保持していて誤マッチを起こすケースが実機で確認
    された (= 2026-05-28 ログで Desktop App resume の claude_sid が PWA タブに誤紐付け)
    ため廃止する。

    マッチしなければ None (= Web Push 抑制)。
    """
    if not claude_sid:
        return None
    try:
        bindings = jsonl_watcher.list_bindings()
    except Exception:
        logger.exception("_pwa_session_for_claude_sid: list_bindings failed")
        return None
    # backend-F-23: 旧版は per-hook で bindings dict 全件を線形 scan していた。 binding
    # 数は通常 < 30 程度だが、 hook 発火頻度が高い (= 1 turn で Stop / Notification /
    # PreToolUse 等が短時間に並ぶ) のと、 各 entry で stem 計算が要るので一括 reverse 化
    # した方が分かりやすい。 GC コストを払っても hot path 内で 1 dict 作るだけなので軽い。
    for pwa_sid, info in bindings.items():
        if not info or not info.get("confirmed"):
            continue
        jsonl_path = info.get("jsonl_path")
        if not jsonl_path:
            continue
        # claude CLI の JSONL ファイル名は `<claude_session_id>.jsonl` 規約。
        if Path(jsonl_path).stem == claude_sid:
            return pwa_sid
    return None


def _truncate(text: str, limit: int = 140) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


@router.post("/hooks/event")
async def hooks_event(request: Request) -> dict:
    """claude CLI が hook で叩いてくる JSON を受けて Web Push に変換する。

    対応イベント (= 初期実装):
        - Stop: turn 完了。 payload.output を通知本文に
        - Notification: 通知ダイアログ系。 payload.message を通知本文に
    その他のイベントは受信ログだけ残して 200 OK を返す (= claude の hook を
    詰まらせない、 後で対応イベントを増やしていく)。

    セキュリティ: 本 endpoint は claude CLI の `~/.claude/settings.json` hook が
    `http://localhost:8765/hooks/event` を叩く前提。 tailnet 経由で偽 hook を投げると
    JSONL bind を任意ファイルに書き換えられる経路があるため、 接続元を localhost に限定。
    """
    client_host = request.client.host if request.client else None
    # "testclient" は starlette TestClient のデフォルト host (= 単体テスト用、 外部から
    # この値で到達するクライアントは存在しない)。 production の安全性には影響しない。
    if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        logger.warning("hooks/event rejected: non-local client=%s", client_host)
        raise HTTPException(status_code=403, detail="hooks accepted only from localhost")
    try:
        payload = await request.json()
    except Exception:
        body = await request.body()
        logger.warning("hooks/event: invalid JSON body, len=%d", len(body))
        return {"ok": False, "reason": "invalid_json"}

    event = payload.get("hook_event_name") or "?"
    claude_sid = payload.get("session_id")
    cwd = payload.get("cwd")

    # 確定 binding (= 全イベント共通)。 claude の hook は **どのイベントでも** payload に
    # transcript_path を載せ、 PWA spawn が tmux env に注入した PWA_SID から X-PWA-SID
    # header が全イベントに付く (= PWA タブの claude だけがここを通る、 Desktop / ターミナル
    # 直叩きは header 無し)。 よって「そのタブの claude 自身が報告した transcript」 という
    # 100% 確定の事実だけで pwa_sid → jsonl を毎回確定できる。 backend 再起動後も最初の
    # hook 1 発で正しい jsonl に自己修復するので、 birthtime / cwd による確率紐付けは不要。
    pwa_sid_hdr = request.headers.get("x-pwa-sid", "").strip()
    transcript = payload.get("transcript_path")
    # 二重ロック: (1) X-PWA-SID header は PWA spawn が注入した PWA_SID env からのみ非空に
    # なる (= Desktop App / ターミナル直叩きは `${PWA_SID:-}` が空 or header 自体無し)。
    # (2) さらに header 値が **実在する PWA セッション id** の時だけ bind する。 これで
    # 万一 PWA 由来でない claude が値を送っても、 登録済セッションでなければ弾く
    # (= Desktop App 公式と PWA の取り違えを構造的に不可能にする)。
    bound_path = None
    if pwa_sid_hdr and transcript and pwa_sid_hdr in sessions_meta:
        bound_path = jsonl_watcher.confirm_bind(pwa_sid_hdr, claude_sid or "", transcript)

    # SessionStart: PWA タブ起動時に発火する確定 binding 経路。 PWA spawn 時に tmux
    # session env に `PWA_SID=ses_xxx` を注入してるので、 PWA タブで起動した claude が
    # 呼ぶ hook だけ X-PWA-SID header を持つ (= Desktop App / ターミナル直叩きの claude は
    # PWA_SID env が無いので header が空 → ここで弾かれる)。 /clear で source=clear で
    # 再発火するので新 claude_sid に自動追従する。
    # PreToolUse(AskUserQuestion): 質問が表示された瞬間にリアルタイム発火する
    # (= JSONL は回答まで flush されないので tail では検出不可、 実測で確認済み)。
    # ここで pending_question を立てて status SSE 経由で frontend にライブ表示させる。
    # PWA 判定は X-PWA-SID header (= statusline map 逆引きに依存しない確定経路、
    # SessionStart と同じ)。 tool_use_id は payload に無いので None で立て、 回答後 flush
    # の JSONL AskUserQuestion tool_use 行から補完する (= jsonl_routes._mutate_agent_status)。
    # backend-F-30 / crosscut-F-15: hook event 分岐は HOOK_HANDLERS registry で dispatch
    # する。 各 handler は HookContext を受け取り、 結果 dict (= 200 OK body) を返す。
    # PWA session 解決が要らない early handler (= PreToolUse / SessionStart) は
    # `needs_pwa_session=False`、 通知系 (= Stop / Notification) は True で登録し、
    # dispatcher 側で pwa_session_id 解決 + 未解決時の non_pwa_session ack を集中処理する。
    ctx = HookContext(
        payload=payload,
        event=event,
        claude_sid=claude_sid,
        cwd=cwd,
        pwa_sid_hdr=pwa_sid_hdr,
        transcript=transcript,
        bound_path=bound_path,
    )
    spec = HOOK_HANDLERS.get(event)
    if spec is not None and not spec.needs_pwa_session:
        return await spec.handler(ctx)

    # PWA 経由で起動した claude セッションだけ通知する。 claude CLI の hook 設定は
    # `~/.claude/settings.json` 経由でグローバルなので、 デスクトップ公式 / ターミナル
    # 直叩きでも curl が飛んでくる。 confirmed binding に登録された claude_sid のみが
    # PWA 経由なので、 ここで厳密判別して除外する。
    pwa_session_id = _pwa_session_for_claude_sid(claude_sid)
    if pwa_session_id is None:
        logger.info(
            "hooks/event ignored (not a PWA session): event=%s claude_sid=%s cwd=%s",
            event, claude_sid, cwd,
        )
        return {"ok": True, "ignored": "non_pwa_session"}

    logger.info(
        "hooks/event recv: event=%s claude_sid=%s cwd=%s -> pwa_sid=%s",
        event, claude_sid, cwd, pwa_session_id,
    )
    ctx.pwa_session_id = pwa_session_id
    ctx.title = notification_title_for(pwa_session_id)

    if spec is not None and spec.needs_pwa_session:
        return await spec.handler(ctx)

    # 未対応イベントは受信ログだけ残して通す
    return {"ok": True, "ignored": event}


# --- backend-F-30 / crosscut-F-15: HOOK_HANDLERS registry ----------------
# 旧版は `if event == "X": ...` の長い if-elif で event 分岐を hooks_event 内に直書きしていた
# (= 新 event 追加で関数本体に手を入れる必要 / event ごとの責務が交じる)。 registry に
# 分離することで「event 名 → handler」 1 行 register で増やせる + handler 単位の test が
# 書きやすい (= context 1 個渡せば良いので fixture 最小)。
#
# 新 hook 追加方法:
#   1. `async def _handle_xxx(ctx: HookContext) -> dict:` を本 file or 別 file で定義
#   2. `HOOK_HANDLERS["XxxEventName"] = _HookSpec(handler=_handle_xxx, needs_pwa_session=...)`
#   3. mutate が必要なら `backend.jsonl.session_status` に apply_* helper を新設してから
#      handler が呼ぶフォーマット (= mutate 経路 1 本化哲学)。


@dataclass
class HookContext:
    """1 hook 呼出ぶんの解析済 context。 handler が直接 payload / header を再読しない
    よう、 dispatcher 側で 1 度だけ抽出する。"""
    payload: dict
    event: str
    claude_sid: str | None
    cwd: str | None
    pwa_sid_hdr: str
    transcript: str | None
    bound_path: Optional[Path]
    # dispatcher が pwa_session 解決後に埋める (= needs_pwa_session=True の handler 専用)
    pwa_session_id: str | None = None
    title: str = ""


@dataclass
class _HookSpec:
    handler: Callable[[HookContext], Awaitable[dict]]
    needs_pwa_session: bool


async def _handle_pre_tool_use(ctx: HookContext) -> dict:
    """PreToolUse: 質問が表示された瞬間にリアルタイム発火する (= JSONL は回答まで flush
    されないので tail では検出不可)。 ここで pending_question を立てて status SSE 経由で
    frontend にライブ表示させる。 PWA 判定は X-PWA-SID header。
    """
    payload = ctx.payload
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool_name == "AskUserQuestion" and ctx.pwa_sid_hdr:
        # backend-F-69: hook の pending_question mutate は apply_pending_question に集約。
        # hook が tool_use_id=None で立て、 JSONL tail が真の id で補完する正常経路は不変、
        # 重複到着で既知 id を None で潰す race のみ消える。
        questions = tool_input.get("questions") or []
        if questions and isinstance(questions, list):
            applied = _apply_pending_question(ctx.pwa_sid_hdr, questions, tool_use_id=None)
            if applied:
                logger.info(
                    "PreToolUse AskUserQuestion → pending_question merged: pwa_sid=%s nq=%d",
                    ctx.pwa_sid_hdr, len(questions),
                )
    return {"ok": True, "observed": tool_name}


async def _handle_session_start(ctx: HookContext) -> dict:
    """SessionStart: PWA タブ起動時に発火する確定 binding 経路。 PWA spawn が tmux env に
    `PWA_SID=ses_xxx` を注入してるので、 PWA 経由 claude だけ X-PWA-SID header を持つ。
    """
    source = ctx.payload.get("source")
    if not ctx.pwa_sid_hdr:
        logger.info(
            "SessionStart ignored (no PWA_SID): claude_sid=%s source=%s cwd=%s",
            ctx.claude_sid, source, ctx.cwd,
        )
        return {"ok": True, "ignored": "non_pwa_session"}
    if not ctx.transcript:
        logger.warning(
            "SessionStart missing transcript_path: pwa_sid=%s claude_sid=%s",
            ctx.pwa_sid_hdr, ctx.claude_sid,
        )
        return {"ok": False, "reason": "no_transcript_path"}
    # 確定 binding は dispatcher 共通ブロックで実施済 (= header + transcript + 実在 session の時)。
    # backend-F-70: 共通ブロックで bind 失敗 (= sid 未登録 等) ならここで 1 度だけ warn。
    # 旧版は confirm_bind を SessionStart 内でも呼んで二重呼出していたのを集約。
    if not ctx.bound_path:
        logger.warning(
            "SessionStart bind skipped (sid not registered yet?): pwa_sid=%s claude_sid=%s",
            ctx.pwa_sid_hdr, ctx.claude_sid,
        )
    logger.info(
        "SessionStart bound: pwa_sid=%s source=%s claude_sid=%s -> %s",
        ctx.pwa_sid_hdr, source, ctx.claude_sid,
        ctx.bound_path.name if ctx.bound_path else None,
    )
    return {"ok": ctx.bound_path is not None, "pwa_sid": ctx.pwa_sid_hdr,
            "bound": str(ctx.bound_path) if ctx.bound_path else None}


async def _handle_stop(ctx: HookContext) -> dict:
    """Stop: turn 完了。 apply_immediate_stop で agent_status を即時収束、 broadcast_push
    を fire-and-forget。"""
    payload = ctx.payload
    # Stop hook payload は `last_assistant_message` に直近の assistant 発言全文を載せる
    # (= 2026-05-24 実機ダンプで確認、 spec で `output` ではない)。
    body_raw = payload.get("last_assistant_message") or payload.get("output") or ""
    body = _truncate(body_raw) if body_raw else "(turn 完了)"
    # turn 完了の即時化 (= backend-F-12)。 mutate 経路は session_status 1 本に絞る。
    assert ctx.pwa_session_id is not None  # dispatcher が解決済
    _apply_immediate_stop(ctx.pwa_session_id)
    # fire-and-forget: webpush 送信は数百 ms かかる場合があるので hook の curl を待たせない。
    asyncio.create_task(broadcast_push(body, ctx.title, ctx.pwa_session_id))
    return {"ok": True, "pushed": "Stop"}


async def _handle_notification(ctx: HookContext) -> dict:
    """Notification: 通知ダイアログ系。 generic な「待ち」 通知は skip。"""
    message = ctx.payload.get("message") or ""
    if not message:
        return {"ok": True, "ignored": "empty_message"}
    msg_lower = message.lower()
    if "is waiting" in msg_lower or "needs your input" in msg_lower:
        return {"ok": True, "ignored": "generic_waiting"}
    body = _truncate(message)
    assert ctx.pwa_session_id is not None
    asyncio.create_task(broadcast_push(body, ctx.title, ctx.pwa_session_id))
    return {"ok": True, "pushed": "Notification"}


HOOK_HANDLERS: dict[str, _HookSpec] = {
    "PreToolUse": _HookSpec(handler=_handle_pre_tool_use, needs_pwa_session=False),
    "SessionStart": _HookSpec(handler=_handle_session_start, needs_pwa_session=False),
    "Stop": _HookSpec(handler=_handle_stop, needs_pwa_session=True),
    "Notification": _HookSpec(handler=_handle_notification, needs_pwa_session=True),
}
