"""チャットの添付ファイル保存 (uploads/tmp への退避 + セッション単位の追跡)。

PTY 経路では保存したファイルのパスを tmux send-keys で claude に渡し、 claude が
Read で読む。 ここはファイルの保存と uuid 命名だけを担当する。
"""
import logging
import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from backend.config import UPLOADS_TMP
from backend.state import session_tmp_files

logger = logging.getLogger(__name__)

# backend-F-59: 1 ファイルあたり 20 MiB 上限。 入口で fail-fast することで、 disk write を
# 走らせる前に拒否する (= 旧版は f.size を見ずに `await f.read()` で受け切ってから書き出して
# いたので、 攻撃的 client が 100 MB の multipart を投げると mem ピーク + disk 占有が起きた)。
# 上限は iPhone 写真 (= 数 MB) + 高解像度スクショを通すサイズに合わせる (= 1 MiB だと
# 常用画像が軒並み 413 で reject される事故が出たので 2026-06-21 緩和)。
FILE_SIZE_LIMIT = 20 * 1024 * 1024


async def save_to_tmp(files: list[UploadFile], session_id: str) -> list[dict]:
    """アップロードされたファイルを uploads/tmp に保存、 セッションごとに追跡。

    backend-F-59: 1 ファイル上限 FILE_SIZE_LIMIT (= 20 MiB)。 size が事前にわかる時は
    入口で fail-fast する (= 部分書き出し + cleanup を避ける)。 size が None の時 (= iOS
    Safari 等 multipart の Content-Length が per-part で来ない client) は read 後にバイト数
    で check する (= 旧実装は `if not f.size: continue` で size 不明の upload を silent skip
    していた = 画像が「成功した風」 で消える原因、 2026-06-22 fix)。
    """
    UPLOADS_TMP.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        # 事前 size がわかる時のみ早期 reject (= 大物 multipart で disk / mem を食い止める)。
        if f.size is not None and f.size > FILE_SIZE_LIMIT:
            raise HTTPException(
                status_code=413,
                detail=f"file too large: {f.filename!r} {f.size} bytes (limit {FILE_SIZE_LIMIT})",
            )
        data = await f.read()
        if not data:
            # 本当に 0 バイト (= ファイル選択ダイアログ空送信等)。 静かに skip。
            logger.info("save_to_tmp: skipping empty upload %r", f.filename)
            continue
        if len(data) > FILE_SIZE_LIMIT:
            raise HTTPException(
                status_code=413,
                detail=f"file too large: {f.filename!r} {len(data)} bytes (limit {FILE_SIZE_LIMIT})",
            )
        ext = Path(f.filename or "file").suffix or ""
        dest = UPLOADS_TMP / f"{uuid.uuid4().hex}{ext}"
        dest.write_bytes(data)
        session_tmp_files.setdefault(session_id, []).append(dest)
        saved.append({
            "name": f.filename or dest.name,
            "path": str(dest),
            "mime": f.content_type or mimetypes.guess_type(f.filename or "")[0] or "",
        })
    return saved
