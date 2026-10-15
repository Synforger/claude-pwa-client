#!/usr/bin/env python3
"""cpc device: この Mac の backend を通して、 iPhone の app に操作を頼む (= 標準の部品だけで動く)。

    cpc device                               つながっているかと、 できる操作の一覧
    cpc device <種類>                        その種類の操作と引数
    cpc device <種類> <操作> [--<引数> <値> ...] [--json '{...}'] [--timeout <秒>]
                                             操作を 1 つ頼み、 答えを JSON で出す
    cpc device screen                        iPhone の画面の最後の 1 枚の在処と、 配信しているか
                                             (= app の操作ではなく backend が持つ物。 配信は iPhone の画面収録で始める)
    cpc device screenshot [--out <png>] [--device <UDID>]
                                             今の iPhone の画面を、 この Mac が撮って file にする (= 前に出ている
                                             app が何でも撮れる。 Xcode の devicectl を使い、 iPhone がこの Mac と
                                             同じ網に居る間だけ。 app も backend も通さない)

操作の一覧の真値は app の中にある (= app がつないだ時に送り、 backend が控える)。 引数の型は一覧に従って
直す (= int / number / bool / json、 それ以外は文字のまま)。 backend の場所は CPC_URL (= 既定
http://127.0.0.1:8765)。

終わりの番号: 0 = 答えた / 2 = 書き方が違う / 3 = app がつながっていない (= screenshot は iPhone に届かない) /
4 = 一覧に無い操作 / 5 = 時間切れ / 6 = app ができなかった / 7 = backend に届かない

screenshot の iPhone は、 この Mac と対になっている実機が 1 台ならそれ (= 複数なら --device か CPC_DEVICE で
UDID を渡す)。 撮った file は backend の写真の取り出しと同じ所 (= CPC_DATA_DIR、 既定 backend/data の
device-files/) に置き、 path を JSON で出す。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = os.environ.get("CPC_URL", "http://127.0.0.1:8765").rstrip("/")
EXIT = {"usage": 2, "offline": 3, "unknown": 4, "timeout": 5, "failed": 6, "unreachable": 7}
_HTTP_EXIT = {503: "offline", 404: "unknown", 504: "timeout", 502: "failed", 400: "usage"}
FILES_DIR = Path(os.environ.get("CPC_DATA_DIR") or Path(__file__).resolve().parents[1] / "data") / "device-files"
# 撮るのを待つ上限 (秒)。 届く iPhone なら 2〜3 秒で返る
SCREENSHOT_TIMEOUT_S = 60


class Stop(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _request(method: str, path: str, body: dict | None = None, timeout: float = 600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read() or b"null")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read() or b"{}").get("detail")
        except ValueError:
            detail = None
        raise Stop(_HTTP_EXIT.get(error.code, "failed"), json.dumps(detail, ensure_ascii=False)
                   if not isinstance(detail, str) else detail) from error
    except urllib.error.URLError as error:
        raise Stop("unreachable", f"the backend at {URL} did not answer: {error.reason}") from error


def _catalog() -> dict:
    try:
        return _request("GET", "/device/catalog")
    except Stop as stop:
        if stop.kind == "unknown":   # (= その backend に口が無い)
            raise Stop("unreachable", f"the backend at {URL} has no /device (it needs updating)") from stop
        raise


def _by_type(catalog: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for op in catalog:
        kind, _, _ = str(op.get("name")).partition(".")
        grouped.setdefault(kind, []).append(op)
    return grouped


def _show_all(status: dict) -> str:
    head = (f"connected: {status.get('device')} (app {status.get('app')})" if status.get("connected")
            else "not connected (the app connects while a call is on or while it is open); "
                 "the list below is the last one it sent")
    lines = [head, ""]
    for kind, ops in sorted(_by_type(status.get("catalog") or []).items()):
        lines.append(f"{kind}")
        for op in ops:
            name = str(op["name"]).partition(".")[2]
            lines.append(f"  {name:<16} [{op.get('kind', '?')}] {op.get('summary', '')}")
    lines += ["", "cpc device <type> for the arguments of each operation"]
    return "\n".join(lines)


def _show_type(status: dict, kind: str) -> str:
    ops = _by_type(status.get("catalog") or []).get(kind)
    if not ops:
        raise Stop("unknown", f"no operations for '{kind}' (cpc device lists them)")
    lines = []
    for op in ops:
        flags = " (opens the app on screen)" if op.get("foreground") else ""
        lines.append(f"{op['name']} [{op.get('kind', '?')}] {op.get('summary', '')}{flags}")
        for param in op.get("params") or []:
            need = "required" if param.get("required") else "optional"
            lines.append(f"  --{param['name']} <{param.get('type', 'string')}> {need}: {param.get('description', '')}")
    return "\n".join(lines)


def _convert(value: str, kind: str):
    try:
        if kind == "int":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "bool":
            if value.lower() in ("true", "yes", "1"):
                return True
            if value.lower() in ("false", "no", "0"):
                return False
            raise ValueError(value)
        if kind == "json":
            return json.loads(value)
    except ValueError as error:
        raise Stop("usage", f"'{value}' is not a {kind}") from error
    return value


def _args(rest: list[str], spec: dict | None) -> tuple[dict, float | None]:
    types = {p["name"]: p.get("type", "string") for p in (spec or {}).get("params") or []}
    args: dict = {}
    timeout = None
    i = 0
    while i < len(rest):
        flag = rest[i]
        if not flag.startswith("--") or i + 1 >= len(rest):
            raise Stop("usage", f"expected --<name> <value>, got '{flag}'")
        name, value = flag[2:], rest[i + 1]
        if name == "json":
            extra = _convert(value, "json")
            if not isinstance(extra, dict):
                raise Stop("usage", "--json takes an object")
            args.update(extra)
        elif name == "timeout":
            timeout = float(_convert(value, "number"))
        else:
            args[name.replace("-", "_")] = _convert(value, types.get(name.replace("-", "_"), "string"))
        i += 2
    return args, timeout


def _devicectl(args: list[str]) -> subprocess.CompletedProcess:
    """Xcode の devicectl を 1 回呼ぶ (= 終わりの番号と出力を返す)。"""
    try:
        return subprocess.run(["xcrun", "devicectl", *args], capture_output=True, text=True,
                              timeout=SCREENSHOT_TIMEOUT_S, check=False)
    except FileNotFoundError:
        raise Stop("failed", "this Mac has no xcrun (screenshot needs Xcode)") from None
    except subprocess.TimeoutExpired:
        raise Stop("timeout", f"the iPhone did not answer within {SCREENSHOT_TIMEOUT_S} s") from None


def _the_iphone() -> str:
    """この Mac と対になっている実機の iPhone の UDID (= 1 台だけの時)。"""
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "devices.json"
        done = _devicectl(["list", "devices", "--quiet", "--json-output", str(listing)])
        if done.returncode != 0 or not listing.exists():
            raise Stop("failed", f"devicectl could not list devices: {(done.stderr or done.stdout).strip()[-300:]}")
        devices = json.loads(listing.read_text()).get("result", {}).get("devices", [])
    udids = [d["hardwareProperties"]["udid"] for d in devices
             if d.get("hardwareProperties", {}).get("reality") == "physical"
             and d.get("hardwareProperties", {}).get("platform") == "iOS"
             and d.get("connectionProperties", {}).get("pairingState") == "paired"]
    if not udids:
        raise Stop("offline", "no iPhone is paired with this Mac")
    if len(udids) > 1:
        raise Stop("usage", f"several iPhones are paired; pass --device <UDID> or set CPC_DEVICE: {', '.join(udids)}")
    return udids[0]


def _screenshot(rest: list[str]) -> dict:
    """今の iPhone の画面を、 この Mac が撮って file にする。"""
    options: dict[str, str] = {}
    while rest:
        if rest[0] not in ("--out", "--device") or len(rest) < 2:
            raise Stop("usage", "usage: cpc device screenshot [--out <png>] [--device <UDID>]")
        options[rest[0][2:]] = rest[1]
        rest = rest[2:]
    device = options.get("device") or os.environ.get("CPC_DEVICE") or _the_iphone()
    out = Path(options["out"]) if "out" in options else FILES_DIR / time.strftime("%Y%m%d-%H%M%S-screenshot.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    done = _devicectl(["device", "capture", "screenshot", "--device", device, "--destination", str(out), "--quiet"])
    if done.returncode != 0 or not out.exists():
        reason = (done.stderr or done.stdout).strip().splitlines()
        raise Stop("offline", "the Mac could not reach the iPhone (it has to be on the same network as this Mac): "
                   + (reason[-1] if reason else f"devicectl ended with {done.returncode}"))
    return {"path": str(out), "bytes": out.stat().st_size, "device": device}


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] in ("-h", "--help"):
            print(_show_all(_catalog()))
            return 0
        if argv[0] == "screen":
            print(json.dumps(_request("GET", "/device/screen"), ensure_ascii=False, indent=2))
            return 0
        if argv[0] == "screenshot":
            print(json.dumps(_screenshot(argv[1:]), ensure_ascii=False, indent=2))
            return 0
        if len(argv) == 1 or argv[1] in ("-h", "--help"):
            print(_show_type(_catalog(), argv[0]))
            return 0
        op = f"{argv[0]}.{argv[1]}"
        status = _catalog()
        spec = next((o for o in status.get("catalog") or [] if o.get("name") == op), None)
        args, timeout = _args(argv[2:], spec)
        body = {"op": op, "args": args, **({"timeout_s": timeout} if timeout else {})}
        answer = _request("POST", "/device/ops", body)
        print(json.dumps(answer.get("result"), ensure_ascii=False, indent=2))
        return 0
    except Stop as stop:
        print(f"cpc device: {stop}", file=sys.stderr)
        return EXIT[stop.kind]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
