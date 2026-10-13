"""タブごとのメモ (= 📋)。

真値は `USER_DIR/notes/<タブの id>.md` の 1 本で、 そのタブの持ち物 (= 他のタブからは見えず、
タブを消すと一緒に消える)。 画面はこの口から読み書きし、 そのタブのエージェントは環境変数
`PWA_NOTE` が指す同じ file を直に書く。 残したい物は、 エージェントに頼んで作業中の repo の側へ
移す (= ここは下書きの置き場で、 保存先ではない)。

空にしたメモは file ごと消す (= 空の file を溜めない)。
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from backend.config import FILE_SIZE_LIMIT
from backend.errors import raise_error
from backend.paths import note_path
from backend.routes.sessions import require_session
from backend.state import atomic_write_text

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sessions/{session_id}/note")
def get_note(session_id: str, _: str = Depends(require_session)):
    path = note_path(session_id)
    try:
        if path.stat().st_size > FILE_SIZE_LIMIT:
            raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
        content = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        content = ""
    return {"path": str(path), "content": content}


@router.put("/sessions/{session_id}/note")
def put_note(session_id: str, content: str = Body(..., embed=True), _: str = Depends(require_session)):
    path = note_path(session_id)
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
