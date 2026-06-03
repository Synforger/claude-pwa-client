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


def is_clean_fork_point(source_lines: list[str], from_uuid: str) -> bool:
    """from_uuid が分岐の安全な切れ目か判定する。

    tool_use と tool_result のペアの間で切ると resume が壊れるので、 stop_reason でなく
    コンテンツ構造で判定する (= frontend は result の stop_reason を最後のバブルに上書き
    stamp するため、 バブルの stop_reason は当てにならない。 行の中身が真値):
      - user      : tool_result ブロックを含まない実プロンプトなら OK (= claude の次手番が
                    user 入力で、 dangling が無い)
      - assistant : tool_use ブロックを含まない行なら OK (= ツール呼び出しが保留してない、
                    end_turn のテキスト回答等)
    """
    for d in _parse_lines(source_lines):
        if d.get("uuid") != from_uuid:
            continue
        if d.get("isSidechain") or d.get("isMeta"):
            return False
        t = d.get("type")
        block_types = _content_block_types(d)
        if t == "user":
            return "tool_result" not in block_types
        if t == "assistant":
            return "tool_use" not in block_types
        return False
    return False


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
    if from_uuid not in by_uuid:
        raise ValueError(f"from_uuid {from_uuid!r} not found in source session")

    # leaf から parentUuid を根まで遡る。 親がファイル内に無い (= 過去の compact /
    # 別セッション由来) 時点で打ち切る = そこが新セッションの実質的な根になる。
    chain: list[dict] = []
    seen: set[str] = set()
    cur: str | None = from_uuid
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
