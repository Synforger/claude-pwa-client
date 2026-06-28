"""ADR-012 /debug/* endpoint 群。

公開原則 (= 2 段防御、 DNS rebinding 対策、 99-references.md § 12-3):
    1. transport peer が loopback (= 127.0.0.1 / ::1) のみ
    2. Host header allowlist (= localhost / 127.0.0.1 / [::1])

production build でも router を含むが、 上記 2 段で外からは触れない設計。 開発者の手元 PC でだけ
ブラウザの localhost 経由で叩ける。

ADR-020 /debug/e2e/seed は更に CPC_E2E=1 env を要求する 3 段防御。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.observability import inspector
from backend.observability.event_journal import journal_path, read_range
from backend.observability.metrics import metrics
from backend.observability.replay import replay_stream

router = APIRouter(prefix="/debug")

# DNS rebinding 対策: Host header の host:port が allowlist にあるもののみ通す。
# 開発時の default port (= 8765) と未指定 port (= None 相当) を許可。
ALLOWED_HOST_NAMES = {
    "localhost",
    "127.0.0.1",
    "[::1]",
    "::1",
}

# transport peer (= request.client.host) として許容する loopback 名。 test では starlette
# TestClient が "testclient" を peer に立てるので、 fixture が monkeypatch で本 set に追加する。
# production では loopback 3 種のみ。
ALLOWED_PEERS = {
    "127.0.0.1",
    "::1",
    "localhost",
}


def _host_is_allowed(host_header: str) -> bool:
    """Host header value (= "localhost:8765" 等) を分解して allowlist と照合。

    port は問わない (= 開発者が configure した backend port は任意で OK)。 host name の正確な
    一致のみを要求する。
    """
    if not host_header:
        return False
    host = host_header.strip().lower()
    # [::1]:port 形式と localhost:port 形式の両対応
    if host.startswith("["):
        # IPv6 bracket
        end = host.find("]")
        if end == -1:
            return False
        name = host[: end + 1]
    else:
        # 最後の ':' を port 区切りと見なす (= IPv4 / 名前 / 素の ::1 を扱う)
        if ":" in host and host.count(":") == 1:
            name = host.rsplit(":", 1)[0]
        else:
            name = host
    return name in ALLOWED_HOST_NAMES


def _ensure_localhost(request: Request) -> None:
    """2 段 check (= loopback peer + Host allowlist)。 違反は 403。"""
    client = request.client
    peer = client.host if client else None
    if peer not in ALLOWED_PEERS:
        raise HTTPException(status_code=403, detail="debug endpoints are localhost-only")
    host_header = request.headers.get("host", "")
    if not _host_is_allowed(host_header):
        raise HTTPException(status_code=403, detail=f"host not allowed: {host_header}")


@router.get("/state")
async def get_state(request: Request) -> dict[str, Any]:
    _ensure_localhost(request)
    return inspector.snapshot()


@router.get("/metrics")
async def get_metrics(request: Request) -> dict[str, Any]:
    _ensure_localhost(request)
    return metrics.snapshot()


@router.get("/log")
async def get_log(
    request: Request,
    sid: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    days_back: int = 1,
    limit: int = 500,
) -> dict[str, Any]:
    """直近 event_journal entry を時刻範囲 + sid で filter して返す (= 単発 JSON)。

    巨大 response 防止のため `limit` (= default 500、 最新を返す)。 streaming で見たい時は
    /debug/replay を使う。
    """
    _ensure_localhost(request)
    entries = read_range(start_ts=start_ts, end_ts=end_ts, sid=sid, days_back=days_back)
    entries.sort(key=lambda e: e.get("seq", 0))
    return {
        "count": len(entries),
        "returned": min(limit, len(entries)),
        "journal_path": str(journal_path()),
        "entries": entries[-limit:],
    }


class ReplayRequest(BaseModel):
    sid: str | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    speed: float = 0.0
    days_back: int = 1


@router.post("/replay")
async def post_replay(request: Request, body: ReplayRequest) -> StreamingResponse:
    """event_journal を SSE で再配信。 frontend debug panel が直接 EventSource で接続する想定。"""
    _ensure_localhost(request)
    return StreamingResponse(
        replay_stream(
            sid=body.sid,
            start_ts=body.start_ts,
            end_ts=body.end_ts,
            speed=body.speed,
            days_back=body.days_back,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ----- ADR-020 e2e seed endpoint ---------------------------------------------
# Bypasses hook-driven binding (= claude SessionStart hook) so playwright can
# install a session + JSONL fixture in one POST. Triple-gated: localhost peer,
# Host allowlist, and CPC_E2E=1 must be set in the backend process env. The
# router stays registered in prod builds so any env mistake fails closed (= 404
# without the env), matching the rest of /debug/*.


def _ensure_e2e_enabled() -> None:
    if os.environ.get("CPC_E2E") != "1":
        raise HTTPException(status_code=404, detail="not found")


class E2eSeedRequest(BaseModel):
    sid: str = Field(..., description="pwa session id (= ses_xxx)")
    agent_id: str = Field("agent_e2e", description="must exist in config.agents")
    account_id: str | None = Field(None, description="resolves the claude projects dir")
    title: str | None = None
    notify_mode: str = Field("both", description="off | banner | both")
    claude_sid: str | None = Field(
        None,
        description="filename stem under <projects>/<cwd-hash>/; UUID4 if omitted",
    )
    jsonl_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="ordered JSONL events; written verbatim, one per line",
    )


class E2eSeedResponse(BaseModel):
    sid: str
    claude_sid: str
    jsonl_path: str
    written_events: int


@router.post("/e2e/seed", response_model=E2eSeedResponse)
async def post_e2e_seed(request: Request, body: E2eSeedRequest) -> E2eSeedResponse:
    """Seed a session_meta entry + JSONL fixture + confirmed binding in one go.

    Mirrors what `POST /sessions` + claude SessionStart hook would do, but
    without spawning tmux / claude. Playwright global-setup calls this once per
    fixture session.
    """
    _ensure_localhost(request)
    _ensure_e2e_enabled()

    # Imports are local so prod builds never load these modules unless e2e is
    # actually exercised (= keeps startup graph clean + dodges a state.py side
    # effect for non-e2e processes).
    from backend.config import projects_dir_for_account
    from backend.jsonl import watcher
    from backend.state import register_session, sessions_meta

    agents = (await _agents_snapshot())
    if body.agent_id not in agents:
        raise HTTPException(status_code=400, detail=f"unknown agent_id: {body.agent_id}")
    agent_cwd = agents[body.agent_id].get("cwd") or str(Path.home())

    claude_sid = body.claude_sid or str(uuid.uuid4())
    projects_dir = projects_dir_for_account(body.account_id)
    # Safety net: refuse to write into the operator's real ~/.claude/projects.
    # The launcher is supposed to point the e2e account at an isolated dir
    # (= fixtures/_runtime/.claude); if it didn't, fail loud instead of
    # silently scattering fixture JSONL into live chat history.
    real_home_claude = (Path.home() / ".claude" / "projects").resolve()
    if projects_dir.resolve() == real_home_claude:
        raise HTTPException(
            status_code=400,
            detail=(
                "refusing to seed into the real ~/.claude/projects. "
                "Set accounts.<account>.env.CLAUDE_CONFIG_DIR to an isolated dir."
            ),
        )
    cwd_hash = watcher._cwd_to_project_dirname(agent_cwd)
    jsonl_dir = projects_dir / cwd_hash
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = jsonl_dir / f"{claude_sid}.jsonl"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for event in body.jsonl_events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Re-seeding the same sid is idempotent: drop the previous registration so
    # register_session reinitialises every companion dict (stream_states /
    # agent_status / session_states), matching what a fresh /sessions POST
    # would produce.
    if body.sid in sessions_meta:
        sessions_meta.pop(body.sid, None)
    register_session(
        agent_id=body.agent_id,
        title=body.title or body.sid,
        account_id=body.account_id,
        sid=body.sid,
    )
    # notify_mode override (register_session leaves it at "both" by default).
    if body.notify_mode in {"off", "banner", "both"}:
        sessions_meta[body.sid].notify_mode = body.notify_mode

    watcher.confirm_bind(body.sid, claude_sid, str(jsonl_path))

    return E2eSeedResponse(
        sid=body.sid,
        claude_sid=claude_sid,
        jsonl_path=str(jsonl_path),
        written_events=len(body.jsonl_events),
    )


class PendingPlanInjectRequest(BaseModel):
    plan: str = Field("e2e plan body")
    tool_use_id: str = Field("tool_e2e_plan")
    choices: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/e2e/inject-pending-plan/{session_id}")
async def post_e2e_inject_pending_plan(
    request: Request,
    session_id: str,
    body: PendingPlanInjectRequest,
) -> dict:
    """ADR-022 follow-up: write pending_plan straight into agent_status[sid].

    The status SSE pump reads from agent_status, so the next tick delivers
    the change to whatever client is subscribed - same path as the real
    capture_plan_choices result but without needing a tmux pane.
    """
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    from backend.state import agent_status, sessions_overview
    if session_id not in agent_status:
        raise HTTPException(status_code=409, detail="no session")
    agent_status[session_id]["pending_plan"] = {
        "tool_use_id": body.tool_use_id,
        "plan": body.plan,
        "choices": body.choices,
    }
    # Wake the /sessions/status/stream broadcaster so subscribers get the new
    # snapshot on the next event loop tick instead of waiting for the 20s
    # keep-alive to roll around.
    sessions_overview.notify()
    return {"ok": True}


class PtyWriteRequest(BaseModel):
    bytes_b64: str = Field(..., description="base64-encoded bytes to enqueue on the WS output side")


@router.post("/e2e/pty-write/{session_id}")
async def post_e2e_pty_write(request: Request, session_id: str, body: PtyWriteRequest) -> dict:
    """ADR-022 e2e WS injection: enqueue bytes on a fake PTY session's output queue.

    The websocket /ws/pty/{sid} handler in CPC_E2E mode skips spawn and
    installs a queue-only PtySession; pump_to_client then forwards anything
    we put on the queue to every attached client. Scenarios use this to
    drive UTF-8 boundary tests, ANSI tests, etc., without booting a real PTY.
    """
    import base64
    _ensure_localhost(request)
    _ensure_e2e_enabled()
    from backend.terminal.runner import pty_sessions
    session = pty_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=409, detail="no pty session (= /ws/pty not connected yet?)")
    try:
        data = base64.b64decode(body.bytes_b64, validate=True)
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=400, detail=f"bad base64: {exc}") from exc
    try:
        session.output_queue.put_nowait(data)
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail="pty queue full") from None
    return {"ok": True, "queued": len(data)}


async def _agents_snapshot() -> dict[str, dict[str, Any]]:
    # Tiny indirection so the test suite can monkeypatch agent config without
    # reaching into backend.config internals.
    from backend.config import AGENTS  # noqa: PLC0415
    return AGENTS


# ----- /debug/healthcheck (= prod backend liveness probe, 12 read-only checks)
# Diagnoses "is every feature alive RIGHT NOW" so the operator can curl one
# endpoint when investigating user-reported symptoms (file tree dead, launch
# alias silent, push notifications missing, PTY fd exhausted, etc.). All
# checks are read-only — no spawn, no real push send, no file mutation.
# Localhost-gated by the same 2-stage defence as the rest of /debug/*.


_HEALTH_CHECK_NAMES = (
    "liveness",
    "config",
    "agent_launch_alias",
    "session_meta",
    "jsonl_bindings",
    "claude_jsonl_files",
    "files_tree",
    "tmux_pty_sessions",
    "vapid",
    "subscriptions",
    "push_dry_run",
    "backend_error_log",
)


@router.get("/healthcheck")
async def get_healthcheck(request: Request) -> dict[str, Any]:
    """Run all 12 read-only probes and return per-check `{ok, ...}`.

    Never raises; each check is isolated in try/except so a single broken
    probe doesn't blank the whole report. The HTTP status is always 200 —
    callers must look at `summary.fail` / per-check `ok` to decide.
    """
    _ensure_localhost(request)
    return await _build_healthcheck()


async def _build_healthcheck() -> dict[str, Any]:
    import os as _os
    checks: dict[str, dict[str, Any]] = {}
    runners = {
        "liveness": _check_liveness,
        "config": _check_config,
        "agent_launch_alias": _check_agent_launch_alias,
        "session_meta": _check_session_meta,
        "jsonl_bindings": _check_jsonl_bindings,
        "claude_jsonl_files": _check_claude_jsonl_files,
        "files_tree": _check_files_tree,
        "tmux_pty_sessions": _check_tmux_pty_sessions,
        "vapid": _check_vapid,
        "subscriptions": _check_subscriptions,
        "push_dry_run": _check_push_dry_run,
        "backend_error_log": _check_backend_error_log,
    }
    for name in _HEALTH_CHECK_NAMES:
        try:
            result = await runners[name]()
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        checks[name] = result

    fail = sum(1 for r in checks.values() if not r.get("ok"))
    return {
        "ts": time.time(),
        "pid": _os.getpid(),
        "summary": {
            "total": len(checks),
            "pass": len(checks) - fail,
            "fail": fail,
        },
        "checks": checks,
    }


async def _check_liveness() -> dict[str, Any]:
    import os as _os
    from backend.paths import LOGS_DIR
    boot_marker = LOGS_DIR / "backend.log"
    uptime_sec: float | None = None
    if boot_marker.exists():
        try:
            uptime_sec = max(0.0, time.time() - boot_marker.stat().st_mtime)
        except OSError:
            uptime_sec = None
    return {"ok": True, "pid": _os.getpid(), "uptime_sec_hint": uptime_sec}


async def _check_config() -> dict[str, Any]:
    from backend.config import get_config
    from backend.paths import CONFIG_PATH
    cfg = get_config()
    agents = cfg.get("agents") or {}
    accounts = cfg.get("accounts") or {}
    claude_path = cfg.get("claude_path") or ""
    missing: list[str] = []
    if not agents:
        missing.append("agents")
    if not claude_path:
        missing.append("claude_path")
    elif not Path(claude_path).expanduser().exists():
        missing.append(f"claude_path:not_exists({claude_path})")
    return {
        "ok": not missing,
        "config_path": str(CONFIG_PATH),
        "agents_count": len(agents),
        "accounts_count": len(accounts),
        "claude_path": claude_path,
        "missing": missing,
    }


async def _check_agent_launch_alias() -> dict[str, Any]:
    """Per-agent: launch_alias defined? alias resolvable via login shell?

    "launch alias never fires after session restart" の主因候補:
        a) config.agents.<id>.launch_alias 未定義 → そもそも送られない
        b) launch_alias 定義ありだが shell に該当 alias なし → tmux に文字列が
           送られるが zsh が「command not found」 を返して claude 起動失敗
        c) zsh prompt 検出 timeout で送られない (= backend-F-49 系の退行)
    ここでは a) と b) を直接判定。 c) は実 spawn しないと出ないので別 spec で。
    """
    import shutil
    import subprocess as _sp
    from backend.config import get_config
    agents = (get_config().get("agents") or {})
    per_agent: list[dict[str, Any]] = []
    any_fail = False
    zsh = shutil.which("zsh") or "/bin/zsh"
    for agent_id, agent_cfg in agents.items():
        alias = (agent_cfg or {}).get("launch_alias") or ""
        cwd = (agent_cfg or {}).get("cwd") or ""
        entry: dict[str, Any] = {
            "agent_id": agent_id,
            "launch_alias": alias,
            "cwd": cwd,
            "cwd_exists": bool(cwd) and Path(cwd).expanduser().is_dir(),
        }
        if not alias:
            entry["resolved"] = False
            entry["reason"] = "launch_alias not defined in config"
            any_fail = True
            per_agent.append(entry)
            continue
        # zsh -ilc "type <alias>": login + interactive で .zshrc を読み込み、
        # alias / function / file として解決可能か判定。 timeout で hang を防ぐ。
        try:
            proc = _sp.run(
                [zsh, "-ilc", f"type {alias!s} 2>&1"],
                capture_output=True, text=True, timeout=5,
            )
            stdout = (proc.stdout or "").strip()
            entry["resolved"] = proc.returncode == 0
            entry["type_output"] = stdout[:200]
            if proc.returncode != 0:
                any_fail = True
                entry["reason"] = "alias not found in login zsh"
        except (_sp.TimeoutExpired, OSError) as exc:
            entry["resolved"] = False
            entry["reason"] = f"zsh probe failed: {type(exc).__name__}"
            any_fail = True
        per_agent.append(entry)
    return {
        "ok": not any_fail and bool(agents),
        "shell": zsh,
        "agents": per_agent,
    }


async def _check_session_meta() -> dict[str, Any]:
    from backend.paths import SESSION_META_PATH
    from backend.state import sessions_meta
    in_memory = list(sessions_meta.keys())
    on_disk: list[str] = []
    parse_error: str | None = None
    if SESSION_META_PATH.exists():
        try:
            raw = json.loads(SESSION_META_PATH.read_text())
            if isinstance(raw, list):
                on_disk = [e.get("id") for e in raw if isinstance(e, dict) and e.get("id")]
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    dupes = sorted({sid for sid in on_disk if on_disk.count(sid) > 1})
    drift = sorted(set(in_memory) ^ set(on_disk))
    return {
        "ok": parse_error is None and not dupes and not drift,
        "path": str(SESSION_META_PATH),
        "in_memory_count": len(in_memory),
        "on_disk_count": len(on_disk),
        "in_memory_ids": in_memory,
        "duplicate_ids": dupes,
        "mem_vs_disk_drift": drift,
        "parse_error": parse_error,
    }


async def _check_jsonl_bindings() -> dict[str, Any]:
    from backend.jsonl.watcher import list_bindings
    from backend.paths import JSONL_BINDINGS_PATH
    bindings = list_bindings()
    per_sid: list[dict[str, Any]] = []
    any_missing = False
    for sid, b in bindings.items():
        jp = b.get("jsonl_path")
        entry: dict[str, Any] = {
            "sid": sid,
            "confirmed": b.get("confirmed"),
            "jsonl_path": jp,
        }
        if jp:
            p = Path(jp)
            try:
                st = p.stat()
                entry["exists"] = True
                entry["size"] = st.st_size
                entry["mtime"] = st.st_mtime
            except OSError:
                entry["exists"] = False
                any_missing = True
        else:
            entry["exists"] = False
            any_missing = b.get("confirmed", False)
        per_sid.append(entry)
    return {
        "ok": not any_missing,
        "persist_path": str(JSONL_BINDINGS_PATH),
        "binding_count": len(bindings),
        "bindings": per_sid,
    }


async def _check_claude_jsonl_files() -> dict[str, Any]:
    """For each session_meta entry, look up the binding's transcript and verify
    the jsonl file actually exists under the resolved account's projects dir."""
    from backend.jsonl.watcher import list_bindings
    from backend.state import sessions_meta
    bindings = list_bindings()
    missing: list[str] = []
    have: int = 0
    for sid in sessions_meta:
        jp = (bindings.get(sid) or {}).get("jsonl_path")
        if jp and Path(jp).is_file():
            have += 1
        else:
            missing.append(sid)
    return {
        "ok": not missing,
        "session_count": len(sessions_meta),
        "with_jsonl": have,
        "missing_sids": missing,
    }


