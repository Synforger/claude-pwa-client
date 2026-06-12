"""個人 / 仕事 Claude OAuth credentials をワンタップで切り替える経路。

claude CLI は macOS keychain の単一エントリ "Claude Code-credentials" で認証情報を持つので、
事前に "Claude Code-credentials-personal" / "Claude Code-credentials-work" として退避した
別エントリの中身を本エントリに上書きすることでアカウントを丸ごと差し替える。

切替後は走行中の claude TUI を全部 kill する。 tmux session 自体は残し、 既存の autoresume
経路 (= terminal/session_resolver.resolve_autoresume_fallback) が新 credentials + 既存の
claude_sid で claude を再起動する → ユーザ視点では同じ会話の続きを別アカウントで継続する形。

退避エントリの初回セットアップは README / セットアップガイド参照。
"""
from __future__ import annotations

import getpass
import json
import logging
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)
_ACCOUNT = getpass.getuser()

ACTIVE_SERVICE = "Claude Code-credentials"
PROFILE_SERVICES: dict[str, str] = {
    "personal": "Claude Code-credentials-personal",
    "work":     "Claude Code-credentials-work",
}
Profile = Literal["personal", "work"]


def _read_password(service: str) -> str | None:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip() or None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("keychain read failed service=%s: %s", service, e)
        return None


def _write_password(service: str, password: str) -> bool:
    try:
        r = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", service, "-a", _ACCOUNT, "-w", password],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("keychain write failed service=%s: %s", service, e)
        return False


def _profile_of(payload: str | None) -> str | None:
    """credentials JSON から subscription type を取って profile ラベルに変換する。
    判定は subscriptionType 値で行う (= 個人 Max = 'max', 会社 Team = 'team')。
    """
    if not payload:
        return None
    try:
        d = json.loads(payload)
        sub = (d.get("claudeAiOauth") or {}).get("subscriptionType")
    except (json.JSONDecodeError, AttributeError):
        return None
    if sub == "team":
        return "work"
    if sub == "max":
        return "personal"
    return None


def current_profile() -> str | None:
    """今 active な credentials の profile (personal / work) を返す。 判別不能なら None。"""
    return _profile_of(_read_password(ACTIVE_SERVICE))


def available_profiles() -> list[str]:
    return [p for p, svc in PROFILE_SERVICES.items() if _read_password(svc) is not None]


def switch_profile(target: Profile) -> dict:
    """target profile の credentials を active に書き戻す。 成功なら新 profile を返す。

    成功条件:
      - target 用 entry が事前退避されてる
      - keychain への上書き成功
    失敗時は changed=False + reason を含む dict を返す (= 例外は投げない)。
    """
    if target not in PROFILE_SERVICES:
        return {"changed": False, "reason": f"unknown profile: {target}", "profile": current_profile()}
    src_service = PROFILE_SERVICES[target]
    src_pw = _read_password(src_service)
    if not src_pw:
        return {"changed": False, "reason": f"profile not staged: {target}", "profile": current_profile()}

    cur_pw = _read_password(ACTIVE_SERVICE)
    if cur_pw == src_pw:
        return {"changed": False, "reason": "already on target", "profile": target}

    # 安全策: 現在の active credentials を、 判別できた profile 用 entry に退避し直す。
    # これで「個人で login し直して active を上書きしてから personal 退避してなかった」 ような
    # 状態でも、 切替時に自動で取り残し救済される。
    cur_profile = _profile_of(cur_pw)
    if cur_pw and cur_profile and cur_profile != target:
        backup_service = PROFILE_SERVICES[cur_profile]
        if _read_password(backup_service) != cur_pw:
            _write_password(backup_service, cur_pw)

    if not _write_password(ACTIVE_SERVICE, src_pw):
        return {"changed": False, "reason": "keychain write failed", "profile": cur_profile}

    return {"changed": True, "profile": target}
