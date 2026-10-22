"""変換した頁の画像の控えと、 変換の待ちの状態。

控えは `<置き場>/<key>/` (= `p-001.jpg` … と `meta.json`)。 key は元の file の実体の path・大きさ・更新時刻と
変換の条件から決まるので、 元の中身が変わると別の key になり、 前の控えは使われない (= 同じ path の古い控えは、
新しい控えができた時に消す)。 置き場の大きさが上限を超えたら、 最後に開かれてから長い順に消す。

変換は時間が掛かるので、 要求した頁は待たせず別の thread で走らせ、 画面は `running` を見て自分で更新し直す。
同じ file の要求が重なっても変換は 1 回 (= key ごとに 1 つの job)。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from backend._common.config import documents_settings
from backend.documents import convert

logger = logging.getLogger(__name__)

# 変換の条件を変えたら上げる (= 前の条件で作った控えを使わない)
RENDER_VERSION = 1
# 同時に走らせる変換の数 (= soffice は重いので 2 本まで。 3 本目以降は順番を待つ)
CONVERT_WORKERS = 2
# 失敗の記憶を持ち続ける時間 (= 超えたら、 同じ file をまた開いた時に最初から試す)
FAILURE_MEMORY_SEC = 3600
# 途中で止まった変換の作業 folder が残っていた時、 これより古い物だけ片付ける (= 別の process が作業中かもしれない)
STALE_WORK_SEC = 3600


@dataclass
class Page:
    width: int
    height: int


@dataclass
class Entry:
    key: str
    directory: Path
    pages: list[Page]

    def image(self, number: int) -> Path:
        return self.directory / f"p-{number:03d}.jpg"


@dataclass
class Job:
    started: float = field(default_factory=time.monotonic)
    phase: str = "start"
    error: convert.ConversionError | None = None


@dataclass
class Status:
    """`ready` (= entry が在る) / `running` (= phase と経過) / `failed` (= error)。"""
    state: str
    entry: Entry | None = None
    phase: str = "start"
    elapsed: float = 0.0
    error: convert.ConversionError | None = None


def cache_key(source: Path) -> str:
    st = source.stat()
    material = f"{RENDER_VERSION}\0{convert.DPI}\0{convert.JPEG_QUALITY}\0{source}\0{st.st_size}\0{st.st_mtime_ns}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


class DocumentStore:
    def __init__(self, cache_dir: Path, max_bytes: int, executor: Executor | None = None):
        self.cache_dir = cache_dir
        self.max_bytes = max_bytes
        self._executor = executor or ThreadPoolExecutor(max_workers=CONVERT_WORKERS, thread_name_prefix="doc-convert")
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._clean_work_folders()

    # ---- 問い合わせ

    def status(self, source: Path, retry: bool = False) -> Status:
        """控えが在れば ready。 無ければ変換を始め (= 既に走っていれば相乗り)、 running か failed を返す。"""
        key = cache_key(source)
        entry = self._entry(key)
        if entry is not None:
            self._touch(entry)
            return Status("ready", entry=entry)
        with self._lock:
            job = self._jobs.get(key)
            started = job is None or (job.error is not None and (retry or self._forgotten(job)))
            if started:
                job = self._jobs[key] = Job()
        if started:
            self._executor.submit(self._build, key, source, job)
        if job.error is not None:
            return Status("failed", error=job.error)
        return Status("running", phase=job.phase, elapsed=time.monotonic() - job.started)

    def _forgotten(self, job: Job) -> bool:
        return time.monotonic() - job.started > FAILURE_MEMORY_SEC

    # ---- 控え

    def _entry(self, key: str) -> Entry | None:
        directory = self.cache_dir / key
        try:
            meta = json.loads((directory / "meta.json").read_text())
            pages = [Page(int(w), int(h)) for w, h in meta["pages"]]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        entry = Entry(key, directory, pages)
        if not pages or not all(entry.image(n).is_file() for n in range(1, len(pages) + 1)):
            return None
        return entry

    @staticmethod
    def _touch(entry: Entry) -> None:
        """最後に開かれた時刻を新しくする (= 上限を超えた時に、 長く開かれていない控えから消すため)。"""
        try:
            os.utime(entry.directory / "meta.json")
        except OSError:
            logger.debug("could not touch %s", entry.directory, exc_info=True)

    # ---- 変換

    def _build(self, key: str, source: Path, job: Job) -> None:
        work = self.cache_dir / f".work-{uuid.uuid4().hex}"
        try:
            work.mkdir(parents=True)
            sizes = convert.render_pages(source, work, lambda phase: setattr(job, "phase", phase))
            total = sum(page.stat().st_size for page in work.glob("p-*.jpg"))
            (work / "meta.json").write_text(json.dumps({
                "source": str(source), "pages": sizes, "bytes": total, "version": RENDER_VERSION,
            }))
            final = self.cache_dir / key
            shutil.rmtree(final, ignore_errors=True)
            os.replace(work, final)
            with self._lock:
                self._jobs.pop(key, None)
            self._prune(keep=key, source=source)
        except convert.ConversionError as error:
            job.error = error
        except Exception:
            logger.exception("document conversion failed: %s", source)
            job.error = convert.ConversionError("failed")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ---- 片付け

    def _clean_work_folders(self) -> None:
        if not self.cache_dir.is_dir():
            return
        now = time.time()
        for work in self.cache_dir.glob(".work-*"):
            try:
                if now - work.stat().st_mtime > STALE_WORK_SEC:
                    shutil.rmtree(work, ignore_errors=True)
            except OSError:
                logger.debug("could not inspect %s", work, exc_info=True)

    def _prune(self, keep: str, source: Path) -> None:
        """同じ file の古い控えと、 上限を超えた分 (= 最後に開かれてから長い順) を消す。 今作った控えは残す。"""
        entries: list[tuple[float, int, Path]] = []
        for directory in self.cache_dir.iterdir():
            if directory.name.startswith(".") or not directory.is_dir():
                continue
            meta_path = directory / "meta.json"
            try:
                meta = json.loads(meta_path.read_text())
                touched = meta_path.stat().st_mtime
                size = int(meta.get("bytes", 0))
            except (OSError, ValueError, TypeError):
                shutil.rmtree(directory, ignore_errors=True)  # meta の無い物は途中で壊れた控え
                continue
            if directory.name != keep and meta.get("source") == str(source):
                shutil.rmtree(directory, ignore_errors=True)
                continue
            entries.append((touched, size, directory))
        total = sum(size for _, size, _ in entries)
        for _, size, directory in sorted(entries):
            if total <= self.max_bytes:
                break
            if directory.name == keep:
                continue
            shutil.rmtree(directory, ignore_errors=True)
            total -= size


_store: DocumentStore | None = None
_store_lock = threading.Lock()


def get_store() -> DocumentStore:
    """設定の置き場と上限で作った控え (= 設定が変わったら作り直す)。"""
    global _store
    cache_dir, max_bytes = documents_settings()
    with _store_lock:
        if _store is None or (_store.cache_dir, _store.max_bytes) != (cache_dir, max_bytes):
            _store = DocumentStore(cache_dir, max_bytes)
        return _store