async def _check_files_tree() -> dict[str, Any]:
    """Dry-run the same path resolution `/files/tree` would do for HOME root.
    Catches "file tree button does nothing" symptoms without enumerating the
    full tree."""
    from backend.config import HOME
    from backend.routes.files import _DENY_RE
    try:
        resolved = Path("~").expanduser().resolve()
        resolved.relative_to(HOME)
        denied = bool(_DENY_RE.search(str(resolved)))
        if denied:
            return {"ok": False, "reason": "HOME root matched deny regex (impossible)"}
        # 1 階層だけ iterdir で読めるか確認 (= permission 確認)。 結果は捨てる。
        sample: list[str] = []
        for i, entry in enumerate(resolved.iterdir()):
            if entry.name.startswith("."):
                continue
            sample.append(entry.name)
            if i > 5:
                break
        return {"ok": True, "home": str(resolved), "sample_entries": sample}
    except PermissionError as exc:
        return {"ok": False, "reason": f"PermissionError: {exc}"}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


async def _check_tmux_pty_sessions() -> dict[str, Any]:
    """In-memory pty_sessions registry + open fd count (= macOS PTY device上限
    256 / launchd default fd limit と照合可能)。 fd 超過による PTY spawn 連鎖
    失敗を早期検知する。"""
    import resource as _resource
    from backend.state import sessions_meta
    from backend.terminal.runner import has_tmux_session, pty_sessions
    pty_count = len(pty_sessions)
    per_sid: list[dict[str, Any]] = []
    for sid in sessions_meta:
        per_sid.append({
            "sid": sid,
            "pty_attached": sid in pty_sessions,
            "tmux_alive": has_tmux_session(sid),
        })
    soft, hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
    # 自プロセスの実 open fd 数 (macOS は /dev/fd を列挙)
    open_fd = -1
    try:
        open_fd = len(list(Path("/dev/fd").iterdir()))
    except OSError:
        pass
    return {
        "ok": True,
        "session_count": len(sessions_meta),
        "pty_attached_count": pty_count,
        "sessions": per_sid,
        "fd_rlimit_soft": soft,
        "fd_rlimit_hard": hard,
        "open_fd_count": open_fd,
    }


