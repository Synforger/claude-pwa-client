"""backend の HTTPException を frontend の i18n dict と対にする発火ヘルパ。

frontend の `i18n/{ja,en}.json` に `backend.<code>` キーがあり、 各 error は placeholder 付き
テンプレート。 backend は machine-readable code + params のみ返し、 文字列組み立ては frontend
で行う (= locale 別 rendering は frontend の t() に一元化、 backend は locale 気にせず済む)。

detail は dict:
    {"code": "file_too_large", "message": "<JA fallback>", "params": {"limit": "1MB"}}

- `code`: 常に必要、 frontend が t(`backend.${code}`) で lookup する。
- `message`: **JA テキスト**を必ず入れる。 frontend の i18n dict に該当 key が無い / 旧 client
  で translate 経路を通っていない場合の生 fallback として。 JA を default に選んだ理由 =
  従来クライアントの期待挙動が JA そのまま表示、 互換性を切らない。
- `params`: あれば frontend で placeholder 補間、 無ければ省略可。
"""
from __future__ import annotations

from fastapi import HTTPException


def raise_error(status_code: int, code: str, message: str, **params) -> None:
    """`HTTPException(status_code, detail={code, message, params?})` を統一的に raise する。

    使い方:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
        raise_error(400, "invalid_agent_id", "agent_id が無効です")
    """
    detail: dict = {"code": code, "message": message}
    if params:
        detail["params"] = params
    raise HTTPException(status_code=status_code, detail=detail)
