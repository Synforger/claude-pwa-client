# タブを渡る頼みを 1 枚の票で運ぶ (`tabs ticket`)

あるタブが別のタブに仕事を頼み、 受けたタブがさらに別のタブへ回す時、 頼みを毎回書き直して伝えると、 回るたびに
要約が入って、 最後のタブには一言しか届きません。 票 (ticket) はその代わりです。 1 つの頼みに 1 枚の file を作り、
関わるタブは **書き足すだけ** で、 誰も消さず、 言い換えません。 最後のタブも、 最初に頼んだ人の言葉をそのまま読めます。
タブどうしの連絡は「票 `<id>` を渡されました」 の 1 行で済みます。

票は backend だけが書きます。 タブは `tabs ticket` を打つだけで、 file には触りません。 同じ機械の中の
タブだけが使えます (別の機械のタブへは、 まだ渡せません)。

## 使う

```sh
tabs ticket new <題> <本文の file> [--operator-said]   # 票を開き、 id を出す
tabs ticket show <id>                                   # 票を全部、 時刻の順に読む
tabs ticket add <id> <file>                             # やったことを書き足す
tabs ticket ask <id> --kind decide|mac|report <file> [--recommend <file>]
                                                        # 票を操作者の前に出す
tabs ticket close <id> [<file>]                         # 票を閉じる (= 残る。 閉じた後は書き足せない)
tabs ticket pass <id> <宛先のタブの id か名前>           # 票の持ち主を移し、 宛先に 1 行で知らせる
```

- 送り主は、 打ったタブ自身です (`PWA_SID`。 [tabs](../../skills/tabs/SKILL.md) と同じ)。 タブの外では動きません
- `new --operator-said`: 頼みが操作者の言葉から出た時に付けます。 そのタブで操作者が最後に打った発話を、 backend が
  会話の記録から取って、 票の 2 行目に入れます。 タブが書いた文は、 操作者の言葉としては入りません。 今の作業を
  始めたのが操作者の発話でない時は入らず、 そう伝えます (= 票は開きます)
- `ask`: `decide` は決めてほしい事、 `mac` は Mac の前でしかできない事、 `report` は報告です。 `--recommend` の
  file には、 操作者がそのまま取れる推奨を書きます。 `ask` した票は操作者の返事を待つ状態 (`waiting-operator`) になります
- `pass`: 持ち主を宛先へ移し、 宛先に 「票 `<id>` を渡されました。 `tabs ticket show <id>` で読んでください」 の
  1 行を [タブどうしの連絡](agent-messages.md) と同じ道で届けます (= Claude の居ないタブは起こします)。
  届ける前に失敗した時、 票は変わりません。 操作者の返事を待っている票と、 閉じた票は渡せません
- 票の本文を、 連絡の 1 行に写して回さないでください。 宛先は `show` で読みます

失敗した時は、 標準エラーに `tabs: <見出し> [<code>]: <理由>` を出して 1 で終わります。

| code | 意味と次の手 |
|---|---|
| `ticket_unknown` | その id の票がありません。 id を確かめてください |
| `ticket_closed` | 票は閉じていて、 書き足せません |
| `ticket_waiting_operator` | 票は操作者の返事を待っていて、 渡せません |
| `ticket_empty` | 題・本文・宛先が空です |
| `ticket_bad_kind` | `--kind` が `decide` / `mac` / `report` ではありません |
| `ticket_to_self` | 自分のタブへは渡せません |
| `ticket_peer_not_yet` | 別の機械のタブへは、 まだ渡せません |
| `ticket_unknown_sender` | このタブの id (`PWA_SID`) が backend のタブにありません |
| `ticket_local_only` | 別の機械から呼ばれました |
| `ticket_refused` | 検査コマンドが、 その本文を票に足すことを断りました。 理由に従って書き直してください |
| `ticket_outside_place` | このタブは、 その票の置き場を読めないので票に関われません |
| `ticket_place_split` | このタブが読んだ範囲が 1 つの置き場に収まらず、 票を開けません |
| `ticket_place_unknown` | 票の置き場を決められない・見つけられません |
| `ticket_check_failed` | 検査コマンドが動きませんでした。 もう一度試し、 続く時は設定を確かめてください |
| `agent_message_*` | `pass` で宛先に届ける道の失敗です。 意味と次の手は [tabs の skill](../../skills/tabs/SKILL.md) の表と同じです |
| `ticket_not_sent` / `ticket_unconfirmed` | backend に繋がらない / 答えを受け取れませんでした。 前者は何も書いていません。 後者は `show` で確かめてから、 やり直してください |

## 票の形と置き場

票 1 枚は `<置き場>/<id>.jsonl` で、 1 行が 1 件の JSON です (= 追記だけ)。 件は次の欄を持ちます。

