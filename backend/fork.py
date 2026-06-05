"""会話フォーク (= 分岐) の純ロジック。

claude は 1 セッション = `~/.claude/projects/<cwd-hash>/<session_id>.jsonl` に追記し、
各 user/assistant 行は `uuid` ↔ `parentUuid` で鎖 (= 木) を作る。 「ここから分岐」 は、
ある行 (= from_uuid) を leaf として parentUuid を根まで遡り、 その lineage だけを残した
新セッションの jsonl を書き出すこと。 claude --resume <新 id> でその時点の会話を引き継いで
別方向に進める。 元セッションには一切触れない。

この module は file I/O を持たない純関数だけを置く (= 停止済みデータでテストできる)。
実際の書き出し・SessionDef 登録・spawn は chat_routes 側が組み立てる。
"""
import json

# claude が「会話の 1 発言」 として書く行 type。 これら以外 (queue-operation /
# last-prompt / summary 等のメタ行) は uuid 鎖を持たないので lineage 復元では使わない。
_MESSAGE_TYPES = ("user", "assistant")


def _parse_lines(source_lines: list[str]) -> list[dict]:
    """jsonl の各行を dict にする。 JSON でない行は捨てる (= 壊れた行で全体を落とさない)。"""
    out: list[dict] = []
    for raw in source_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _content_block_types(line: dict) -> list[str]:
    """message.content (str / list / None) からブロック type のリストを返す。 str や
    None は空 (= ブロック無し) 扱い。"""
    content = (line.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [b.get("type") for b in content if isinstance(b, dict)]


def _resolve_target(parsed: list[dict], from_uuid: str) -> tuple[dict | None, list[dict]]:
    """from_uuid を行に解決する。 戻り値 (leaf_line, group_lines)。

    frontend は **assistant バブルの識別子に message.id (= "msg_xxx") を使う** (= jsonl の行
    uuid とは別物)。 さらに 1 つの API message が thinking / text / tool_use と複数行に分かれて
    同じ message.id を共有するので、 message.id 一致は『その id を持つ全行 (= group)』 を返し、
    leaf には group の最後 (= file 順最後 = そのメッセージの末尾) を採る。
      - 行 uuid 直接一致: leaf=その行、 group=[その行]   (= user バブル等)
      - message.id 一致 : leaf=group[-1]、 group=全行       (= assistant バブル)
      - どちらも無し    : (None, [])
    """
    by_uuid = {d.get("uuid"): d for d in parsed if d.get("uuid")}
    if from_uuid in by_uuid:
        d = by_uuid[from_uuid]
        return d, [d]
    group = [d for d in parsed if (d.get("message") or {}).get("id") == from_uuid]
    if not group:
        return None, []
    return group[-1], group


def fork_point_status(source_lines: list[str], from_uuid: str) -> str:
    """from_uuid が分岐できるか分類する。 戻り値:
      "ok"        : 分岐可能な切れ目
      "not_found" : その uuid / message.id が jsonl に無い (= 別 jsonl / 未確定)
      "dirty"     : 行はあるが tool 保留中 / sidechain 等で切れ目でない

    tool_use と tool_result のペアの間で切ると resume が壊れるので、 stop_reason でなく
    コンテンツ構造で判定する (= frontend は result の stop_reason を最後のバブルに上書き
    stamp するため当てにならない。 行の中身が真値):
      - user      : tool_result ブロックを含まない実プロンプトなら ok
      - assistant : group の全行で tool_use ブロックが無ければ ok (= ツール呼び出しを
                    保留してない、 thinking/text だけの回答)
    """
    parsed = _parse_lines(source_lines)
    leaf, group = _resolve_target(parsed, from_uuid)
    if leaf is None:
        return "not_found"
    if any(d.get("isSidechain") or d.get("isMeta") for d in group):
        return "dirty"
    t = leaf.get("type")
    if t == "user":
        return "ok" if "tool_result" not in _content_block_types(leaf) else "dirty"
    if t == "assistant":
        has_tool = any("tool_use" in _content_block_types(d) for d in group)
        return "ok" if not has_tool else "dirty"
    return "dirty"


def is_clean_fork_point(source_lines: list[str], from_uuid: str) -> bool:
    """fork_point_status が "ok" かの薄いラッパ (= 既存呼び出し / test 互換)。"""
    return fork_point_status(source_lines, from_uuid) == "ok"


def lineage_root_resolved(source_lines: list[str], from_uuid: str) -> bool:
    """from_uuid から parentUuid 鎖を辿った時、 根 (= parentUuid=null) まで到達できるか。
    True = 鎖が完走 (= 全 context が source_lines 内にある)、 False = 親が見つからない
    時点で打ち切られる (= 別 jsonl にまたがってる)。 主に test の意図表現 / 手動デバッグ用。
    chat_routes は build_forked_lineage_lazy を使うのでこの関数は呼ばない (= 毎回全 parse
    を避けるため)。"""
    parsed = _parse_lines(source_lines)
    by_uuid: dict[str, dict] = {
        d["uuid"]: d
        for d in parsed
        if d.get("type") in _MESSAGE_TYPES and d.get("uuid")
    }
    leaf, _group = _resolve_target(parsed, from_uuid)
    leaf_uuid = leaf.get("uuid") if leaf is not None else None
    if leaf_uuid not in by_uuid:
        return False
    cur: str | None = leaf_uuid
    seen: set[str] = set()
    while cur is not None and cur not in seen:
        if cur not in by_uuid:
            return False
        seen.add(cur)
        cur = by_uuid[cur].get("parentUuid")
    return True


def _index_lines(by_uuid: dict[str, dict], lines: list[str]) -> None:
    """jsonl 行群を parse して by_uuid に追加 (= 既出 uuid は上書きしない)。"""
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        if d.get("type") in _MESSAGE_TYPES and d.get("uuid"):
            by_uuid.setdefault(d["uuid"], d)


def build_forked_lineage_lazy(
    src_lines: list[str],
    from_uuid: str,
    new_session_id: str,
    fetch_more,
) -> list[str]:
    """鎖駆動の lazy 版 build_forked_lineage。 src_lines を起点に parentUuid 鎖を辿り、
    親 uuid が今の index に無い時だけ fetch_more() を呼んで追加 jsonl 行を取り込む。
    全行を一括 parse する build_forked_lineage と違い、 必要になった時だけ index を拡張
    するので、 大量の jsonl が project dir にあっても鎖が src_lines 内で閉じるケースでは
    追加 jsonl を 1 個も読まない (= O(必要な親数) で済む)。

    fetch_more: 引数なしで呼び出して `list[str] | None` を返す callable。
                次の jsonl の行リストを返す。 もう候補が無ければ None。

    挙動:
      - 鎖の親 uuid が index に無い → fetch_more() で 1 個ずつ追加 load
      - fetch_more が None を返したら、 そこで鎖を確定して終了
      - 完走 (= parentUuid=null まで到達) しても、 候補が残ってても余計な load はしない

    from_uuid が src_lines に無ければ ValueError (旧 build_forked_lineage と同じ)。
    """
    by_uuid: dict[str, dict] = {}
    _index_lines(by_uuid, src_lines)

    # leaf 解決は src_lines 内で行う (= from_uuid を含む jsonl は src_path 単体で確定済)。
    # message.id grouping は src_lines に対してだけ意味があるので _resolve_target は src のみ。
    parsed_src = _parse_lines(src_lines)
    leaf, _group = _resolve_target(parsed_src, from_uuid)
    leaf_uuid = leaf.get("uuid") if leaf is not None else None
    if leaf_uuid not in by_uuid:
        raise ValueError(f"from_uuid {from_uuid!r} not found in source session")

    chain: list[dict] = []
    seen: set[str] = set()
    cur: str | None = leaf_uuid
    while cur is not None and cur not in seen:
        if cur not in by_uuid:
            # 親 uuid が今の index に無い: 次の jsonl を読み込んで再 check (= まだ追加 load
            # しても見つからなければさらに次へ、 候補尽きるまで)。
            extra = fetch_more()
            if extra is None:
                break
            _index_lines(by_uuid, extra)
            continue
        seen.add(cur)
        chain.append(by_uuid[cur])
        cur = by_uuid[cur].get("parentUuid")
    chain.reverse()

    out: list[str] = []
    for d in chain:
        line = dict(d)
        line["sessionId"] = new_session_id
        out.append(json.dumps(line, ensure_ascii=False))
    return out


def build_forked_lineage(
    source_lines: list[str], from_uuid: str, new_session_id: str
) -> list[str]:
    """source jsonl の行群から、 from_uuid を leaf として parentUuid 鎖を根まで遡り、
    その lineage だけを残した新セッションの jsonl 行群 (= 文字列のリスト) を返す。

    - 各行の `sessionId` を new_session_id に書き換える (= claude は filename の id と
      行内 sessionId の両方を見るので揃える)。
    - `uuid` / `parentUuid` の鎖はそのまま残す (= ファイル内で自己完結していれば良く、
      別ファイルと uuid が衝突しても各 resume は 1 ファイルしか読まないので無害)。
    - 並びは根 → leaf (= 元の時系列) を保つ。

    from_uuid が見つからなければ ValueError。
    """
    parsed = _parse_lines(source_lines)
    # uuid → 行 dict (= message 行のみ。 メタ行は uuid を持たない)
    by_uuid: dict[str, dict] = {
        d["uuid"]: d
        for d in parsed
        if d.get("type") in _MESSAGE_TYPES and d.get("uuid")
    }
    # from_uuid は行 uuid か message.id (= assistant バブル) のどちらか。 leaf 行を解決して、
    # その実 uuid を鎖の起点にする。
    leaf, _group = _resolve_target(parsed, from_uuid)
    leaf_uuid = leaf.get("uuid") if leaf is not None else None
    if leaf_uuid not in by_uuid:
        raise ValueError(f"from_uuid {from_uuid!r} not found in source session")

    # leaf から parentUuid を根まで遡る。 親がファイル内に無い (= 過去の compact /
    # 別セッション由来) 時点で打ち切る = そこが新セッションの実質的な根になる。
    chain: list[dict] = []
    seen: set[str] = set()
    cur: str | None = leaf_uuid
    while cur is not None and cur in by_uuid and cur not in seen:
        seen.add(cur)
        chain.append(by_uuid[cur])
        cur = by_uuid[cur].get("parentUuid")
    chain.reverse()  # 根 → leaf

    out: list[str] = []
    for d in chain:
        line = dict(d)
        line["sessionId"] = new_session_id
        out.append(json.dumps(line, ensure_ascii=False))
    return out
