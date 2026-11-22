# program からタブに聞く (`tabs ask`)

同じ Mac で動く program が、 Claude Code のタブを自分の言語 model として使う仕組みです。 program は文を 1 つ
タブへ打ち、 そのターンが終わった時の最後の答えを受け取ります。 Claude Code を毎回 `claude -p` で起こす代わりに、
口座にログインしたタブを 1 つ置いておき、 そこへ聞きます。

聞けるのは、 設定で聞かれる用に作ったエージェントのタブだけです (= 下の「聞かれるエージェントを作る」)。
文は人が画面で打った時と同じ形でタブに入るので、 人やエージェントが働くタブへは打てないようにしてあります。

## 聞く

```sh
tabs ask <タブの id か名前> <文の file> [--fresh | --resume <会話の id> [--fork]] [--stream | --json] [--timeout <秒>]
```

- 答えを標準出力に出して 0 で終わります。 答えは、 そのターンで Claude が最後に書いた文です
- `--fresh`: 文を打つ前に `/clear` を打ち、 前の問いを何も見ない新しい会話で答えさせます。 タブの id は
  変わりません。 毎回の文に全部の文脈を入れて送る program は、 これを付けると会話が溜まって重くなりません
- `--stream`: 答えを 1 行 1 JSON で、 来た順に出します (= 下の「答えを途中から受け取る」)
- `--json`: 答えの文の代わりに `{"answer":"<文>","session":"<Claude の会話の id>"}` を 1 行で出します
  (= 続きを聞く時に、 どの会話の答えかを持ち帰れます。 取れなかった時の `session` は `null`)。 `--stream` では
  最後の `final` の行が同じ `session` を持つので、 付けても変わりません
- `--resume <会話の id> [--fork]`: 問いを打つ前に、 その会話を開きます (= 下の「会話を続ける・戻す」)。
  `--fresh` とは一緒に使えません
- `--timeout`: 文を打ってから答えが終わるまで待つ秒数です。 既定は 180 秒、 上限は 3600 秒です。 過ぎると
  そのターンを止め (= Escape)、 次の問いを受けられる状態に戻します
- 眠っているタブと、 まだ Claude の居ないタブは、 [タブどうしの連絡](agent-messages.md) と同じに起こしてから
  打ちます。 起こす時間は待つ秒数に入りません
- `tabs` はタブの中でなくても動きます (= `PWA_SID` は要りません)。 backend の port は既定が 8765 で、
  別の port の時は `PWA_PORT` で渡します

失敗した時は、 標準エラーに `tabs: 答えを受け取れませんでした [<code>]: <理由>` を出して 1 で終わります。

| code | 意味と次の手 |
|---|---|
| `ask_not_allowed` | タブのエージェントが聞かれる設定を持っていません。 何も打っていません |
| `ask_unknown_tab` / `ask_ambiguous_tab` | その id か名前のタブが無い / 同じ名前が 2 つ以上あります。 id で指してください |
| `ask_in_progress` | そのタブには別の問いの答えを待っています。 1 つのタブに聞けるのは 1 度に 1 つです |
| `ask_tab_busy` | タブが別の仕事の途中です。 何も打っていません |
| `ask_held` | 口座が使えません。 `detail.params.reason` が `account_hold` なら、 タブが口座の止める線で止まっていて動ける口座が無く、 何も打っていません ([account-hold.md](account-hold.md))。 `limit_stop` なら、 打った問いのターンが使用量の上限で終わりました (下の「使用量の上限に当たった時」)。 どちらも、 口座が戻るまで聞くのを止めてください |
| `ask_not_ready` | タブの Claude が起動しない、 入力を受けない、 `/clear` `/resume` `/branch` の後に会話が開かない (= `--resume` の id の会話が無い時も)。 `--resume` は Claude の居ないタブには使えません。 何も聞いていないので、 聞き直してください |
| `ask_timeout` | 待つ秒数の間に答えが終わりませんでした。 そのターンは止めてあります |
| `ask_empty` / `ask_bad_timeout` | 文が空 / 待つ秒数が 0 以下か 3600 を超えています |
| `ask_bad_args` | `--fresh` と `--resume` を一緒に付けた、 `--fork` だけを付けた、 `--resume` の値が会話の id (= uuid の形) でない。 何も打っていません |
| `ask_unconfirmed` | 文は打ったかもしれませんが、 答えを受け取れませんでした。 聞き直す前にタブの会話を確かめてください |
| `ask_not_sent` | backend に繋がりませんでした。 何も聞いていません |

