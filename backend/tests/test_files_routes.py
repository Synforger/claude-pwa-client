"""files_routes.py の _resolve_safe (= path injection 防御) の unit test。"""
import pytest
from fastapi import HTTPException

from config import HOME
from files_routes import _resolve_safe


def test_resolve_safe_inside_home():
    # 意図: HOME 配下のパスは resolve されてそのまま返る
    p = _resolve_safe(str(HOME / "x" / "y"))
    assert str(p).startswith(str(HOME))


def test_resolve_safe_tilde_expansion():
    # 意図: "~/foo" は HOME 配下に展開される
    p = _resolve_safe("~/foo.txt")
    assert p == HOME / "foo.txt"


def test_resolve_safe_outside_home_raises():
    # 意図: /etc/passwd 等 HOME 外は 403 (path injection 防御)
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe("/etc/passwd")
    assert exc_info.value.status_code == 403


def test_resolve_safe_dotdot_escape_raises():
    # 意図: HOME 配下から .. で抜けようとしても resolve 後の prefix 判定で止まる
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe(str(HOME) + "/../../etc")
    assert exc_info.value.status_code == 403


# --- deny list (= 秘密ファイルの読み書き阻止) ---

@pytest.mark.parametrize("path", [
    "~/.ssh/id_rsa",
    "~/.ssh/authorized_keys",
    "~/.ssh/config",
    "~/.aws/credentials",
    "~/.gnupg/private-keys-v1.d",
    "~/.kube/config",
    "~/.docker/config.json",
    "~/.netrc",
    "~/.zshrc",
    "~/.zshenv",
    "~/.bashrc",
    "~/.bash_profile",
    "~/.zsh_history",
    "~/.bash_history",
    "REDACTED_PATH/work/key.pem",
    "REDACTED_PATH",
    "~/something/id_ed25519",
    "REDACTED_PATH/gh/hosts.yml",
])
def test_resolve_safe_denies_secret_paths(path):
    # 意図: SSH 鍵 / クラウド認証 / シェル rc / 履歴 / 証明書 は 403 で拒否される
    with pytest.raises(HTTPException) as exc_info:
        _resolve_safe(path)
    assert exc_info.value.status_code == 403


def test_resolve_safe_allows_ordinary_paths():
    # 意図: deny list に当たらない通常 path は通過する
    p = _resolve_safe(str(HOME / "repos" / "myproj" / "README.md"))
    assert str(p).endswith("README.md")
