"""/debug/healthcheck (= prod backend liveness probe, 12 read-only checks)。

Diagnoses "is every feature alive RIGHT NOW" so the operator can curl one
endpoint when investigating user-reported symptoms (file tree dead, launch
alias silent, push notifications missing, PTY fd exhausted, etc.). All
checks are read-only — no spawn, no real push send, no file mutation.

公開原則 = /debug/* 共通の 2 段防御 (= loopback peer + Host allowlist、
`debug._ensure_localhost` を共用) のみ。 e2e 系 (= CPC_E2E env の 3 段目が付く
`debug_e2e.py`) とは防御レベルが違うので file を分離してある。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from backend.routes.debug import _ensure_localhost

router = APIRouter(prefix="/debug")


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
    from backend.core.jsonl_watcher import list_bindings
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
    """For each *bound* session, verify the recorded transcript still exists
    on disk. Sessions without any binding are "未起動タブ" (= the user has
    never opened a claude on them yet) — those are expected to be missing,
    not a fault. Only previously-confirmed bindings whose jsonl has vanished
    count as broken."""
    from backend.core.jsonl_watcher import list_bindings
    from backend.state import sessions_meta
    bindings = list_bindings()
    broken: list[str] = []
    not_started: list[str] = []
    healthy: int = 0
    for sid in sessions_meta:
        b = bindings.get(sid)
        jp = (b or {}).get("jsonl_path")
        if jp:
            if Path(jp).is_file():
                healthy += 1
            else:
                # binding was confirmed at some point but the file disappeared
                broken.append(sid)
        else:
            # never started, or binding never confirmed (= no hook fired yet)
            not_started.append(sid)
    return {
        "ok": not broken,
        "session_count": len(sessions_meta),
        "with_healthy_jsonl": healthy,
        "broken_bindings": broken,
        "not_started_sids": not_started,
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
        # benign: /dev/fd 列挙は debug endpoint の best-effort 補助情報、
        # 取れなければ -1 のまま return する設計 (= 観測経路で例外を投げると
        # healthcheck dashboard が壊れる方が損失大)。
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
