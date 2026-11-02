# 階層のタブ

エージェントの folder が持つ階層 (= エージェントそのもの・プロジェクト・サブプロジェクト) ごとに、 backend が
タブを 1 つずつ一覧に置く仕組みです。 置いたタブで話し始めると、 Claude はそのタブの階層で起動します。
新しい機械や新しい場所で client を建てた時も、 階層の folder を足した時も、 タブを開いて最初に階層の名前を
打つ手間がありません。

## 入れ方

`config.json` のエージェントに `tier_tabs: true` を書きます。 起動の仕方を最初の発話から決める起動ラッパ
(= `launcher: true` と `launch_alias`) と、 エージェントの folder (= `cwd`) が要ります。

```json
"agents": {
  "agent_a": {
    "cwd": "/path/to/agents/main",
    "launch_alias": "main",
    "launcher": true,
    "tier_tabs": true
  }
}
```

## どの階層にタブが置かれるか

階層は `cwd` の folder から読みます。

| 階層 | folder | タブの名前 |
|---|---|---|
| `normal` | `cwd` そのもの | エージェントの `display_name` |
| `projects/<P>` | `cwd/projects/<P>/` | `<P>` |
| `projects/<P>/subprojects/<S>` | `cwd/projects/<P>/subprojects/<S>/` | `<P>・<S>` |

名前が `_` か `.` で始まる folder は階層ではありません (= `_archive` など)。

- backend は起動の 90 秒後に 1 回目を見て、 その後は 60 秒ごとに見ます。 1 回目を待つのは、 動いているタブの
  階層を backend が知るまでの間です
- まだタブを置いたことの無い階層にだけ、 タブを置きます。 置いた階層は `tier_tabs.json` (= 運用 state の
  `data/`) に残ります
- 初めて見た時に、 その階層のタブが既にある (= 人が開いたタブ) なら、 新しく置かずに記録だけします
- **人が閉じたタブは、 もう置きません**。 戻す時は `tabs open <階層>` を使います (= 下の「1 つだけ置き直す」)
- 置いたタブは普通のタブです (= 子のタブではありません)。 一覧では、 その階層の folder の下に並びます

## 話し始めた時

置いたタブでは、 最初の発話が届くまで Claude は動いていません。 最初の発話 (= 人の送信か、 別のタブからの
[連絡](agent-messages.md)) が届くと、 backend は次の封筒で Claude を起動し、 Claude が入力を受け取れるように
なってから、 届いた発話をそのまま次の発話として渡します。

```
Tab opened by the client for its tier (the operator did not type this):
<tab-open>
tier=projects/<P>/subprojects/<S>
</tab-open>
```

- 1 行目は固定です。 起動ラッパは `<tab-open>` の塊の `tier=` の行から階層を読み、 その階層で Claude を
  起動します ([自動の入れ替え](rollover.md) の `<session-rollover phase="start">` と、
  [子のタブ](child-sessions.md) の `<child-start>` と同じ形です)
- 届いた発話は封筒に混ぜずに、 別の発話として渡します。 人の送信は人の発話のまま記録に残ります
- 会話を終えた後 (= セッション終了) の次の発話も、 同じように封筒で起動します。 自動の入れ替えの発話は
  自分で階層を運ぶので、 封筒を付けずにそのまま起動します
- 端末の入力を読む外の道具は、 この 1 行目で始まる発話を人の発話から外してください。 タブどうしの連絡と
  自動の入れ替えの 1 行目と同じ扱いです。 画面は、 この発話を「階層のタブとして起動」 の吹き出しで出します

Claude がまだ動いていない置いたタブも、 `tabs list` に「未起動」 の状態で並び、 `tabs send` で連絡を
送れます (= 置いたタブ以外も同じです。 [連絡](agent-messages.md#claude-が動いていないタブへ送った時))。 連絡の検査 (= `agent_message_check`) は、 まだ何も読んでいない会話を宛先として通します。

## 1 つだけ置き直す

閉じた階層のタブを戻す時は、 そのエージェントのタブの中で次を打ちます。

```sh
tabs open projects/<P>
```

`tabs` は `POST /tier-tabs` を呼びます。

| 項目 | 中身 |
|---|---|
| `agent_dir` | エージェントの folder (= どれか 1 つのエージェントの `cwd`。 ほかのエージェントの `child_agent` に名指されたエージェントは数えません) |
| `tier` | `normal` / `projects/<P>` / `projects/<P>/subprojects/<S>` (= そのエージェントに folder がある階層) |

受け付けると、 置いたタブの記録 (= `GET /sessions` の 1 件と同じ形。 `tier_tab` に階層) を返します。 呼べるのは
backend と同じ機械の中からだけです。 `tier_tabs` を入れていないエージェントでも使えます。

| 断る時 | code |
|---|---|
| 別の機械から呼ばれた | `403 tier_tab_local_only` |
| `agent_dir` のエージェントが設定に無い (= 無いか、 2 つ以上ある) | `400 tier_tab_unknown_agent` |
| その階層の folder が無い | `400 tier_tab_unknown_tier` |
| その階層のタブが既にある | `409 tier_tab_exists` |
