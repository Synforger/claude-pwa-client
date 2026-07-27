"""SSE event type の三点整合 gate (= 2026-07-27 退役 audit の再発防止機構)。

3 つの真値が同じ event 集合を語っていることを機械照合する:
  1. 契約 yaml (= contracts/schema/sse-events.yaml の keys)
  2. 実装が実際に emit する type (= backend/jsonl/events.py + prompt_detector_loop の静的抽出)
  3. docs (= docs/internals/protocol/streams.md の event wire shape 表)

背景: `user` (tool_result) が実装と docs にあるのに yaml に無い /
`system(init)`・`request_id` が docs と yaml にあるのに実装が emit しない、 という
「片側にしか無い event」 が audit で 3 件見つかった。 集合一致を CI で強制する。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]

# yaml に定義があるが実装が意図的に emit しない封印 entry (= 追加時はここに理由を書く)。
#   - stop_hook_summary / away_summary: 型だけ予約済み (= test_jsonl_events が「emit されない」
#     ことを別途 assert している封印仕様)
SEALED_IN_YAML = {"stop_hook_summary", "away_summary"}

# frontend が自己注入する合成 event (= wire に乗らないので契約 yaml の対象外、 docs には載る)。
FRONTEND_SYNTHETIC = {"session_end"}


def _yaml_types() -> set[str]:
    doc = yaml.safe_load((REPO / "contracts/schema/sse-events.yaml").read_text())
    return set(doc["events"].keys())


def _emitted_types() -> set[str]:
    """実装の emit を静的抽出する。 `"type": "<x>"` literal を emit 箇所とみなす。"""
    out: set[str] = set()
    for rel in ("backend/jsonl/events.py",):
        src = (REPO / rel).read_text()
        out |= set(re.findall(r'"type": "([a-z_]+)"', src))
    # prompt_state は detector loop が合成する (= jsonl 由来でない唯一の常設 event)
    src = (REPO / "backend/terminal/prompt_detector_loop.py").read_text()
    if re.search(r'"prompt_state"', src):
        out.add("prompt_state")
    return out


def _docs_types() -> set[str]:
    """streams.md の「event wire shape」 セクションの表からのみ抽出する
    (= 他セクションの field 表 / endpoint 表を event と誤認しない)。"""
    text = (REPO / "docs/internals/protocol/streams.md").read_text()
    start = text.index("## event wire shape")
    section = text[start:]
    nxt = re.search(r"\n## (?!event wire shape)", section)
    if nxt:
        section = section[: nxt.start()]
    # 「### 共通フィールド」 節は field 名の表 (= type/uuid 等) なので event 抽出から除外
    m = re.search(r"### 共通フィールド.*?(?=\n### )", section, re.S)
    if m:
        section = section[: m.start()] + section[m.end():]
    out: set[str] = set()
    for line in section.splitlines():
        m = re.match(r"\| `([a-z_]+)` \| ", line.strip())
        if m:
            out.add(m.group(1))
    return out


def test_yaml_matches_implementation():
    yaml_types = _yaml_types()
    emitted = _emitted_types()
    missing_in_yaml = emitted - yaml_types
    assert not missing_in_yaml, (
        f"実装が emit するのに契約 yaml に無い event: {sorted(missing_in_yaml)} "
        "(= contracts/schema/sse-events.yaml に追記して codegen を回す)")
    dead_in_yaml = yaml_types - emitted - SEALED_IN_YAML
    assert not dead_in_yaml, (
        f"契約 yaml にあるのに実装が emit しない event: {sorted(dead_in_yaml)} "
        "(= 実装するか、 yaml から削るか、 封印仕様なら SEALED_IN_YAML に理由付きで登録)")


def test_docs_table_is_subset_of_yaml():
    """docs 表の event は全部 yaml に居る (= docs だけの幽霊 event を禁止)。

    表には event 以外の行 (= endpoint 表等) も混ざり得るので、 docs ⊆ yaml 方向のみ検査し、
    抽出の過剰 hit は yaml 非掲載として即 fail で気付く。"""
    docs = _docs_types()
    yaml_types = _yaml_types()
    ghosts = {d for d in docs if d not in yaml_types} - FRONTEND_SYNTHETIC
    assert not ghosts, (
        f"docs (streams.md) に載っているが契約 yaml に無い event/型: {sorted(ghosts)} "
        "(= 実在しないなら docs から削除、 実在するなら yaml へ)")


def test_yaml_event_types_documented():
    """yaml の event は docs 表にも載っている (= 契約だけの隠し event を禁止)。"""
    docs = _docs_types()
    yaml_types = _yaml_types()
    undocumented = yaml_types - docs - SEALED_IN_YAML
    assert not undocumented, (
        f"契約 yaml にあるが docs (streams.md) の表に無い event: {sorted(undocumented)}")
