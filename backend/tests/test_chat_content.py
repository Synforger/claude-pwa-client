"""backend.chat_content の unit test。

backend-F-59: save_to_tmp 入口で FILE_SIZE_LIMIT (= 1 MiB) を fail-fast する。 入口検査
無し時代は `await f.read()` で全部 mem に load してから書き出していたので、 巨大 multipart
で mem ピーク + disk 占有が起きた。
"""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

import backend.chat_content as cc


def _run(coro):
    """asyncio.run() は走るたびに default loop を閉じて、 同 process 内で
    `asyncio.get_event_loop()` 経由で動く後続 test (= 旧式 deprecated API を使う
    test_fork など) を巻き添えで壊す。 個別 new_event_loop で隔離して、 後の
    `get_event_loop()` 経路を残しておく。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _upload(name: str, data: bytes, content_type: str = "text/plain") -> UploadFile:
    """テスト用 UploadFile を作る (= starlette は file size を自動算出)。"""
    headers = Headers({"content-type": content_type})
    return UploadFile(
        file=io.BytesIO(data),
        filename=name,
        size=len(data),
        headers=headers,
    )


def test_save_to_tmp_accepts_small_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "UPLOADS_TMP", tmp_path / "tmp")
    monkeypatch.setattr(cc, "session_tmp_files", {})
    files = [_upload("a.txt", b"hello", "text/plain")]
    saved = _run(cc.save_to_tmp(files, "ses_x"))
    assert len(saved) == 1
    assert saved[0]["name"] == "a.txt"


def test_save_to_tmp_rejects_oversize_file(tmp_path, monkeypatch):
    """1 MiB を超える file は入口で 413 拒否、 disk write 無し。"""
    monkeypatch.setattr(cc, "UPLOADS_TMP", tmp_path / "tmp")
    monkeypatch.setattr(cc, "session_tmp_files", {})
    big = b"x" * (cc.FILE_SIZE_LIMIT + 1)
    files = [_upload("big.bin", big, "application/octet-stream")]
    with pytest.raises(HTTPException) as exc:
        _run(cc.save_to_tmp(files, "ses_x"))
    assert exc.value.status_code == 413
    # disk に書かれていない (= tmp dir 無し or 空)
    tdir = tmp_path / "tmp"
    if tdir.exists():
        assert list(tdir.iterdir()) == []


def test_save_to_tmp_zero_size_is_skipped(tmp_path, monkeypatch):
    """size=0 (= 空アップロード) は skip して例外無し (= 旧挙動と同じ)。"""
    monkeypatch.setattr(cc, "UPLOADS_TMP", tmp_path / "tmp")
    monkeypatch.setattr(cc, "session_tmp_files", {})
    files = [_upload("empty.txt", b"", "text/plain")]
    saved = _run(cc.save_to_tmp(files, "ses_x"))
    assert saved == []
