"""`tabs list` の末尾に並べる、 別の機械のタブの行を組む (= 判定だけ。 backend は呼ばない)。 呼ぶのは `tabs list`。"""
from __future__ import annotations

from backend.cli.tab_state import peer_tab_state

#: 別の機械の行の 2 番目の欄 (= 階層の欄の位置に入る)。
OTHER_MACHINE = "別の機械"


def peer_tab_lines(peers: list) -> list[str]:
    """`GET /agent-messages/peers` の `peers` から行を作る。 行の頭は `<機械>:<タブの id>` (= 起動の検査がこの形を読む)、
    続けて状態の語と名前。 眠っているタブ・claude の居ないタブも並べる。
    A machine the asking tab may not talk to gets a line with the reason ahead of its tabs."""
    lines = []
    for peer in peers:
        name = peer.get("name")
        if peer.get("refusal"):
            lines.append(f"{name}:  {OTHER_MACHINE}  {peer['refusal']}")
        if peer.get("tabs") is None:
            lines.append(f"{name}:  {OTHER_MACHINE}  一覧を取れません ({peer.get('error')})")
            continue
        lines.extend("  ".join([f"{name}:{tab.get('id')}", OTHER_MACHINE, peer_tab_state(tab), tab.get("title") or ""]).rstrip()
                     for tab in peer["tabs"])
    return lines
