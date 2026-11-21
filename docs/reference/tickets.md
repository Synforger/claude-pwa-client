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
tabs ticket pass <id> <宛先>                            # 票の持ち主を移し、 宛先に 1 行で知らせる (= タブの id か名前、 別の機械は <機械>:<タブ>)
```

- 送り主は、 打ったタブ自身です (`PWA_SID`。 [tabs](../../skills/tabs/SKILL.md) と同じ)。 タブの外では動きません
- `new --operator-said`: 頼みが操作者の言葉から出た時に付けます。 そのタブで操作者が最後に打った発話を、 backend が
  会話の記録から取って、 票の 2 行目に入れます。 タブが書いた文は、 操作者の言葉としては入りません。 今の作業を
  始めたのが操作者の発話でない時は入らず、 そう伝えます (= 票は開きます)
- `ask`: `decide` は決めてほしい事、 `mac` は Mac の前でしかできない事、 `report` は報告です。 `--recommend` の
  file には、 操作者がそのまま取れる推奨を書きます。 `ask` した票は操作者の返事を待つ状態 (`waiting-operator`) になります。 `ask` できるのは票の家の機械のタブで、 かつ **その票を今持っているタブ** だけです (`ticket_not_holder`。 答えは持つタブへ届くので、 別のタブが訊くと答えが読まれません)
  ([2 台の機械にまたがる票](#2-台の機械にまたがる票))
- `pass`: 持ち主を宛先へ移し、 宛先に 「票 `<id>` を渡されました。 `tabs ticket show <id>` で読んでください」 の
  1 行を [タブどうしの連絡](agent-messages.md) と同じ道で届けます (= Claude の居ないタブは起こします)。
  届ける前に失敗した時、 票は変わりません。 操作者の返事を待っている票と、 閉じた票は渡せません。 操作者の答えが
  持ち主に届くまでも渡せません (= 宛先が途中で変わらないようにするため。 [操作者の答えを届ける](#操作者の答えを届ける))
- 票の本文を、 連絡の 1 行に写して回さないでください。 宛先は `show` で読みます

失敗した時は、 標準エラーに `tabs: <見出し> [<code>]: <理由>` を出して 1 で終わります。

| code | 意味と次の手 |
|---|---|
| `ticket_unknown` | その id の票がありません。 id を確かめてください |
| `ticket_closed` | 票は閉じていて、 書き足せません |
| `ticket_waiting_operator` | 票は操作者の返事を待っていて、 渡せません |
| `ticket_empty` | 題・本文・宛先・答えが空です |
| `ticket_not_waiting` | 票は操作者の返事を待っていません (= 答えの口) |
| `ticket_ask_changed` | 答えた問いが、 最後の問いではなくなっています (= 画面が見ている間に別の `ask` が足されました。 見直してから答えます) |
| `ticket_no_holder` | 票を持つタブがありません (= 持っていたタブも、 最初に頼んだタブも閉じられました) |
| `ticket_no_recommend` | 最後の問いに推奨がありません (= 推奨では答えられません) |
| `ticket_bad_answer` | 答えの形が正しくありません (= `asked_at` が無い、 `text` が文字列でない) |
| `ticket_answer_pending` | 操作者の答えが、 まだ持ち主に届いていません。 届いてから渡します |
| `ticket_bad_kind` | `--kind` が `decide` / `mac` / `report` ではありません |
| `ticket_to_self` | 自分のタブへは渡せません |
| `ticket_ask_elsewhere` | 票の家が別の機械です。 操作者に訊けるのは家の機械のタブだけです。 票を家のタブへ渡すか、 この機械で票を開いて訊きます |
| `ticket_not_holder` | 票を今持っているタブではないので、 操作者に訊けません (= `ask` は持つタブだけ。 持つタブに頼むか、 票を渡してもらいます) |
| `ticket_has_holder` | 票は、 もうタブが持っています (= 操作者が画面で渡せるのは、 持つタブが無い票だけです) |
| `ticket_elsewhere` | 票は別の機械にあります (= 操作者の画面で読み・答えるのは、 票の家の機械の画面です) |
| `ticket_inside_boundary` | その票は境界の中にあり、 別の機械のタブは関われません |
| `ticket_to_third_machine` | 票は、 その 2 台の機械のタブの間でだけ渡せます |
| `ticket_peer_down` | 票の家の機械が答えません。 何も預かっていないので、 家が戻ってから打ち直します。 理由に「済んでいるかもしれません」とあれば、 先に `show` で確かめます |
| `ticket_peer_failed` | 票の家の機械が、 code の無い失敗を返しました。 `show` で確かめてから打ち直します |
| `ticket_bad_relay` | 別の機械から届いた操作の形が正しくありません (= 2 台の client の版が違う時に出ます) |
| `ticket_unknown_sender` | このタブの id (`PWA_SID`) が backend のタブにありません |
| `ticket_local_only` | 別の機械から呼ばれました |
| `ticket_refused` | 検査コマンドが、 その本文を票に足すことを断りました。 理由に従って書き直してください |
| `ticket_outside_place` | このタブは、 その票の置き場を読めないので票に関われません |
| `ticket_place_split` | このタブが読んだ範囲が 1 つの置き場に収まらず、 票を開けません |
| `ticket_place_unknown` | 票の置き場を決められない・見つけられません |
| `ticket_check_failed` | 検査コマンドが動きませんでした。 もう一度試し、 続く時は設定を確かめてください |
| `ticket_check_missing` | 連絡を検査する機械 (`agent_message_check` がある) で、 票の検査コマンドの鍵が設定にありません。 設定に書いて backend を起動し直すまで、 その段は断ります |
| `agent_message_*` | `pass` で宛先に届ける道の失敗です。 意味と次の手は [tabs の skill](../../skills/tabs/SKILL.md) の表と同じです |
| `ticket_not_sent` / `ticket_unconfirmed` | backend に繋がらない / 答えを受け取れませんでした。 前者は何も書いていません。 後者は `show` で確かめてから、 やり直してください |

## 票の形と置き場

票 1 枚は `<置き場>/<id>.jsonl` で、 1 行が 1 件の JSON です (= 追記だけ)。 件は次の欄を持ちます。

| 欄 | 中身 |
|---|---|
| `kind` | `opened` (最初の頼み) / `operator` (操作者の原文) / `added` / `asked` / `passed` / `closed` / `answered` / `delivered` / `returned` / `seen` (最後の 4 つは backend が書く。 `tab`・`tab_title`・`tier` は空) |
| `at` | 時刻 (ISO、 UTC) |
| `tab` / `tab_title` / `tier` | 書いたタブの id・名前・階層 |
| `text` | 本文 |
| `title` | `opened` だけ |
| `ask_kind` / `recommend` | `asked` だけ (`recommend` は任意) |
| `to` | `passed` (渡した先のタブの id)・`delivered` (答えを打った先)・`returned` (戻した先。 戻す先が無ければ空) |
| `asked_at` / `recommended` | `answered` だけ (答えた問いの `at` と、 推奨で答えたか) |
| `asked_at` / `result` | `delivered` だけ (どの問いへの答えか、 `typed` / `kept` / `unconfirmed` / `refused`) |
| `from` | `returned` だけ (持っていたタブの id) |
| (`seen`) | 操作者が、 届かなかった答えを画面で確かめた印。 欄は種類と時刻だけです |
| `typed_in` | `operator` だけ (その言葉が打たれたタブの id) |

id は `<機械の名前>-<YYMMDD>-<NN>` です (例: `home-261119-01`)。 NN は機械と日ごとに 01 から数えます。 機械の名前は
設定の [`machine_name`](config.md) で、 無ければこの機械の host 名の最初の `.` までです。 年と機械の名前が入るので、
2 台で同じ id は出ず、 閉じた票を残しても来年の同じ日とは重なりません。

置き場は、 票を開く時に 1 つに決まり、 後から動きません。 検査コマンドの設定が無い時は、 すべての票が
`<根>/state/claude-pwa-client/tickets/` (根を渡さない時は `~/.claude-pwa-client/tickets/`) に置かれます。
そこにある `index.json` は、 全部の票の **置き場の鍵・今の持ち主・最初に頼んだタブ・状態・求める物** だけを持ちます
(題と本文は入れません)。 状態は `open` / `waiting-operator` / `closed` です。

## 検査コマンドを設定する

票を読み書きできるタブを、 読んだ範囲で絞る時のために、 [`agent_message_check`](agent-messages.md) と同じ形
(= 語のリスト) の検査コマンドを 5 つ、 設定の鍵で渡します。 `agent_message_check` の無い機械では任意で、 どれも
書かなければ、 その段の検査はしません (= 票は境界の外の置き場に 1 つだけで、 誰でも読み書きできます)。
`agent_message_check` のある機械では 5 つとも要ります。 欠けた鍵の段は、 検査せずに通すのではなく
`ticket_check_missing` で断り、 起動の時の log に欠けた鍵の名前を WARNING で出します。 連絡なら止まる本文が、
票なら検査されずに境界の外へ書かれるのを防ぐためです。 語の中の `{名前}` は値に置き換わります。
`{session}` は、 そのタブの Claude の会話の id (= 会話の記録 file の名前) です。 値が空になる `{名前}` は、 直前の
`--` で始まる語と一緒に省かれます (= `--typed-in {typed_in}` は、 操作者の発話が無い時は渡りません)。

| 鍵 | いつ | 語の中で使える物 | 終了 code |
|---|---|---|---|
| `ticket_place_check` | 票を開く時 | `{session}`、 `{typed_in}` (操作者の発話が打たれた会話)、 `{folder}` (= タブの階層の folder) | 0: 標準出力の 1 行目が、 票を置く folder の絶対 path。 1: 読んだ範囲が 1 つの置き場に収まらない (`ticket_place_split`)。 それ以外: `ticket_place_unknown` |
| `ticket_places_check` | backend が最初に票に触れる時と、 索引に知らない置き場の鍵が出た時 | なし | 0: 標準出力の 1 行に 1 つ、 票を置く folder の絶対 path |
| `ticket_write_check` | 票に件を足す前 | `{place}` (票の folder)、 `{text_file}`、 `{typed_in}` | 0: 足す。 1: 断る (標準エラーの最後の行が理由。 `ticket_refused`)。 それ以外: `ticket_check_failed` |
| `ticket_covers_check` | 票に関わるタブ (書き足す・求める・閉じる・渡す側と渡される側) が置き場を読めるか | `{session}`、 `{place}`、 `{folder}` (= タブの階層の folder) | 0: 関われる。 それ以外: `ticket_outside_place` |
| `ticket_read_check` | `tabs ticket show` の 1 件ごと | `{session}` (読むタブ)、 `{text_file}` | 0: 見せる。 それ以外: その件は「読めない境界の書き足し」 の 1 行に置き換わる (題も同じ扱い) |

`{text_file}` は、 判定する本文を書いた、 その run の間だけの file です。 `opened` の件は題と本文を続けた物です。

置き場の folder は、 backend が **file には書きません**。 索引は folder の path の代わりに、 その path の SHA-256 の
頭 16 文字 (= 鍵) を持ち、 鍵から folder への対応は `ticket_places_check` の答えから backend の memory の中に作ります。
`ticket_places_check` を書かない時は、 境界の外の置き場 1 つだけです。

### 検査の前に書かれた票を移す

検査コマンドを後から設定した時のために、 backend は起動のたびに 1 回、 境界の外の置き場にある票を確かめます
(`ticket_place_check` と `ticket_write_check` がある時だけ)。 票の file の行をそのまま (= 書いたタブの名前と階層も
含めて) 境界の外の置き場への書き足しとして `ticket_write_check` に掛け、 断られた票は、 開いたタブの置き場
(`ticket_place_check`、 票に操作者の発話があれば `{typed_in}` も) へ file ごと移し、 索引の置き場の鍵を書き換えます。
置き場を決められない・開いたタブの置き場も境界の外・その置き場にも置けない票は動かさず、 log に
`ticket relocate: <id> stays: <理由>` の WARNING を出します。 消すかどうかは人が決めます。

## 件を、 関わるタブが読めるかの扱い

- 書き足し (`add` / `ask` / `close` と、 `new` の最初の件) は、 足す前に `ticket_write_check` を通ります
  (= 本文が無い `close` と `pass` は判定する物が無いので通しません)
- `pass` は、 渡す側と渡される側の両方が `ticket_covers_check` を通ります
- `show` の件は、 読むタブに対して 1 件ずつ `ticket_read_check` を通ります。 止まった件は
  `{"kind": ..., "at": ..., "hidden": true, "text": "読めない境界の書き足し"}` だけになり、 誰が書いたかも出ません

## 操作者の答えを届ける

操作者は、 `ask` された票 (`waiting-operator`) に、 自分の画面から答えます。 答えは、 その票を持つタブへ届くまで
backend が預かります。 `tabs` の命令にはなく、 タブは答えの口を呼べません (= 検査の `destinations` が止めます)。

### 答えの口

`POST /tickets/<id>/answer`。 本文は JSON で、 `{"asked_at": "<画面が見ていた問いの at>", "text": "<答え>"}` か
`{"asked_at": …, "recommend": true}` (= その問いの推奨をそのまま答えにする。 この時 `text` は読みません)。
`asked_at` は、 答える問い (= その票の最後の `asked` の件) の `at` です。 同じ機械の中からだけ呼べます。

次の順に確かめて、 どれかに当たれば断ります (code は上の表)。 票が無い (`404 ticket_unknown`) → 操作者の返事を待っていない
(`409 ticket_not_waiting`) → `asked_at` が最後の問いのものでない (`409 ticket_ask_changed`) → 持つタブが空
(`409 ticket_no_holder`) → `recommend` なのに推奨が無い (`409 ticket_no_recommend`)。 文が空 (`400 ticket_empty`) と、
形が読めない (`400 ticket_bad_answer`) は、 票を見る前に断ります。

通ると、 票の file に `answered` の件を足し、 索引の状態を `open` に戻します (= 1 つの lock の中で一緒に)。 続けて答えを
**答えの列** (`<置き場の根>/state/claude-pwa-client/tickets/answer-queue.json`) に足し、 裏で届け始めます。 返事は
`{"ok": true, "id": …, "queued": true}` です。 列の 1 件は `(票の id, asked_at)` だけで、 文は持ちません (= 文は票の
`answered` の件から読みます)。 同じ鍵は 2 件になりません。 答えは操作者自身の言葉なので、 検査コマンドの
`ticket_write_check` には掛けません。 届ける時に、 持つタブが票の置き場の境界を読んでいるか (`ticket_covers_check`) だけを確かめます。

### 届け方

届けるのは次の 3 つのどれかが引き金です。 どれも同じ判定を、 答え 1 件ごとの lock の中で行い、 「打つ → 結果を見る →
列から消す」 の順に進みます (= 同時に 3 つ来ても 1 回しか打ちません)。

- 答えを列に足した時
- 持つタブの turn が終わった時 (`Stop` の hook)
- 5 秒ごとの見回り (backend の起動から 30 秒は見ません)

宛先は、 届ける時の索引の持ち主です。 封筒の 1 行目は backend の知らせの物 (`Sent by the client (the operator did not
type this):`) で、 `<ticket-answer ticket="<id>">` の中に `<operator-said>` で答えの文が入ります。 1 行目が知らせの物なので、
受けたタブが `tabs send --operator-said` で先へ運ぶことはできません。 先へ運ぶ時は票に書きます。

| 持つタブと票の今 | 手 | 列 |
|---|---|---|
| この機械に居て、 推論中でなく、 締めを頼まれていない | 打つ (眠っていれば起こす。 口座の線で止まっていれば、 起こさず預かる)。 `delivered` の件 (`typed` / `kept`) を足す | 消す |
| 推論中、 または締め (自動の入れ替え) を頼まれた会話 | 打たない (Claude Code の待ち行列にも入れない) | 残す。 入れ替えの後の会話か、 turn の終わりで打つ |
| 人が Stop を押して止めた | 推論中ではないので、 上の 1 行目 | 消す |
| 打つ前に断られた (宛先で claude が動かない・起動しない・想定外の失敗) | 何も届いていない | 残す。 打ち直す間を 5 秒から倍にして、 5 分で止める |
| 打った後に届いたか分からない (`agent_message_unconfirmed` / `agent_message_not_taken`) | 打ち直さない。 `delivered` の件 (`unconfirmed`) | 消す |
| 検査が動かない (`ticket_check_failed`)・置き場が見つからない (`ticket_place_unknown`) | 打たない | 残す (上と同じ間で打ち直す) |
| 持つタブが置き場の境界を読んでいない | 打たない。 `delivered` の件 (`refused`)。 log に WARNING | 消す |
| 持つタブが閉じられた | 下の「持ち主の戻り」 で戻してから、 この表を引き直す | 残す |
| 持つタブが空・持つタブが別の機械 | 打たない | 残す |
| 票が閉じている | 打つ (答えは消さない)。 封筒に 「票は閉じています」 の 1 文が付く。 持つタブが閉じられていれば `refused` | 消す |
| 索引に票の行が無い | 打たない。 log に WARNING | 消す |

backend を打った直後に落とすと、 起動の時の入れ直しで同じ答えが 2 回打たれることがあります。 打つ前に消すと答えが消えるので、
2 回の方を受け入れています。 起動の入れ直しは、 票の file の `answered` の件のうち、 `delivered` の件が無いものを列に戻します。

### 持ち主の戻り

60 秒ごとの見回りと、 答えを届ける前に、 閉じていない票の持つタブが生きているか見ます。

| 持つタブ | 最初に頼んだタブ | 手 |
|---|---|---|
| この機械に居る | — | なし |
| 居ない (別の機械のタブは、 ここでは見ません) | 居る | 持ち主を最初に頼んだタブへ戻す。 `returned` の件 (`from` / `to`) を足し、 そのタブへ 「票 `<id>` を持っていたタブが閉じられたので、 あなたに戻りました」 の 1 行を送る。 子のタブなら、 子のメモを `作業中` に戻す |
| 居ない | 居ない | 持ち主を空にする (`returned` の件の `to` は空)。 答えの口は `ticket_no_holder` で断る |

知らせが届かなければ票は動かず、 次の見回りでやり直します。 操作者の返事を待つ票が戻っても、 状態は待ちのままです。

### backend の log

- `ticket answer: id=… asked_at=… holder=… result=typed|kept|unconfirmed|refused|waiting|retry …` (`refused` と `unconfirmed` は WARNING)
- `ticket returned: id=… from=… to=…`
- `ticket relay: op=… id=… to=<機械> result=ok|down|refused` (= この機械のタブの操作を、 票の家へ運んだ時)
- `ticket relayed in: op=… id=… from=<機械>:<タブ>` (= 別の機械のタブの操作を、 家として受けた時)
- `ticket notified: id=… reason=waiting|delivery|no_holder` (= 通知を送った時)
- `ticket peer count: machine=… waiting=N|unreadable` (= もう 1 台の数が変わった時)

## 画面と通知

票は、 操作者の画面 (PWA と iPhone の app) で見て、 答えられます。 画面は backend の口を打つだけで、 タブが打つ口とは別です。

- **☰ の数の印**: 上の帯の ☰ に、 「見てほしい」 票の数を出します (0 の時は出しません)。 票の一覧は、 ☰ で開く会話の一覧のいちばん上の行 (📌 票。 同じ数が付きます) を押すと開きます
- **票の一覧**: 「見てほしい」「動いている」「閉じた」 (畳みます) の 3 段。 行は 題・求める物・持つタブの名前・最後の件からの経過です。
  「閉じた」 に出すのは、 最後の件 (無ければ開いた時刻) が今から 7 日以内の票だけで、 段の見出しの数も出している数です
  (= 古い閉じた票も記録には残り、 一覧に出さないだけです)。
  一番下に、 もう 1 台の機械で、 操作者の答えを待つ票の数が機械ごとに 1 行で出ます (「<機械> で答えを待つ票: N 件」。 その機械の
  画面で答えます)。 待つ票が 0 の機械は出さず、 数が読めない機械だけ「読めません」 と出します
- **票の画面**: 一番上に操作者の原文を枠で囲んで固定し、 下に件を時刻の順に出します。 件は素の文字で出し、 Markdown もリンクも
  画像も描きません (タブが書いた文が別の物に見えないように)。 下の欄は票の今で決まります

  | 票の今 | 下の欄 |
  |---|---|
  | 持つタブが無い (閉じていない) | 渡す先のタブの選びと「渡す」 |
  | 返事待ち (推奨あり / なし) | 問い・推奨・答えの欄・「推奨で」・「答える」 |
  | 答えが届く途中 (開いている / 閉じた) | 「届けています」 / 「閉じた票へ届けています」 |
  | 最後の届けが `refused` / `unconfirmed` で、 その後に件が無い | 「届けられませんでした」 / 「届いたか確かめてください」 と「確かめた」 |
  | ほか | なし |
- **チャット**: 票つきの連絡 (渡された知らせ) と、 答えを届けた知らせは、 「票 `<id>` を渡されました ▸」 「票 `<id>` に答えを届けました ▸」 の 1 行で出て、 押すと票の画面が開きます。
  タブの一覧の各行には、 そのタブが持つ票の題が 1 行出ます

### 「見てほしい」 票

次のどれかの票です。 持つタブがあるかや、 答えがあるかで決まります。

- 操作者の答えを待っている (`waiting-operator`)
- 最後の `delivered` が `refused` か `unconfirmed` で、 その後に件が無い。 画面の「確かめた」 (`seen` の件) で外れます
- 持つタブが無く、 閉じていない

### 画面の口

操作者の画面だけが使う口で、 検査の `destinations` が `local:<port>/tickets/*/answer*` を止めるので、 タブからは打てません。

| 口 | 中身 |
|---|---|
| `GET /tickets/{id}/answer` | 票を判定せずに全部返す (操作者は全部読めます)。 別の機械の票は `ticket_elsewhere` |
| `POST /tickets/{id}/answer` | 答える ([答えの口](#答えの口)) |
| `POST /tickets/{id}/answer/holder` | 持つタブが無い票を、 `to` のタブへ渡す。 返事待ちの票・答えが届く途中の票も渡せ、 答えは新しい持つタブへ届く。 タブには「操作者から渡されました」 の 1 行が先に届き、 届かなければ何も書かない。 持つタブがある票は `ticket_has_holder` |
| `POST /tickets/{id}/answer/seen` | 届かなかった答えを確かめた印 (`seen` の件) を書く。 何も無ければ書かず `written: false` |

### 統合 stream の `tickets` channel

画面は `/stream/unified` の `tickets` channel で票を受けます。 中身は `{tickets, peers}` で、 `tickets` はこの機械の票
(`GET /tickets` と同じ欄に `answer_pending`・`last_at`・`last_delivery`・`attention` を足した物)、 `peers` は、 もう 1 台の機械ごとの
`{waiting: N}` (その機械で操作者の答えを待つ票の数。 60 秒ごとに相手の一覧から読む) か `{unreadable: true}` です。 接続した時に今の 1 枚、
その後は票の file か索引・もう 1 台の数が変わった時に、 絵が変わっていれば 1 枚流します。

### 通知

票が「見てほしい」 に入った時に、 1 回通知を送ります。 通知を起こすのは、 タブが `ask` した時、 操作者の答えが `refused` / `unconfirmed` で終わった時、
持つタブも最初に頼んだタブも閉じて持つタブが無くなった時です。

- 題は、 境界の外の票なら `📌 <題>`、 境界の中の票なら `📌 Ticket <id>` (題も中身なので出しません)。 本文は、 何を求めるか (決める・Mac の前・報告) か、 答えの届け方の結果です
- 札 (`tag`) は `ticket-<id>` で、 同じ票の通知は 1 つにまとまります。 未読の数には足しません
- 声の通話がどこかでつながっている間は送りません (☰ の数は残ります)。 票の画面を開いている端末は、 音を出しません
- 押すと票の画面が開きます (PWA は `?ticket=<id>`、 iPhone の app は `claudepwa://open?ticket=<id>`)

## 2 台の機械にまたがる票

backend を 2 台で動かし、 [別の機械のタブへ送る](agent-messages.md#別の機械のタブへ送る-任意) 設定がある時、 票は 2 台の
タブの間でも使えます。

- **家の機械**: 票を開いた機械です。 票の id は家の機械の名前 (`machine_name`) で始まり、 票の file と一覧の行は家に
  だけあります。 家でない機械のタブの `add`・`close`・`show`・`pass` は、 その機械の backend が家へ運び、 家が行います。
  運ぶ前に、 この機械の検査が本文を「機械を出る連絡」として見ます
- **名前を揃える**: 家を id から引くので、 両方の機械で、 `machine_name` と、 相手の設定の `agent_message_peers` での
  呼び名を同じにします (例: 自宅の `machine_name` が `home` なら、 会社の設定でも自宅を `home` と呼ぶ)
- **預かりません**: 家が答えない時は `ticket_peer_down` で返します。 連絡と違い、 後で届ける形はありません。 家の今
  (閉じた・返事待ち) を見ずに積んだ操作は、 届いた時に断られるためです
- **操作者に訊くのは家の機械のタブだけ** (`ticket_ask_elsewhere`)。 操作者の返事を待つ票は渡せないので、 操作者が
  答える時、 票を持つタブはいつも家の機械に居ます。 操作者の答えは機械を渡りません
- **操作者の言葉は家から出ません**: 別の機械のタブが `show` で読むと、 `operator` と `answered` の行は種類と時刻だけに
  なります。 ほかの行は、 どの境界も読んでいない相手への連絡として検査されます
- **境界の中の票は家から出ません**: 別の機械のタブは関われず (`ticket_inside_boundary`)、 別の機械へ返す一覧にも
  載りません。 境界の外の票も、 別の機械へ返す一覧には題を出しません
- **渡すのはいつも家**: 家が確かめ、 宛先のタブが居る機械が名前を id にして知らせの 1 行を打ち、 届いてから家が
  持ち主を書きます。 別の機械からの知らせは、 1 行目が別の機械からの連絡の物になります
- **持ち主の戻り**: 持つタブが別の機械のタブの時は、 その機械が一覧の口に答え、 その一覧に無い時だけ閉じられたと
  みなします。 答えない間は戻しません
- 運ぶ口は全部 `/agent-messages/tickets/…` の下にあり、 設定した相手の機械からだけ呼べます (契約は
  `contracts/schema/http-endpoints.yaml`)

## 設定

`machine_name` と、 上の 5 つの鍵は [config.md](config.md) の「全体オプション」 にあります。
