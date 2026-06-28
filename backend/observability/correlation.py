"""correlation id (= W3C traceparent 互換 8 hex) の発行 + ContextVar 伝播。

W1 stub:
    - new_corr_id() で 8 hex 文字列を 1 つ生成
    - current_corr_id() は ContextVar から読み、 未設定なら新規発行 + set
    - bind_corr_id(corr_id) で明示的に context に貼る (= request middleware 想定、 W3 で本実装)

W3 本実装で増やす予定:
    - new_traceparent() で W3C trace context full format ("00-<32hex>-<16hex>-01")
    - HTTP middleware で `traceparent` header を読んで corr_id を抽出
    - asyncio task copy_context での伝播保証
    - SSE / WS pump で current_corr_id() を event envelope に注入する正規路 (W1 では routes.py 直書き)
"""
from __future__ import annotations

import secrets
from contextvars import ContextVar
from contextlib import contextmanager

_current: ContextVar[str | None] = ContextVar("corr_id", default=None)


def new_corr_id() -> str:
    """W3C trace-id 互換の 8 hex 文字列 (= 4 bytes 乱数の hex 表現)。

    1 接続 / 1 turn 等の論理単位ごとに 1 つ発行して全 layer に伝播する想定。
    32 hex フル trace-id への移行は W3。
    """
    return secrets.token_hex(4)


def current_corr_id() -> str:
    """現在 context の corr_id を返す。 未設定なら新規発行 + ContextVar に set。

    SSE / WS event envelope 付与の主入口。 frontend が `traceparent` header を投げてきた
    場合は HTTP middleware で bind_corr_id() しておくことで、 本関数は既存値を返す。
    """
    cur = _current.get()
    if cur is not None:
        return cur
    new = new_corr_id()
    _current.set(new)
    return new


def bind_corr_id(corr_id: str) -> None:
    """明示的に context に corr_id を貼る (= 上流 trace との結合用)。

    middleware や test fixture から使う想定。 同じ task / context 内で以降の current_corr_id()
    は本値を返す。
    """
    _current.set(corr_id)


@contextmanager
def corr_id_scope(corr_id: str | None = None):
    """`with corr_id_scope("abcd1234"):` で限定スコープ corr_id を貼り、 抜けると元に戻す。

    test や同期処理の境界で「この block 全部を 1 corr_id で trace」 したい時に。 None を渡すと
    新規発行。
    """
    token = _current.set(corr_id or new_corr_id())
    try:
        yield _current.get()
    finally:
        _current.reset(token)
