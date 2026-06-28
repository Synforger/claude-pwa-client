#!/usr/bin/env python
"""yaml schema (= sse-events / ws-channels / http-endpoints) から pydantic v2 model を生成する。

設計判断:
    - datamodel-code-generator は OpenAPI / JSON Schema 入力前提で自前 yaml に不適合、 自前 codegen で書く。
    - 出力先: --out で指定、 デフォルトは contracts/_generated/ (= 中立)。 backend に配置するのは Phase 3。
    - 全 model は pydantic v2 BaseModel、 extra='forbid' (= contract drift 検知)。

使い方:
    python codegen/gen-python.py                     # contracts/_generated/ に書き出し
    python codegen/gen-python.py --out ../backend/jsonl --only events  # backend に events のみ
    python codegen/gen-python.py --check             # 既存出力との diff のみ、 書き換えない (= CI gate)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required: pip install pyyaml\n")
    sys.exit(2)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "_generated"

HEADER = '''"""GENERATED FILE — do not edit by hand.

Source: contracts/schema/{src}
Generator: contracts/codegen/gen-python.py
Regenerate: cd contracts && python codegen/gen-python.py
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field
'''


def to_pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-]", name) if part)


def py_type_of(schema: dict[str, Any], nested_models: list[str]) -> str:
    """yaml field schema → python type 表記。 nested object は別 model に分けず inline dict[str, Any] で。"""
    if "const" in schema:
        v = schema["const"]
        if isinstance(v, str):
            return f'Literal["{v}"]'
        return f"Literal[{v!r}]"
    if "enum" in schema:
        opts = ", ".join(f'"{v}"' if isinstance(v, str) else repr(v) for v in schema["enum"])
        return f"Literal[{opts}]"
    if "oneOf" in schema or "anyOf" in schema:
        variants = schema.get("oneOf") or schema.get("anyOf") or []
        types = [py_type_of(v, nested_models) for v in variants]
        return f"Union[{', '.join(types)}]"
    t = schema.get("type")
    if t == "string":
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "array":
        item = py_type_of(schema.get("items") or {}, nested_models)
        return f"list[{item}]"
    if t == "object":
        return "dict[str, Any]"
    if t == "null":
        return "None"
    return "Any"


def emit_model(class_name: str, schema: dict[str, Any], description: str = "") -> str:
    """object schema (= type=object + properties + required) を pydantic BaseModel 文字列にする。"""
    required = set(schema.get("required") or [])
    props = schema.get("properties") or {}
    additional = schema.get("additionalProperties")
    extra_policy = "forbid" if additional is False else ("allow" if additional is True else "ignore")

    lines = [f"class {class_name}(BaseModel):"]
    if description:
        lines.append(f'    """{description}"""')
    lines.append(f'    model_config = ConfigDict(extra="{extra_policy}")')

    if not props:
        lines.append("    pass")
        return "\n".join(lines) + "\n"

    for fname, fschema in props.items():
        ftype = py_type_of(fschema, [])
        nullable = bool(fschema.get("nullable"))
        is_required = fname in required
        if not is_required or nullable:
            ftype = f"Optional[{ftype}]"
            default = " = None"
        else:
            default = ""
        desc = fschema.get("description", "")
        if desc:
            lines.append(f"    {fname}: {ftype}{default}  # {desc}")
        else:
            lines.append(f"    {fname}: {ftype}{default}")
    return "\n".join(lines) + "\n"


def gen_events(src_yaml: Path) -> str:
    doc = yaml.safe_load(src_yaml.read_text())
    out = [HEADER.format(src=src_yaml.name)]
    out.append(f'\nSCHEMA_VERSION = "{doc["schema_version"]}"\n')

    type_literals = []
    classes = []
    for name, ev in (doc.get("events") or {}).items():
        class_name = to_pascal(name) + "Event"
        type_literals.append((name, class_name))
        # type field をモデルに明示的に足す (= Literal で event 種別を縛る)
        # 元 schema は type を properties に含まない (= envelope の外で扱う) が、 frontend が
        # event.type で分岐するため codegen 出力では含める。
        schema = dict(ev)
        schema["properties"] = {"type": {"const": name}, **(ev.get("properties") or {})}
        schema["required"] = ["type", *(ev.get("required") or [])]
        classes.append(emit_model(class_name, schema, description=ev.get("description", "")))

    out.append("\n\n")
    out.append("\n\n".join(classes))
    # Union 型 (= 全 event の判別 union)
    if type_literals:
        union = ", ".join(c for _, c in type_literals)
        out.append(f"\n\nAnyEvent = Union[{union}]\n")
        # type → class mapping (= dispatch table)
        out.append("\nEVENT_BY_TYPE: dict[str, type[BaseModel]] = {\n")
        for tname, cname in type_literals:
            out.append(f'    "{tname}": {cname},\n')
        out.append("}\n")
    return "".join(out)


def gen_ws_channels(src_yaml: Path) -> str:
    doc = yaml.safe_load(src_yaml.read_text())
    out = [HEADER.format(src=src_yaml.name)]
    out.append(f'\nSCHEMA_VERSION = "{doc["schema_version"]}"\n\n')

    for ch_name, ch in (doc.get("channels") or {}).items():
        prefix = to_pascal(ch_name)
        for direction in ("client_to_server", "server_to_client"):
            for idx, frame in enumerate(ch.get(direction) or []):
                schema = frame.get("schema")
                if not schema:
                    continue
                # oneOf の variant ごとに sub-class 生成、 最終的に Union[...]
                base_name = f"{prefix}{to_pascal(direction)}{idx}"
                if "oneOf" in schema:
                    variant_classes = []
                    for vi, variant in enumerate(schema["oneOf"]):
                        cname = f"{base_name}V{vi}"
                        variant_classes.append(cname)
                        out.append(emit_model(cname, variant))
                        out.append("\n\n")
                    union = ", ".join(variant_classes)
                    out.append(f"{base_name} = Union[{union}]\n\n")
                elif schema.get("type") == "object":
                    out.append(emit_model(base_name, schema))
                    out.append("\n\n")
    return "".join(out)


def gen_http_endpoints(src_yaml: Path) -> str:
    doc = yaml.safe_load(src_yaml.read_text())
    out = [HEADER.format(src=src_yaml.name)]
    out.append(f'\nSCHEMA_VERSION = "{doc["schema_version"]}"\n\n')

    for ep in (doc.get("endpoints") or []):
        # endpoint id を method + path から組み立て、 path は word 化
        method = ep["method"].lower()
        # /sessions/{sid}/fork → SessionsSidFork
        path_words = re.findall(r"[a-zA-Z0-9]+", ep["path"])
        ep_name = to_pascal("_".join(path_words))
        prefix = f"{to_pascal(method)}{ep_name}"

        if ep.get("request_body") and ep["request_body"].get("type") == "object":
            out.append(emit_model(f"{prefix}Request", ep["request_body"], description=f"{method.upper()} {ep['path']} request body"))
            out.append("\n\n")
        if ep.get("response") and ep["response"].get("type") == "object":
            out.append(emit_model(f"{prefix}Response", ep["response"], description=f"{method.upper()} {ep['path']} response"))
            out.append("\n\n")
        elif ep.get("response") and ep["response"].get("type") == "array":
            item = ep["response"].get("items") or {}
            if item.get("type") == "object":
                out.append(emit_model(f"{prefix}ResponseItem", item, description=f"{method.upper()} {ep['path']} response[i]"))
                out.append("\n\n")
    return "".join(out)


GENERATORS = {
    "events": ("sse-events.yaml", "events.py", gen_events),
    "ws_channels": ("ws-channels.yaml", "ws_channels.py", gen_ws_channels),
    "http_endpoints": ("http-endpoints.yaml", "http_endpoints.py", gen_http_endpoints),
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (default: contracts/_generated/)")
    p.add_argument("--only", choices=list(GENERATORS.keys()), action="append", help="generate only specified module (repeatable)")
    p.add_argument("--check", action="store_true", help="compare with existing output, exit 1 if differ (= CI gate)")
    args = p.parse_args()

    targets = args.only or list(GENERATORS.keys())
    args.out.mkdir(parents=True, exist_ok=True)

    differ = 0
    for key in targets:
        yaml_name, py_name, gen_fn = GENERATORS[key]
        src = SCHEMA_DIR / yaml_name
        if not src.exists():
            sys.stderr.write(f"SKIP {key}: {src} not found\n")
            continue
        content = gen_fn(src)
        out_path = args.out / py_name
        if args.check:
            existing = out_path.read_text() if out_path.exists() else ""
            if existing != content:
                sys.stderr.write(f"DIFF {out_path} differs from regenerated content\n")
                differ += 1
            else:
                print(f"OK   {out_path} matches")
        else:
            out_path.write_text(content)
            print(f"WROTE {out_path}")

    if args.check and differ > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
