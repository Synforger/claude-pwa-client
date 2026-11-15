"""A tab's memo (= the 📋 file).

The memo is one file, `<tier folder>/pages/<tab id>/memo.md` (see `terminal/tab_memo.py` for how the folder
is chosen). The screen reads and writes it through these routes; the tab's agent writes the same file
directly, at the path in its `PWA_NOTE` variable. A tab with no memo reads as empty: the backend never writes
a memo template. The tab's top page (= `index.html` next to the memo) is made by the backend from the agent's
template when the tab's tier is recorded (`terminal/tab_page.py`); the read tells the screen where it is.

Emptying a memo deletes the file (= no empty files pile up). Other pages in the same folder are never touched.

The read answers the memo's version in an `ETag` header (= a hash of the file as it was read; a memo that is not
there has the version of an empty file). A write that carries it in `If-Match` is refused with 409 when the file
is not what was read any more, so a screen that opened an old copy cannot replace what the agent wrote since. A
write without `If-Match` goes through as it always did.
"""
import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response

from backend._common.config import FILE_SIZE_LIMIT
from backend._common.errors import raise_error
from backend.routes.sessions import require_session
from backend._common.state import atomic_write_text
from backend.terminal.tab_memo import memo_path
from backend.terminal.tab_page import existing_page

logger = logging.getLogger(__name__)
router = APIRouter()


def _version(raw: bytes) -> str:
    """The version of a memo whose bytes are `raw`, in the form of an `ETag` (= quoted)."""
    return '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'


def _memo_bytes(path: Path) -> bytes:
    """The file as it is now (= empty when the memo is not there)."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _read_memo(path: Path) -> tuple[str, str]:
    """The memo at `path` as text and its version, from one read of the file (= the version is of what the text
    came from). A memo that is not there is empty."""
    try:
        if path.stat().st_size > FILE_SIZE_LIMIT:
            raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    except FileNotFoundError:
        pass
    raw = _memo_bytes(path)
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return text, _version(raw)


@router.get("/sessions/{session_id}/note")
def get_note(response: Response, session_id: str, _: str = Depends(require_session)):
    path = memo_path(session_id)
    content, version = _read_memo(path)
    response.headers["ETag"] = version
    page = existing_page(session_id)
    return {"path": str(path), "content": content, "page": str(page) if page else None}


@router.put("/sessions/{session_id}/note")
def put_note(
    response: Response,
    session_id: str,
    content: str = Body(..., embed=True),
    if_match: str | None = Header(None),
    _: str = Depends(require_session),
):
    path = memo_path(session_id)
    if len(content.encode("utf-8")) > FILE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    if if_match is not None and if_match != _version(_memo_bytes(path)):
        raise_error(409, "note_changed", "メモが変わりました。開き直してください")
    try:
        if content == "":
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content)
    except Exception:
        logger.exception("failed to write note: %s", path)
        raise HTTPException(status_code=500, detail="Internal error")
    response.headers["ETag"] = _version(content.encode("utf-8"))
    return {"path": str(path), "content": content}
