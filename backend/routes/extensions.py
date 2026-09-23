"""拡張 (= 別 repo のアプリ) の一覧 endpoint。

- GET /extensions : config.json の `extensions` を検証済みの形で返す

本体は拡張の中身を知らない。 返すのは名前・アイコン・置き場 (= `/ext/<id>/`) だけで、
拡張への経路は Tailscale Serve が持つ (= backend は proxy しない)。 届くかどうかの判定は
frontend が各 path に HEAD を投げて行う。
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.config import extensions

router = APIRouter()


@router.get("/extensions")
def list_extensions():
    """拡張の一覧を config の順で返す。 未設定なら空配列。"""
    return extensions()