## 答えを途中から受け取る (`--stream`)

`--stream` を付けると、 答えが終わるのを待たずに、 Claude Code が画面に書いた分を先に受け取れます。 語り手の返事の
ように、 地の文のあとに JSON が続く答えで、 地の文だけを先に見せたい時に使います。 標準出力は 1 行 1 JSON です。

```json
{"type":"partial","text":"霧の港町は夜明け前で、"}
{"type":"partial","text":"霧の港町は夜明け前で、 桟橋の端でランタンが揺れている。"}
{"type":"final","text":"<Stop の hook の文>","session":"<Claude の会話の id>"}
```

- `partial`: **答えのここまで全部**です。 前の行に足す形ではなく、 毎回その時の全部を出します (= 画面は書き直される
  ことがあるので、 増えるだけとは限りません)。 画面の答えが変わった時だけ、 0.5 秒ごとに読んで出します
- `final`: ターンが終わった時の最後の答え (= `--stream` なしで受け取る答えと同じ) と、 その答えを書いた Claude の会話の
  id (`session`。 取れなかった時は `null`)。 **正しい値は `final` です**。 `partial` は先に見せるためだけの物で、
  `final` と 1 字ずつは一致しません
- `error`: 失敗です。 `{"type":"error","code":"ask_timeout","message":"…"}` の形で、 code は上の表と同じです
  (`ask_held` の `detail.params` は `params` に入ります)。 打つ前の失敗 (`ask_tab_busy` など) は行にならず、 今までと
  同じ標準エラーと終了の値 1 です
- 終わりの行が `final` なら 0、 `error` か、 終わりの行が無いまま切れた時 (= `ask_unconfirmed`) は 1 で終わります。
  `error` の時は標準エラーにも、 `--stream` なしと同じ 1 行を出します

`partial` の文は、 画面に出た答えを読んで作ります。 画面は Claude Code が書いた後の形なので、 次の違いがあります。