async def _check_vapid() -> dict[str, Any]:
    import hashlib
    from backend.paths import VAPID_PATH
    if not VAPID_PATH.exists():
        return {"ok": False, "reason": "vapid.json not found", "path": str(VAPID_PATH)}
    try:
        data = json.loads(VAPID_PATH.read_text())
    except Exception as exc:
        return {"ok": False, "reason": f"parse: {exc}", "path": str(VAPID_PATH)}
    pub = (data.get("public_key") or "").strip()
    has_priv = bool((data.get("private_pem") or "").strip())
    fp = hashlib.sha256(pub.encode()).hexdigest()[:16] if pub else None
    return {
        "ok": bool(pub and has_priv),
        "path": str(VAPID_PATH),
        "public_key_fingerprint": fp,
        "has_private_pem": has_priv,
    }


async def _check_subscriptions() -> dict[str, Any]:
    from backend.core.push import subscriptions
    from backend.paths import SUBSCRIPTIONS_PATH
    subs = list(subscriptions)
    endpoints: list[str] = []
    for s in subs:
        ep = (s or {}).get("endpoint") or ""
        # Origin だけ抽出 (= 端末 token を log に出さない)。 fcm / web.push.apple / etc.
        if ep:
            try:
                from urllib.parse import urlparse
                u = urlparse(ep)
                endpoints.append(f"{u.scheme}://{u.netloc}")
            except Exception:
                endpoints.append("(unparseable)")
    return {
        "ok": True,  # 0 件でも probe 自体は OK、 通知未着の原因把握材料として返すだけ
        "path": str(SUBSCRIPTIONS_PATH),
        "count": len(subs),
        "endpoint_origins": endpoints,
    }


