"""A tab's memo (= the 📋 file).

The memo is one file, `<tier folder>/pages/<tab id>/memo.md` (see `terminal/tab_memo.py` for how the folder
is chosen). The screen reads and writes it through these routes; the tab's agent writes the same file
directly, at the path in its `PWA_NOTE` variable. A tab with no memo reads as empty: the backend never writes
a memo template. The tab's top page (= `index.html` next to the memo) is made by the backend from the agent's
template when the tab's tier is recorded (`terminal/tab_page.py`); the read tells the screen where it is.

Emptying a memo deletes the file (= no empty files pile up). Other pages in the same folder are never touched.
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from backend._common.config import FILE_SIZE_LIMIT
from backend._common.errors import raise_error
from backend.routes.sessions import require_session
from backend._common.state import atomic_write_text
from backend.terminal.tab_memo import memo_path
from backend.terminal.tab_page import existing_page

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sessions/{session_id}/note")
def get_note(session_id: str, _: str = Depends(require_session)):
    path = memo_path(session_id)
    try:
        if path.stat().st_size > FILE_SIZE_LIMIT:
            raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
        content = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        content = ""
    page = existing_page(session_id)
    return {"path": str(path), "content": content, "page": str(page) if page else None}


@router.put("/sessions/{session_id}/note")
def put_note(session_id: str, content: str = Body(..., embed=True), _: str = Depends(require_session)):
    path = memo_path(session_id)
    if len(content.encode("utf-8")) > FILE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    try:
        if content == "":
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content)
    except Exception:
        logger.exception("failed to write note: %s", path)
        raise HTTPException(status_code=500, detail="Internal error")
    return {"path": str(path), "content": content}