| 欄 | 中身 |
|---|---|
| `kind` | `opened` (最初の頼み) / `operator` (操作者の原文) / `added` / `asked` / `passed` / `closed` |
| `at` | 時刻 (ISO、 UTC) |
| `tab` / `tab_title` / `tier` | 書いたタブの id・名前・階層 |
| `text` | 本文 |
| `title` | `opened` だけ |
| `ask_kind` / `recommend` | `asked` だけ (`recommend` は任意) |
| `to` | `passed` だけ (渡した先のタブの id) |
| `typed_in` | `operator` だけ (その言葉が打たれたタブの id) |

id は `<機械の名前>-<YYMMDD>-<NN>` です (例: `home-261119-01`)。 NN は機械と日ごとに 01 から数えます。 機械の名前は
設定の [`machine_name`](config.md) で、 無ければこの機械の host 名の最初の `.` までです。 年と機械の名前が入るので、
2 台で同じ id は出ず、 閉じた票を残しても来年の同じ日とは重なりません。

置き場は、 票を開く時に 1 つに決まり、 後から動きません。 検査コマンドの設定が無い時は、 すべての票が
`<根>/state/claude-pwa-client/tickets/` (根を渡さない時は `~/.claude-pwa-client/tickets/`) に置かれます。
そこにある `index.json` は、 全部の票の **置き場の鍵・今の持ち主・最初に頼んだタブ・状態・求める物** だけを持ちます
(題と本文は入れません)。 状態は `open` / `waiting-operator` / `closed` です。

## 検査コマンドを設定する (任意)

票を読み書きできるタブを、 読んだ範囲で絞りたい時のために、 [`agent_message_check`](agent-messages.md) と同じ形
(= 語のリスト) の検査コマンドを 5 つ、 設定の鍵で渡せます。 どれも書かなければ、 その段の検査はしません
(= 票は境界の外の置き場に 1 つだけで、 誰でも読み書きできます)。 語の中の `{名前}` は値に置き換わります。
`{session}` は、 そのタブの Claude の会話の id (= 会話の記録 file の名前) です。 値が空になる `{名前}` は、 直前の
`--` で始まる語と一緒に省かれます (= `--typed-in {typed_in}` は、 操作者の発話が無い時は渡りません)。

| 鍵 | いつ | 語の中で使える物 | 終了 code |
|---|---|---|---|
| `ticket_place_check` | 票を開く時 | `{session}`、 `{typed_in}` (操作者の発話が打たれた会話) | 0: 標準出力の 1 行目が、 票を置く folder の絶対 path。 1: 読んだ範囲が 1 つの置き場に収まらない (`ticket_place_split`)。 それ以外: `ticket_place_unknown` |
| `ticket_places_check` | backend が最初に票に触れる時と、 索引に知らない置き場の鍵が出た時 | なし | 0: 標準出力の 1 行に 1 つ、 票を置く folder の絶対 path |
| `ticket_write_check` | 票に件を足す前 | `{place}` (票の folder)、 `{text_file}`、 `{typed_in}` | 0: 足す。 1: 断る (標準エラーの最後の行が理由。 `ticket_refused`)。 それ以外: `ticket_check_failed` |
| `ticket_covers_check` | 票に関わるタブ (書き足す・求める・閉じる・渡す側と渡される側) が置き場を読めるか | `{session}`、 `{place}` | 0: 関われる。 それ以外: `ticket_outside_place` |
| `ticket_read_check` | `tabs ticket show` の 1 件ごと | `{session}` (読むタブ)、 `{text_file}` | 0: 見せる。 それ以外: その件は「読めない境界の書き足し」 の 1 行に置き換わる (題も同じ扱い) |

`{text_file}` は、 判定する本文を書いた、 その run の間だけの file です。 `opened` の件は題と本文を続けた物です。

置き場の folder は、 backend が **file には書きません**。 索引は folder の path の代わりに、 その path の SHA-256 の
頭 16 文字 (= 鍵) を持ち、 鍵から folder への対応は `ticket_places_check` の答えから backend の memory の中に作ります。
`ticket_places_check` を書かない時は、 境界の外の置き場 1 つだけです。

## 件を、 関わるタブが読めるかの扱い

- 書き足し (`add` / `ask` / `close` と、 `new` の最初の件) は、 足す前に `ticket_write_check` を通ります
  (= 本文が無い `close` と `pass` は判定する物が無いので通しません)
- `pass` は、 渡す側と渡される側の両方が `ticket_covers_check` を通ります
- `show` の件は、 読むタブに対して 1 件ずつ `ticket_read_check` を通ります。 止まった件は
  `{"kind": ..., "at": ..., "hidden": true, "text": "読めない境界の書き足し"}` だけになり、 誰が書いたかも出ません

## 設定

`machine_name` と、 上の 5 つの鍵は [config.md](config.md) の「全体オプション」 にあります。
