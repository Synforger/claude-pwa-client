#!/usr/bin/env python3
"""別のタブのエージェントとの連絡: 宛先の一覧と送信。

    tabs [--agent-dir <エージェントの folder>] <以下の命令>
    tabs    list               連絡できるタブの一覧 (= id / 階層 / 口座 / 状態 / 境界 / 名前。 階層はこのエージェントのタブの物で、
                                 別の agent のタブは「別の agent」 と出る)。
                                 別の機械のタブは、 末尾に `<相手の名前>:<id>` の形で並ぶ
    tabs    send <to> <file>     <file> の中身を <to> (= タブの id か名前) へ送る。
                                 別の機械のタブは `<相手の名前>:<タブの id か名前>`
    tabs    send <to> <file> --operator-said
                                 同じ送信に、 このタブで操作者が最後に打った発話を付ける
    tabs    rollover <continue|wait> [--tier <階層>]
                                 このタブを終了して起動し直す (= 自動の入れ替え。 締めを終えた最後の 1 手)。
                                 この会話が Write / Edit で書いた journal に `## 入れ替えの時点` が在り、 commit が
                                 済んでいる時だけ頼む (= 欠けていれば、 欠けた段を名指して止まる。 push は見ない)。
                                 continue は起動の後に引き継いだ作業を続け、 wait はブリーフィングで待つ。
                                 階層は --tier、 無ければ `AGENT_TIER`、 それも無い会話 (= 再開や fork で始まった
                                 会話) は、 一覧と同じにその会話の最初の発話から導く。
                                 子のタブ (= `AGENT_CHILD=1`) は journal の代わりに、 この会話がタブのメモに
                                 `## 引き継ぎ` を書いた時だけ頼む

    子のタブ (= このタブが仕事を渡すために立てるタブ。 手順は skill `child-tab`):
    tabs    new <題> <本文の file>
                                 子のタブを立て、 本文を最初の発話として渡す。 子はこのタブと同じ階層で起動し、
                                 このタブの id を親として覚える。 渡した本文は子のタブのメモ (= 階層の
                                 `pages/<子の id>/memo.md`) にも残る (= 子が入れ替わった後に読み直す)。 子のタブからは立てられない
    tabs    children [--summary] このタブが立てた子の一覧 (= id / 状態 / claude の状態 / 題)。 --summary は 1 行
    tabs    report <done|stuck> <本文の file>
                                 子のタブから親のタブへ結果を返し、 メモの状態を「完了」 か「詰まり」 にする
    tabs    close <子の id> [--force]
                                 このタブが立てた子を閉じ、 そのメモを消す。 作業中の子は --force の時だけ閉じる

運ぶのは PWA の backend (= `POST /agent-messages`)、 通すかどうかを決めるのは番人。 この script は
呼び出しを 1 つにまとめるだけで、 判定は持たない。 port は `pwa-hook.sh` と同じ決め方
(= 既定 8765、 別 port の PC は `PWA_PORT`)、 送り主は自分のタブの `PWA_SID`。

エージェントの folder は、 `--agent-dir` > 環境変数 `AGENT_ROOT` > 器の根 (= `AGENT_PLATFORM_ROOT`) の `agents/` の下で
起動 script (= `.tooling/lib/claude-launch.py`) を持つ 1 つ、 の順に決める (= どれも無ければ止まる)。 番人の印の置き場は、 `AREA_GUARD_STATE` > 器の根の `state/guard/marks` > `~/.cache/area-guard`。

別の機械 (= backend の設定の `agent_message_peers` に書いた相手) のタブへは、 こちらの backend が番人の検査を
通してから相手の backend へ渡し、 相手の backend が自分の番人を通して届ける。 相手の機械に見えるのも、
こちらから送れるのも、 その相手と連絡してよい口座のタブだけ (= backend の設定が決める)。

操作者の発話は、 付けると言った時だけ付く (= 既定は本文だけ)。 付く文面は backend が記録から読むので、
ここからは書けない。 付けるのは、 その発話がこの連絡を出させた時だけ ― 用件と関係の無い発話を付けると、
受け手はそれを自分のタブへの指示として読む。

階層は起動 script と同じ関数で、 その会話の最初の発話から導く (= 記録を別に持たない)。
手順と受けた時の扱いは、 エージェントの folder の `.claude/skills/tab-messages/SKILL.md`。

エージェントの側の `.tooling/work/tabs.py` をそのまま移した file (= 役割が混ざったまま。 割るのは別の変更でする)。
階層の決め方 (`claude-launch.py`) はエージェントの持ち物で、 import できない名前の file なので、 その folder から path で読む。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
BASE = f"http://127.0.0.1:{os.environ.get('PWA_PORT', '8765')}"
PLATFORM_ROOT = Path(os.environ["AGENT_PLATFORM_ROOT"]).expanduser() if os.environ.get("AGENT_PLATFORM_ROOT") else None
#: 番人の印の置き場。 根が無い時は今までの既定
MARKS = Path(os.environ.get("AREA_GUARD_STATE") or (
    PLATFORM_ROOT / "state/guard/marks" if PLATFORM_ROOT else HOME / ".cache/area-guard"))
#: `--agent-dir` で渡されたエージェントの folder
agent_dir_option: Path | None = None
# backend の検査は番人の上限 (= 180 秒) まで待つことがある。
TIMEOUT_SEC = 240


def agent_dir() -> Path:
    """エージェントの folder (= `--agent-dir` > `AGENT_ROOT` > 器の根の `agents/` の下で起動 script を持つ 1 つ)。"""
    if agent_dir_option is not None:
        return agent_dir_option
    if os.environ.get("AGENT_ROOT"):
        return Path(os.environ["AGENT_ROOT"]).expanduser()
    if PLATFORM_ROOT is None:
        raise SystemExit("tabs: エージェントの folder が分かりません。 --agent-dir か AGENT_PLATFORM_ROOT で渡してください")
    found = sorted(PLATFORM_ROOT.glob("agents/*/.tooling/lib/claude-launch.py"))
    if len(found) != 1:
        raise SystemExit(f"tabs: {PLATFORM_ROOT / 'agents'} の下に起動 script を持つ folder が{len(found)}個あります。 --agent-dir で 1 つを渡してください")
    return found[0].parents[2]


def launcher():
    agent = agent_dir()
    script = agent / ".tooling/lib/claude-launch.py"
    if not script.is_file():
        raise SystemExit(f"tabs: エージェントの起動 script が見つかりません ({script})。 --agent-dir か AGENT_PLATFORM_ROOT で場所を渡してください")
    os.environ["AGENT_ROOT"] = str(agent)     # 起動 script は import の時に環境変数からエージェントの場所を読む
    spec = importlib.util.spec_from_file_location("claude_launch", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(path: str, form: dict | None = None, method: str | None = None) -> tuple[int, object]:
    """backend を 1 回呼ぶ。 → (HTTP の status、 JSON の中身)。 繋がらなければ status 0。"""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    try:
        request = urllib.request.Request(BASE + path, data=data, method=method)
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8"))
        except ValueError:
            return error.code, {}
    except (urllib.error.URLError, OSError, ValueError) as error:
        return 0, {"detail": {"message": f"backend に繋がりません ({BASE}): {error}"}}


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def running() -> dict[str, dict]:
    """タブの id → そのタブで動いている claude (= Claude Code が口座ごとに置く記録から)。"""
    found = {}
    for path in HOME.glob(".claude*/sessions/*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tab = str(row.get("tmux") or "").split(":")[0].removeprefix("pwa-")
        if tab and row.get("sessionId") and alive(row.get("pid")):
            found[tab] = {**row, "account_dir": path.parents[1]}
    return found


def read_areas(session: str) -> int:
    """その会話が読んだ境界の数 (= 番人が持つ印。 名前は出さない)。"""
    try:
        data = json.loads((MARKS / f"{session}.json").read_text())
    except (OSError, ValueError):
        return 0
    return len(data if isinstance(data, list) else data.get("areas") or [])


#: 番人の連絡の判定 (= 受け手が送り主の読んだ境界を知っているかを答える `--covers`)。
PEERS = HOME / ".git-hooks/agent-hooks/claude-code/peers.py"
#: このタブが知らない境界のタブに、 階層と名前の代わりに出す語 (= 階層と名前は、 そのタブが働く場所を言う)。
HIDDEN = "別の境界"


def known_to(me: str | None, other: str) -> bool:
    """このタブ (= claude の session `me`) が、 `other` の読んだ境界を全部知っているか (= 番人が答える)。
    このタブの会話が分からない時と、 番人が答えられない時は知らないとする。"""
    if me is None or not PEERS.is_file():
        return False
    try:
        done = subprocess.run([sys.executable, str(PEERS), "--to", me, "--covers", other],
                              capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def works_unknown(me: str | None, folder: Path | None) -> bool:
    """`folder` (= 別のタブの階層の folder) を含む境界の中に、 このタブ (= claude の session `me`) が知らない
    境界が在るか (= 番人の `corpus-scan.py` の読み方で答える)。 起動したばかりのタブは境界の中をまだ読んで
    いないので、 読んだ印だけでは伏せられない。 働く folder は起動の時から決まっている。
    このタブの会話が分からない時と、 番人が答えられない時は在るとする。"""
    if folder is None:
        return False
    if me is None:
        return True
    try:
        spec = importlib.util.spec_from_file_location("corpus_scan", PEERS.parents[2] / "scanners/corpus-scan.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        areas = module.load_areas()
        unknown = set(module.unknown_areas(read_area_names(me), areas))
    except Exception:  # noqa: BLE001  (= 番人の設定が壊れている / 番人が無い: 伏せる側に倒す)
        return True
    home = Path(os.path.realpath(folder))
    return any(name in unknown for name, roots in areas.items()
               for root in roots if home == root or root in home.parents)


def read_area_names(session: str) -> list[str]:
    """その会話が読んだ境界の名前 (= 番人が持つ印。 判定にだけ使い、 出さない)。"""
    try:
        data = json.loads((MARKS / f"{session}.json").read_text())
    except (OSError, ValueError):
        return []
    return sorted(data if isinstance(data, list) else data.get("areas") or [])


def listing() -> int:
    status, tabs = call("/sessions")
    if status != 200 or not isinstance(tabs, list):
        print(f"tabs: 一覧を取れません: {(tabs.get('detail') or {}).get('message', status) if isinstance(tabs, dict) else status}",
              file=sys.stderr)
        return 1
    launch, live, me = launcher(), running(), os.environ.get("PWA_SID")
    for tab in tabs:
        claude = live.get(tab["id"])
        if claude is None:
            continue        # claude が動いていないタブへは届かない
        # 階層はこのエージェントの物 (= その folder で動いていない claude は別の agent で、 封筒が運ぶ階層もその agent の物)
        ours = Path(os.path.realpath(str(claude.get("cwd") or ""))) == Path(os.path.realpath(agent_dir()))
        tier, folder = (launch.tier_of(launch.first_message(claude["account_dir"], claude["sessionId"])) if ours
                        else ("別の agent", None))
        marks = read_areas(claude["sessionId"])
        # このタブが知らない境界で働くタブは、 階層と名前を伏せる (= 宛先は id で指す)。 働く場所は、 読んだ
        # 境界と、 階層の folder を含む境界の 2 つで見る (= 起動したばかりのタブは、 まだ何も読んでいない)
        mine = (live.get(me) or {}).get("sessionId")
        shown = tab["id"] == me or ((not marks or known_to(mine, claude["sessionId"]))
                                    and not works_unknown(mine, folder))
        print("  ".join([
            tab["id"],
            tier if shown else HIDDEN,
            f"口座={tab.get('account_id') or 'personal'}",
            str(claude.get("status") or "?"),
            f"境界={marks}" if marks else "境界=なし",
            (tab.get("title") or "") if shown else f"({HIDDEN}のタブ)",
            "(= このタブ)" if tab["id"] == me else "",
            f"(= 子のタブ、 親 {tab.get('parent_id')})" if tab.get("child") else "",
        ]).rstrip())
    others()
    return 0


def others() -> None:
    """別の機械のタブを並べる (= 相手が設定されていない backend、 その口を持たない古い backend では何も出さない)。"""
    status, body = call("/agent-messages/peers")
    if status != 200 or not isinstance(body, dict):
        return
    for peer in body.get("peers") or []:
        name = peer.get("name")
        if peer.get("tabs") is None:
            print(f"{name}:  別の機械  一覧を取れません ({peer.get('error')})")
            continue
        for tab in peer["tabs"]:
            if tab.get("running"):      # claude が動いていないタブへは届かない
                print("  ".join([f"{name}:{tab.get('id')}", "別の機械", tab.get("title") or ""]).rstrip())


def send(to: str, file: Path, operator_said: bool = False) -> int:
    me = os.environ.get("PWA_SID")
    if not me:
        print("tabs: このタブの id (= PWA_SID) がありません。 PWA のタブの中から打ってください", file=sys.stderr)
        return 1
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as error:
        print(f"tabs: {file} を読めません: {error}", file=sys.stderr)
        return 1
    form = {"to": to, "from": me, "text": text}
    if operator_said:
        form["operator_said"] = "true"
    status, body = call("/agent-messages", form)
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        said = "操作者の発話つき" if body.get("operator_said") else "操作者の発話なし"
        print(f"届きました: {body.get('to')} ({said})")
        return 0
    detail = (body.get("detail") if isinstance(body, dict) else None) or {}
    detail = detail if isinstance(detail, dict) else {"message": str(detail)}
    print(f"tabs: 届いていません [{detail.get('code', status)}]: {detail.get('message', body)}", file=sys.stderr)
    return 1


def own_tier() -> str | None:
    """この会話の階層を、 一覧と同じ決め方で導く (= 会話の最初の発話から)。 会話の記録が見つからなければ None。"""
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        return None
    launch = launcher()
    for record in HOME.glob(f".claude*/projects/*/{session}.jsonl"):
        return launch.tier_of(launch.first_message(record.parents[2], session))[0]
    return None


# --- 子のタブ ----------------------------------------------------------------------

#: 子のタブのメモの状態の行 (= `report` が書き換え、 `children` と起動の検査が読む)
STATE = re.compile(r"^- 状態: (.*)$", re.M)
STATES = {"done": "完了", "stuck": "詰まり"}
WORKING = "作業中"
#: 作業中のまま claude が動いていない子の印
QUIET = "静か"
#: 子のタブのメモの、 入れ替えの引き継ぎを書く節 (= 子が自分の入れ替えの前に書き、 起き直した子が読む)
CARRY = "## 引き継ぎ"
CARRY_EMPTY = "(まだ無し)"


def my_tier() -> str | None:
    return os.environ.get("AGENT_TIER") or own_tier()


def child_note(tier: str, child: str) -> Path | None:
    """子のタブのメモ (= 📋 が開く所と同じ、 階層の `pages/<タブの id>/memo.md`)。"""
    folder = launcher().tier_folder(tier)
    return folder / "pages" / child / "memo.md" if folder is not None else None


def own_note() -> Path | None:
    """The memo of this tab: the one `children` and the 📋 read (= the tier's `pages/<tab id>/memo.md`) when it
    exists, else the `PWA_NOTE` this tab was started with (= a tab started before memos moved to `pages/`).
    `None` when neither exists."""
    me, tier = os.environ.get("PWA_SID"), my_tier()
    placed = child_note(tier, me) if me and tier else None
    if placed is not None and placed.is_file():
        return placed
    given = os.environ.get("PWA_NOTE")
    return Path(given) if given and Path(given).is_file() else None


def note_state(path: Path | None) -> str:
    try:
        found = STATE.search(path.read_text(encoding="utf-8")) if path is not None else None
    except OSError:
        found = None
    return found.group(1).strip() if found else "?"


def fail(message: str) -> int:
    print(f"tabs: {message}", file=sys.stderr)
    return 1


def refused(status: int, body: object) -> str:
    detail = (body.get("detail") if isinstance(body, dict) else None) or {}
    detail = detail if isinstance(detail, dict) else {"message": str(detail)}
    return f"[{detail.get('code', status)}]: {detail.get('message', body)}"


def new_child(title: str, file: Path) -> int:
    """子のタブを立て、 本文を最初の発話として渡す。 子はこのタブと同じ階層で起動する (= 本文の検査は、 子が
    このタブと同じ境界を読む前提で通る。 違う階層に立てると、 このタブだけが読んだ物が子へ通る)。"""
    me = os.environ.get("PWA_SID")
    if not me:
        return fail("このタブの id (= PWA_SID) がありません。 PWA のタブの中から打ってください")
    if os.environ.get("AGENT_CHILD"):
        return fail("子のタブからは子のタブを立てません。 分けたい仕事は親へ report で返してください")
    tier = my_tier()
    if not tier or launcher().tier_folder(tier) is None:
        return fail(f"このタブの階層が分かりません ({tier or 'AGENT_TIER も会話の記録も無い'})")
    try:
        task = file.read_text(encoding="utf-8").strip()
    except OSError as error:
        return fail(f"{file} を読めません: {error}")
    if not task:
        return fail(f"{file} が空です")
    text = f"<child-start>\ntier={tier}\n</child-start>\n\n{task}"
    status, body = call(f"/sessions/{urllib.parse.quote(me)}/children", {"text": text, "title": title})
    if status != 200 or not isinstance(body, dict) or not body.get("id"):
        return fail(f"子のタブを立てられません {refused(status, body)}")
    child = body["id"]
    note = child_note(tier, child)
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(f"# {title}\n\n- 親のタブ: {me}\n- 状態: {WORKING}\n- 階層: {tier}\n\n"
                    f"## 渡された仕事\n\n{task}\n\n{CARRY}\n\n{CARRY_EMPTY}\n", encoding="utf-8")
    started = "" if body.get("started") else " (= 最初の発話を渡せていません。 子のタブを開いて確かめてください)"
    print(f"立てました: {child} ({title}){started}\n  メモ: {note}")
    return 0


def my_children() -> tuple[list[dict] | None, str]:
    """このタブが立てた子 (= 立てた順)。 取れなければ (None, 理由)。"""
    me = os.environ.get("PWA_SID")
    if not me:
        return None, "PWA のタブの外"
    status, tabs = call("/sessions")
    if status != 200 or not isinstance(tabs, list):
        return None, f"backend に繋がりません ({status})"
    return [t for t in tabs if t.get("child") and t.get("parent_id") == me], ""


def children(summary: bool) -> int:
    found, why = my_children()
    if found is None:
        print(f"children: UNKNOWN ({why})" if summary else f"tabs: 子の一覧を取れません: {why}",
              file=sys.stdout if summary else sys.stderr)
        return 0 if summary else 1
    tier, live = my_tier(), running()
    states = [(t, note_state(child_note(tier, t["id"]) if tier else None)) for t in found]
    # 作業中のまま claude が動いていない子 (= 報告せずに止まった。 API の接続が切れた子は、 次の発話まで待ち続ける)
    quiet = {t["id"] for t, state in states if state == WORKING and (live.get(t["id"]) or {}).get("status") != "busy"}
    if summary:
        counts = {name: sum(1 for _, state in states if state == name) for name in (WORKING, *STATES.values())}
        counts[QUIET] = len(quiet)
        print(f"children: {len(found)}" + (" (" + " / ".join(f"{k} {v}" for k, v in counts.items()) + ")" if found else ""))
        return 0
    for tab, state in states:
        claude = live.get(tab["id"])
        print("  ".join([tab["id"], state, str(claude.get("status") or "?") if claude else "claude なし",
                         tab.get("title") or "", f"← {QUIET} (= 記録の最後を見る)" if tab["id"] in quiet else ""]).rstrip())
    return 0


def report(kind: str, file: Path) -> int:
    """子のタブから親へ結果を返し、 メモの状態を書き換える (= 届かなければ書き換えない)。"""
    me = os.environ.get("PWA_SID")
    if not me or not os.environ.get("AGENT_CHILD"):
        return fail("report は子のタブ (= AGENT_CHILD=1) の中から打ちます")
    status, tabs = call("/sessions")
    mine = next((t for t in tabs if t.get("id") == me), None) if status == 200 and isinstance(tabs, list) else None
    if mine is None or not mine.get("parent_id"):
        return fail(f"親のタブが分かりません ({status})")
    try:
        text = file.read_text(encoding="utf-8").strip()
    except OSError as error:
        return fail(f"{file} を読めません: {error}")
    body = f"子のタブ {me} の報告 ({STATES[kind]})\n\n{text}"
    status, answer = call("/agent-messages", {"to": mine["parent_id"], "from": me, "text": body})
    if not (status == 200 and isinstance(answer, dict) and answer.get("ok")):
        return fail(f"親へ届いていません {refused(status, answer)}")
    note = own_note()
    if note is not None:
        written = note.read_text(encoding="utf-8")
        note.write_text(STATE.sub(f"- 状態: {STATES[kind]}", written, count=1) if STATE.search(written)
                        else f"- 状態: {STATES[kind]}\n\n{written}", encoding="utf-8")
    print(f"届きました: 親のタブ {mine['parent_id']} ({STATES[kind]})")
    return 0


def close_child(child: str, force: bool) -> int:
    found, why = my_children()
    if found is None:
        return fail(f"子の一覧を取れません: {why}")
    if child not in {t["id"] for t in found}:
        return fail(f"{child} はこのタブが立てた子ではありません (= 閉じられるのは自分の子だけ)")
    tier = my_tier()
    note = child_note(tier, child) if tier else None
    state = note_state(note)
    if state == WORKING and not force:
        return fail(f"{child} はまだ作業中です。 結果を受け取ってから閉じるか、 --force で閉じてください")
    status, body = call(f"/sessions/{urllib.parse.quote(child)}", method="DELETE")
    if status != 200:
        return fail(f"閉じられません {refused(status, body)}")
    if note is not None:
        note.unlink(missing_ok=True)
    print(f"閉じました: {child} ({state})")
    return 0


#: journal の file の path の形
JOURNAL = re.compile(r"/journal/\d{4}-\d{2}-\d{2}/session-\d+\.md$")
#: file を書く道具 (= 読む道具と Bash の path は数えない。 起動の時に前の journal を読むので、 読んだ path を数えると
#: 前の会話の journal で素通りする。 Bash で書いた journal は拾えず、 止まる側に倒れる)
WRITERS = ("Write", "Edit", "MultiEdit")
#: 締めの journal が持つ節 (= 次の会話がブリーフィングで読み上げる所)
HANDOVER = "## 入れ替えの時点"


def written_paths(record: Path) -> list[Path]:
    """この会話が file を書く道具で書いた path (= 書いた順、 重なりなし)。"""
    found: list[Path] = []
    with record.open(encoding="utf-8") as lines:
        for line in lines:
            if "tool_use" not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            content = (row.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") not in WRITERS:
                    continue
                written = str((block.get("input") or {}).get("file_path") or "")
                if written:
                    path = Path(written).expanduser()
                    if path not in found:
                        found.append(path)
    return found


def written_journals(record: Path) -> list[Path]:
    """この会話が書いた journal (= 会話の記録の、 file を書く道具の呼び出しに出た path)。 書いた順、 重なりなし。

    ⚠ **file の更新時刻では見分けない。**別の PC から pull した journal も、 取り込んだ時刻の新しい file になる。
    """
    return [path for path in written_paths(record) if JOURNAL.search(str(path))]


def git(folder: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True)
    return done.returncode, done.stdout.strip()


def not_handed_over() -> str | None:
    """この会話の締めが済んでいない理由 (= 済んでいれば None)。

    見るのは 2 つ ― この会話が書いた journal に `## 入れ替えの時点` が在る / その file に commit していない
    変更が無い。 作業木全体の汚れは見ない (= 同じ clone を使う別のタブの書きかけで、 このタブの締めが止まらないように)。
    push は見ない: 起動し直すのは同じ機械の同じ clone なので、 commit した journal は次の会話がそのまま読み、
    push は次の会話の締めが運ぶ。 push の失敗や push 先の無い repo で起動し直しを止めると、 60% を超えた会話が
    人の手を待って動かなくなる。
    """
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    record = next(iter(HOME.glob(f".claude*/projects/*/{session}.jsonl")), None) if session else None
    if record is None:
        return "この会話の記録が見つかりません (= CLAUDE_CODE_SESSION_ID)。 締めが済んだかを確かめられません"
    if os.environ.get("AGENT_CHILD"):
        return child_not_handed_over(record)
    journals = [path for path in written_journals(record) if path.is_file()]
    handed = [path for path in journals if HANDOVER in path.read_text(encoding="utf-8", errors="replace")]
    if not handed:
        return (f"この会話が書いた journal に `{HANDOVER}` がありません"
                + (f" (= 書いた journal: {', '.join(str(p) for p in journals)})" if journals else " (= journal をまだ書いていない)")
                + "。 締めの Step 2 で journal を書いてから打ってください")
    journal = handed[-1]
    code, dirty = git(journal.parent, "status", "--porcelain", "--", journal.name)
    if code != 0:
        return f"journal の repo を読めません: {journal}"
    if dirty:
        return f"journal を commit していません: {journal} (= 締めの Step 3)"
    return None


def child_not_handed_over(record: Path) -> str | None:
    """子のタブの締めが済んでいない理由 (= この会話がタブのメモの `## 引き継ぎ` を書いたか)。 済んでいれば None。

    子は journal を書かない。 起き直した子は、 メモの「渡された仕事」 と「引き継ぎ」 だけを読んで続ける。
    """
    note = own_note()
    if note is None:
        return "このタブのメモが見つかりません (= 階層の pages/<タブの id>/memo.md も PWA_NOTE も無い)"
    real = Path(os.path.realpath(note))
    if not any(Path(os.path.realpath(path)) == real for path in written_paths(record)):
        return f"この会話はタブのメモ ({note}) を書いていません。 `{CARRY}` に続きを書いてから打ってください"
    text = real.read_text(encoding="utf-8", errors="replace")
    carried = text.split(CARRY, 1)[1].strip() if CARRY in text else ""
    if not carried or carried == CARRY_EMPTY:
        return f"タブのメモの `{CARRY}` が空です。 次の会話が続ける所を書いてから打ってください"
    return None


def rollover(mode: str, tier: str | None) -> int:
    """このタブの起動し直しを backend に頼む。 起動器が読む 2 行 (= 階層と、 続けるか待つか) を本文にして渡す。"""
    me = os.environ.get("PWA_SID")
    if not me:
        print("tabs: このタブの id (= PWA_SID) がありません。 PWA のタブの中から打ってください", file=sys.stderr)
        return 1
    tier = tier or os.environ.get("AGENT_TIER") or own_tier()
    if not tier:
        print("tabs: 階層が分かりません (= AGENT_TIER も会話の記録も無い)。 --tier normal のように渡してください", file=sys.stderr)
        return 1
    # 終了された後では直せないので、 起動器が受け取れる階層かを先に見る
    if launcher().tier_folder(tier) is None:
        print(f"tabs: 階層が見つかりません: {tier} (= normal / projects/<P> / projects/<P>/subprojects/<S>)", file=sys.stderr)
        return 1
    # 終了された後では書けないので、 締め (= journal と commit) が済んだかを先に見る
    missing = not_handed_over()
    if missing:
        print(f"tabs: まだ起動し直せません: {missing}", file=sys.stderr)
        return 1
    status, body = call(f"/sessions/{urllib.parse.quote(me)}/rollover", {"text": f"tier={tier}\nmode={mode}\n"})
    if status == 202 and isinstance(body, dict) and body.get("rolling"):
        print(f"受け付けました: このタブは終了され、 {tier} で起動し直されます ({mode})")
        return 0
    detail = (body.get("detail") if isinstance(body, dict) else None) or {}
    detail = detail if isinstance(detail, dict) else {"message": str(detail)}
    print(f"tabs: 起動し直せません [{detail.get('code', status)}]: {detail.get('message', body)}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    global agent_dir_option
    if argv[:1] == ["--agent-dir"] and len(argv) >= 2:
        agent_dir_option, argv = Path(argv[1]).expanduser(), argv[2:]
    if argv == ["list"]:
        return listing()
    if len(argv) == 3 and argv[0] == "new":
        return new_child(argv[1], Path(argv[2]))
    if argv[:1] == ["children"] and argv[1:] in ([], ["--summary"]):
        return children(summary=len(argv) == 2)
    if len(argv) == 3 and argv[0] == "report" and argv[1] in STATES:
        return report(argv[1], Path(argv[2]))
    if len(argv) in (2, 3) and argv[0] == "close" and argv[2:] in ([], ["--force"]):
        return close_child(argv[1], force=len(argv) == 3)
    if len(argv) in (2, 4) and argv[0] == "rollover" and argv[1] in ("continue", "wait") and argv[2:3] in ([], ["--tier"]):
        return rollover(argv[1], argv[3] if len(argv) == 4 else None)
    if len(argv) in (3, 4) and argv[0] == "send" and argv[3:] in ([], ["--operator-said"]):
        return send(argv[1], Path(argv[2]), operator_said=len(argv) == 4)
    print("\n\n".join(__doc__.split("\n\n")[1:3]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
