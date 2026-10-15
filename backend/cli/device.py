#!/usr/bin/env python3
"""cpc device: この Mac の backend を通して、 iPhone の app に操作を頼む (= 標準の部品だけで動く)。

    cpc device                               つながっているかと、 できる操作の一覧
    cpc device <種類>                        その種類の操作と引数
    cpc device <種類> <操作> [--<引数> <値> ...] [--json '{...}'] [--timeout <秒>]
                                             操作を 1 つ頼み、 答えを JSON で出す

操作の一覧の真値は app の中にある (= app がつないだ時に送り、 backend が控える)。 引数の型は一覧に従って
直す (= int / number / bool / json、 それ以外は文字のまま)。 backend の場所は CPC_URL (= 既定
http://127.0.0.1:8765)。

終わりの番号: 0 = 答えた / 2 = 書き方が違う / 3 = app がつながっていない / 4 = 一覧に無い操作 /
5 = 時間切れ / 6 = app ができなかった / 7 = backend に届かない
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("CPC_URL", "http://127.0.0.1:8765").rstrip("/")
EXIT = {"usage": 2, "offline": 3, "unknown": 4, "timeout": 5, "failed": 6, "unreachable": 7}
_HTTP_EXIT = {503: "offline", 404: "unknown", 504: "timeout", 502: "failed", 400: "usage"}


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


def main(argv: list[str]) -> int:
    try:
        if not argv or argv[0] in ("-h", "--help"):
            print(_show_all(_catalog()))
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
