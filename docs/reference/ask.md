# program からタブに聞く (`tabs ask`)

同じ Mac で動く program が、 Claude Code のタブを自分の言語 model として使う仕組みです。 program は文を 1 つ
タブへ打ち、 そのターンが終わった時の最後の答えを受け取ります。 Claude Code を毎回 `claude -p` で起こす代わりに、
口座にログインしたタブを 1 つ置いておき、 そこへ聞きます。

聞けるのは、 設定で聞かれる用に作ったエージェントのタブだけです (= 下の「聞かれるエージェントを作る」)。
文は人が画面で打った時と同じ形でタブに入るので、 人やエージェントが働くタブへは打てないようにしてあります。

## 聞く

```sh
tabs ask <タブの id か名前> <文の file> [--fresh] [--timeout <秒>]
```

- 答えを標準出力に出して 0 で終わります。 答えは、 そのターンで Claude が最後に書いた文です
- `--fresh`: 文を打つ前に `/clear` を打ち、 前の問いを何も見ない新しい会話で答えさせます。 タブの id は
  変わりません。 毎回の文に全部の文脈を入れて送る program は、 これを付けると会話が溜まって重くなりません
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
| `ask_held` | タブが口座の止める線で止まっていて、 動ける口座がありません ([account-hold.md](account-hold.md)) |
| `ask_not_ready` | タブの Claude が起動しない、 入力を受けない、 `/clear` の後に新しい会話が開かない。 何も聞いていないので、 聞き直してください |
| `ask_timeout` | 待つ秒数の間に答えが終わりませんでした。 そのターンは止めてあります |
| `ask_empty` / `ask_bad_timeout` | 文が空 / 待つ秒数が 0 以下か 3600 を超えています |
| `ask_unconfirmed` | 文は打ったかもしれませんが、 答えを受け取れませんでした。 聞き直す前にタブの会話を確かめてください |
| `ask_not_sent` | backend に繋がりませんでした。 何も聞いていません |

## 口

`tabs ask` が呼ぶのは backend の `POST /sessions/{タブの id か名前}/ask` で、 form で `text`・`fresh`
(`true` / `false`)・`timeout_sec` を受けます。 答えは `{"ok": true, "id": "<タブの id>", "answer": "<文>"}`
で、 失敗は上の code を `detail.code` に持つ HTTP の誤りです。 同じ機械の中からだけ呼べます。

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

タブはこのエージェントで普通に立てます (= 画面の新しいタブ、 か `POST /sessions`)。 立てた直後のタブには
Claude が居らず、 最初の問いが Claude を起動します。 新しい folder で初めて起動する時は、 Claude Code が
folder を信頼するかを訊くので、 一度だけ画面で答えてください。