async def _check_push_dry_run() -> dict[str, Any]:
    """pywebpush import + VAPID load + subscription 構造 validation のみ。
    実 POST はしない (= APNs / FCM に hit させない)。 「通知経路が組み立て可能か」
    を判定する。"""
    try:
        from pywebpush import webpush as _webpush  # noqa: F401
        has_lib = True
    except ImportError:
        has_lib = False
    from backend.core.push import subscriptions, vapid_config
    well_formed = 0
    malformed: list[str] = []
    for s in subscriptions:
        ep = (s or {}).get("endpoint")
        keys = (s or {}).get("keys") or {}
        if isinstance(ep, str) and ep and isinstance(keys, dict) and keys.get("p256dh") and keys.get("auth"):
            well_formed += 1
        else:
            malformed.append(ep[:60] if isinstance(ep, str) else "(no endpoint)")
    can_send = has_lib and vapid_config is not None
    return {
        "ok": can_send,
        "pywebpush_installed": has_lib,
        "vapid_loaded": vapid_config is not None,
        "subscription_count": len(subscriptions),
        "well_formed_subscriptions": well_formed,
        "malformed_subscriptions": malformed,
        "note": "dry-run only — actual POST not attempted",
    }


async def _check_backend_error_log() -> dict[str, Any]:
    from backend.paths import LOGS_DIR
    log_path = LOGS_DIR / "backend.error.log"
    if not log_path.exists():
        return {"ok": True, "path": str(log_path), "exists": False}
    try:
        # 末尾 200 行だけ読む (= rotation で 5MB 上限なので余裕で全読みも可だが
        # 帯域節約)。
        with log_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read = min(size, 200 * 1024)
            f.seek(size - read)
            tail = f.read().decode("utf-8", errors="replace")
        lines = tail.splitlines()[-200:]
    except OSError as exc:
        return {"ok": False, "reason": f"read failed: {exc}", "path": str(log_path)}
    needles = ("ERROR ", "Exception", "Traceback", "OSError", "FileNotFoundError")
    hits = [ln for ln in lines if any(n in ln for n in needles)]
    return {
        "ok": not hits,
        "path": str(log_path),
        "scanned_lines": len(lines),
        "match_count": len(hits),
        "recent_matches": hits[-10:],
    }