- 答えを囲む ``` の行は画面に出ません。 `json` の囲みは、 地の文との間の空行 (`\n\n`) と、 `{` で始まる行になります
- 画面は幅で折り返した行です。 幅いっぱい (= 端末の桁数 − 4 以上) に詰まった行は次の行へつなぎ、 それより短く終わった行
  は改行のまま残します。 段落の空行は `\n\n` です。 全角の文字は幅 2 で数えます
- 最後の行は、 書いている途中の形で出ます (例: `{"narration":` だけの行)
- 長い複数行の文は、 画面に貼り付けの印 (`❯ [Pasted text #N +M lines]`) の 1 行で出ます。 その時は、 打つ直前の画面に
  無かった印 (同じ番号が会話を新しくした後にまた出た時は、 数が増えた印) の後ろを答えとして読みます。 打つ直前の画面が
  読めなかった時と、 新しい印が履歴の 400 行の外へ流れた時は、 前の問いの答えを取り違えないよう `partial` を出さず、
  `final` だけが来ます
- 画面を読めるのは、 画面に答えを書き進める Claude Code のタブです。 書き終わってから 1 度に出すタブでは、
  `partial` が来ないか、 終わり際の 1 度だけになります

画面は端末の履歴も含めて読みます (最後の 400 行)。 同じ問いが履歴に何度も残っていても、 最後の問いの後ろの答えを取ります。

## 会話を続ける・戻す (`--resume`・`--fork`)

聞かれるタブの会話は、 `--fresh` を付けない限り、 前の問いの続きになります。 前の会話へ戻ったり、 ある所から枝分かれ
させたりする時に使います。 会話の id は、 `--json` の `session` (= 答えを書いた会話) か、 `--stream` の `final` の
`session` で受け取ります。

```sh
tabs ask <タブ> q.txt --json                          # {"answer":"…","session":"7565f8b3-…"}
tabs ask <タブ> q2.txt --resume 7565f8b3-… --json     # その会話を開いて聞く。 その会話はそのまま続く
tabs ask <タブ> q3.txt --resume 7565f8b3-… --fork     # その会話の枝に聞く。 元の会話は問いの前のまま残る
```

- `--resume <id>`: 問いを打つ前に `/resume <id>` を打ち、 その id の会話が開いたことを知らせる `SessionStart` の hook を
  待ちます (= 確かめの窓は出ず、 約 1 秒)。 そのタブがもうその会話に居る時は、 何も打ちません
- `--fork`: `--resume` の後に `/branch` を打ち、 新しい会話 (= 新しい id) が開くのを待ちます (= 約 4 秒)。 問いはその
  枝に入り、 答えの `session` も枝の id です。 `--resume` で開いた元の会話は残り、 枝への問いは入りません
- 会話が開かなかった時 (= id の会話が無い、 30 秒以内に hook が来ない) は、 Escape を 1 回だけ押して (= `/resume` の
  検索の窓が開いたままタブに残らないように) `ask_not_ready` で終わります。 問いは打っていません
- 開いた後の問いは、 次の問いからも同じ会話の続きです。 別の問いで元へ戻る時は、 もう一度 `--resume` を付けます
- Claude の居ないタブには使えません (`ask_not_ready`)。 まず `--resume` なしで 1 度聞いて、 Claude を起動してください

## 待つ間に backend が止まった時

backend は止まる合図を受けると、 待っている問いを待つ秒数の前に終わらせます。 `detail.params.reason` は
`backend_stopping` です。

- 問いを打つ前なら `ask_not_ready` です。 何も聞いていないので、 backend の起動を待ってから聞き直してください
- 打ち始めた後なら `ask_unconfirmed` です。 ターンはタブで続くので、 聞き直す前にタブの会話を確かめてください。
  backend は Escape を押しません
- 答えか使用量の上限がもう出ていれば、 そちらを返します
- `--stream` の流れは、 最後の `error` の行で終わります

## 使用量の上限に当たった時

タブの口座が使用量の上限 (5 時間や週の枠) に当たると、 Claude Code はそのターンを答えずに終え、 枠が戻った時に
自分で続ける予約をします。 このターンには `Stop` の hook が来ないので、 backend は待つ間にタブの会話の記録を
1 秒ごとに見て、 上限で終わった行が出たら待つ秒数を待たずに `ask_held` で返します。

- `detail.params` は `reason: "limit_stop"`・`limit_message` (Claude Code の文そのまま。 例えば
  `You've hit your 5-hour limit · resets 8:30am (Asia/Tokyo)`)・`continuation_cancelled` です。 理由の文にも
  `limit_message` が入るので、 `tabs ask` の 1 行で戻りの時刻が読めます
- 返す前に、 Claude Code の予約を Escape で取り消します。 取り消さないと、 枠が戻った時にタブが前の問いに
  自分で答え始め、 次の問いと重なります。 `continuation_cancelled` は、 取り消せた時 `true`、 取り消しの
  記録を見られなかった時 (= 2 回押しても出ない、 1 回押した所で backend が止まる) `false`、 予約が無かった時 `null` です
- 打った問いはタブの会話に残っています。 聞き直す時は `--fresh` を付けてください
- 一時的な混み合い (Claude Code が自分でやり直す 429) では返さず、 そのまま答えを待ちます。 上限以外の API の
  誤りでターンが終わった時は、 今は `ask_timeout` になります

聞かれる用のタブには、 client が自分で書く連絡 (口座の移しと止める線の頼みと続け、 [上限明けの続け](limit-resume.md)、
子の止まりの知らせ) を打ちません。 聞き直すのは program の側の仕事で、 終わった問いへの「続けて」は次の問いの
答えを取り合うためです。

## 口

`tabs ask` が呼ぶのは backend の `POST /sessions/{タブの id か名前}/ask` で、 form で `text`・`fresh`
(`true` / `false`)・`resume` (会話の id)・`fork` (`true` / `false`)・`timeout_sec`・`stream` (`true` / `false`) を受けます。
答えは `{"ok": true, "id": "<タブの id>", "answer": "<文>", "session": "<会話の id>"}`
で、 失敗は上の code を `detail.code` に持つ HTTP の誤りです。 `stream=true` の時は、 打つところまでは同じ
(= 失敗は HTTP の誤り) で、 そのあとの答えは NDJSON (= 1 行 1 JSON) の流れ (= 上の `partial` `final` `error` の行) です。
同じ機械の中からだけ呼べます。

答えは Claude Code の `Stop` の hook が運ぶ最後の文 (`last_assistant_message`) です。 hook を backend へ
送る設定 (= `pwa-hook.sh`) が、 そのタブの Claude にも要ります。

## 聞かれるエージェントを作る

`config.json` の `agents` に、 聞かれる用のエージェントを 1 つ足します。

```json
"agent_head": {
  "cwd": "/path/to/an/empty/folder",
  "model": "Opus",
  "display_name": "Story model",
  "launch_alias": "/path/to/claude-pwa-client/bin/claude-launcher --model opus --tools '' --strict-mcp-config --setting-sources project",
  "launcher": true,
  "ask": true,
  "sleep": {"minutes": 60}
}
```

- `ask: true` が、 このエージェントのタブに聞いてよい印です
- `cwd` は `CLAUDE.md` の無い空の folder にします。 Claude Code は作業の folder とその上の `CLAUDE.md` を
  毎回読むので、 エージェントの folder で立てると、 答えにその指示が混ざります
- **道具は持たせません** (`--tools ''` と `--strict-mcp-config`)。 program の文はタブに人の入力として入るので、
  文の中に「file を消して」のような行が混ざっても、 道具の無い Claude は何も実行できません
- `--setting-sources project` は、 利用者の設定 (= `~/.claude/settings.json` の hook・言語・plugin) を読まない
  形です。 その時は、 `cwd` の folder の中の `.claude` の `settings.json` に backend へ hook を送る設定 (`SessionStart`・
  `UserPromptSubmit`・`Stop`・`Notification`) を置いてください。 置かないと答えが backend に届きません
- `bin/claude-launcher` は、 起動の script を持たないエージェントのための起動ラッパです。 alias に書いた引数を、
  新しい会話にも、 眠りや backend の再起動の後に開き直す会話にも付けます (`claude --resume` だけで開き直すと、
  `--tools` などが外れます)。 `launcher: true` と組で使います
- 自動の入れ替え (`rollover`) は置きません。 入れ替えは、 エージェントに締めの手順を回させる仕組みです。
  会話を軽く保つのは `--fresh` です
- 役ごとに前置きや model を分けてエージェントを何本も置くと、 一覧にはエージェントごとの folder が並びます。
  使う program のプロジェクトの folder にまとめる時は、 どのエージェントにも同じ `list_folder` を書きます
  ([config.md](config.md))

タブはこのエージェントで普通に立てます (= 画面の新しいタブ、 か `POST /sessions`)。 立てた直後のタブには
Claude が居らず、 最初の問いが Claude を起動します。 新しい folder で初めて起動する時は、 Claude Code が
folder を信頼するかを訊くので、 一度だけ画面で答えてください。

### program がタブを立てて片付ける

同じ役のエージェントを、 いくつもの仕事 (例えばゲームの世界ごと) で使う時は、 タブごとに一覧の folder を
渡します。 エージェントの `list_folder` より、 タブの `list_folder` が先に効きます。 どれもこの機械の中から打ちます。

```
# 立てる: 題と folder を付ける (folder は <エージェントの key>/<folder>/... の形)
curl -X POST http://127.0.0.1:<port>/sessions -H 'Content-Type: application/json' \
  -d '{"agent_id": "<聞かれるエージェント>", "title": "語り手", "list_folder": "<agent>/<プロジェクト>/<世界>"}'

# 付け替える・題を変える (list_folder を null か "" にすると、 エージェントの folder に戻る)
curl -X PATCH http://127.0.0.1:<port>/sessions/<タブの id> -H 'Content-Type: application/json' \
  -d '{"title": "<新しい題>", "list_folder": "<agent>/<プロジェクト>/<別の世界>"}'

# 片付ける: タブとその Claude を消す
curl -X DELETE http://127.0.0.1:<port>/sessions/<タブの id>
```

- 題は役の名前だけにします。 一覧は folder で分かれるので、 世界やプロジェクトの名前を題の頭に付けると、
  同じ名前が folder と題に 2 回並びます
- 答えは、 そのタブの行 (`id`・`title`・`list_folder` を持つ) です。 形の違う `list_folder` は
  `400 invalid_list_folder` で、 タブは作られず、 付け替えでは題も変わりません
- `list_folder` はタブと一緒に保存され、 backend を再起動しても残ります
- 使わないタブを眠らせるのは、 エージェントの `sleep` (= 聞かれない時間の後に眠る) です。 眠ったタブは、
  次の問いで同じ会話のまま起きます
