"""backend/errors.py の raise_error 動作を担保する unit test。 detail が
{code, message, params?} 形の dict になっていることが frontend の translateHttpErrorDetail
が code lookup できる前提。"""
import pytest
from fastapi import HTTPException

from backend.errors import raise_error


def test_raise_error_basic_shape():
    with pytest.raises(HTTPException) as ei:
        raise_error(400, "some_code", "日本語 fallback")
    exc = ei.value
    assert exc.status_code == 400
    assert exc.detail == {"code": "some_code", "message": "日本語 fallback"}


def test_raise_error_with_params_appended():
    with pytest.raises(HTTPException) as ei:
        raise_error(413, "file_too_large", "ファイルが大きすぎます", limit="1MB")
    exc = ei.value
    assert exc.status_code == 413
    assert exc.detail == {
        "code": "file_too_large",
        "message": "ファイルが大きすぎます",
        "params": {"limit": "1MB"},
    }


def test_raise_error_omits_params_when_empty():
    """params が無い場合は key ごと省略 (frontend translateHttpErrorDetail は無ければ空 dict 扱い)。"""
    with pytest.raises(HTTPException) as ei:
        raise_error(400, "invalid_agent_id", "agent_id が無効です")
    assert "params" not in ei.value.detail
