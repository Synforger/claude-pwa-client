"""iPhone の画面の最後の 1 枚 (= app の画面の配信が 1 秒に 1 枚送る JPEG)。

持つのは最後の 1 枚だけ (= `screen.jpg` を置き換える)。 配信しているかは、 配信の始まりと終わりの知らせと、 最後に
届いた時刻から決める (= 終わりの知らせが届かずに切れても、 STALE_S 秒で配信していない扱いになる)。
"""
from __future__ import annotations

import time
from pathlib import Path

# 1 枚の上限 (= 長辺 1280px の JPEG は数百 KB。 桁違いの物は受けない)
MAX_BYTES = 5 * 1024 * 1024
# 最後の 1 枚がこれより古ければ、 配信していない扱い (= 送る間隔 1 秒の 5 倍)
STALE_S = 5.0


# 配信の仕方の既定 (= `backend/config.json` の `device_screen` で 1 つずつ変えられる。 app はこの値を持たず、
# 配信を始める時に GET /device/screen/settings で受け取る)
SETTINGS_DEFAULT = {
    "interval_s": 1.0,   # 1 枚を送る間隔 (秒)
    "max_side": 1280,    # 長辺の上限 (px)
    "quality": 0.6,      # JPEG の質 (= 0 より大きく 1 以下)
}


def settings(raw: object) -> dict:
    """設定の `device_screen` を既定に重ねる (= 型か範囲が違う値は捨てて既定を使う)。"""
    out = dict(SETTINGS_DEFAULT)
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if key not in out or isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            continue
        if key == "quality" and value > 1:
            continue
        out[key] = int(value) if key == "max_side" else float(value)
    return out


class NotJpeg(ValueError):
    """JPEG でない (= 頭の 2 バイトが FF D8 でない) か、 大きすぎる。"""


class ScreenStore:
    def __init__(self, files_dir: Path):
        self.path = files_dir / "screen.jpg"
        self._live = False

    def receive(self, data: bytes) -> dict:
        if len(data) > MAX_BYTES:
            raise NotJpeg(f"the frame is {len(data)} bytes; the limit is {MAX_BYTES}")
        if not data.startswith(b"\xff\xd8"):
            raise NotJpeg("the frame is not a JPEG")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jpg.tmp")
        tmp.write_bytes(data)
        tmp.replace(self.path)
        self._live = True
        return {"bytes": len(data)}

    def set_live(self, live: bool) -> None:
        self._live = live

    def status(self) -> dict:
        try:
            stat = self.path.stat()
        except OSError:
            return {"live": False, "path": None, "at": None, "age_s": None, "bytes": None}
        age = max(time.time() - stat.st_mtime, 0.0)
        return {"live": self._live and age < STALE_S, "path": str(self.path), "at": stat.st_mtime,
                "age_s": round(age, 1), "bytes": stat.st_size}
