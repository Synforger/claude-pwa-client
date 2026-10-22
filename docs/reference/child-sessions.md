# 子のタブ

タブの中の Claude が、 仕事を渡すために別のタブ (= 子のタブ) を立てる仕組みです。 子のタブは自分の会話を
持つので、 立てたタブ (= 親) の会話が終わっても、 [自動の入れ替え](rollover.md) で起動し直しても回り続けます。
子は終わった時に [タブどうしの連絡](agent-messages.md) で親へ結果を返し、 親が受け取ってから閉じます。

Claude Code の sub-agent に近い使い方ですが、 sub-agent は親の会話の中でしか動けません。 子のタブは画面の
一覧に出る普通のタブなので、 人も中を開いて見られます。

## 立てる口 (= タブの中の Claude が実行する)

```sh
curl -s http://127.0.0.1:8765/sessions/"$PWA_SID"/children \
  -F title='build the parser' -F 'text=<task.txt'
```

| 項目 | 中身 |
|---|---|
| `agent_id` (任意) | 子のタブのエージェント (= `config.json` の `agents` の key)。 省くと、 親のエージェントの `child_agent`。 それも無ければ親と同じエージェント |
| `text` | 子のタブの最初の発話に入る本文 (= 渡す仕事) |
| `title` (任意) | 子のタブの名前。 省くとエージェントの既定の名前 |

port は backend を起動した port に合わせてください。 受け付けると、 立てたタブの記録 (= `GET /sessions` の
1 件と同じ形) に `started` (= 最初の発話を渡せたか) を足して返します。 呼べるのは backend と同じ機械の中から
だけです。

- 子のタブは親と同じアカウントで動きます
- 子のタブの通知は、 立てた時はオフです (= 進みは親への報告で届くため。 画面の ⚙ で入れ直せます)
- 子の記録は `parent_id` に親のタブの id を、 `child` に `true` を持ちます
- タブの id は自動の入れ替えでも変わりません。 子は親のタブの id 宛てに連絡を送れば、 親の今の会話に届きます

## 最初の発話

親のタブから届いた連絡と同じ封筒です ([agent-messages.md](agent-messages.md))。

```
Message from another session, relayed by the client (the operator did not type this):
<agent-message from="<親のタブの名前>" session="<親のタブの id>">
口に渡された本文
</agent-message>
```

エージェントに `launcher: true` を設定している場合は、 この発話が起動ラッパに `--first-message-file` で
渡ります ([config.md](config.md) の `agents`)。

## 子のタブだけ起動の仕方を変える

子用のエージェントを別に設定し、 親のエージェントの `child_agent` にその key を書きます。 例えば起動ラッパに
子のタブであることを伝える引数を付けると、 子のタブは軽い起動で始められます。

```json
"agents": {
  "agent_a":     { "cwd": "/path/to/agent_a", "launch_alias": "agent_a", "launcher": true, "child_agent": "agent_a_sub" },
  "agent_a_sub": { "cwd": "/path/to/agent_a", "launch_alias": "agent_a --child", "launcher": true, "display_name": "Sub-agent" }
}
```

子用のエージェントは、 画面の「新しい会話」 の一覧にも並びます。

## 数の上限

1 つのタブが同時に持てる子は、 既定で 5 つです。 `config.json` の `child_sessions_max` で変えられます。
子は同じアカウントの使用量を分け合うので、 上限を外すと一斉に立てた子が親のタブまで利用の制限に掛けます。
閉じた子は数から外れます。

## 閉じる

普通のタブと同じ `DELETE /sessions/<子のタブの id>` です。 画面の一覧の ⋯ からも閉じられます。

## 画面の一覧

子のタブは、 フォークのタブと同じように親の直下に字下げして並び、 名前の前に `↳` が付きます (= フォークは `⑂`)。
下にタブを持つ行の左の `▾` を押すと、 その下を畳みます (= `▸` で開く)。 畳んだ行には隠れているタブの数が
出ます。 畳んだかどうかは、 端末ごとに覚えます。

## 届ける前に検査する (任意)

[タブどうしの連絡](agent-messages.md) に検査 (= `agent_message_check`) を設定している場合は、 立てる口に
渡された本文にも同じ検査が掛かります。 子は親の仕事の続きとして扱い、 宛先 (= `{session}`) には親の今の
会話の id が渡ります。 親の会話の記録が見つからない時だけ、 どの会話の id でもない `child:<親のタブの id>`
(= 何も読んでいない相手) が渡ります。 検査が通らなかった時は、 タブを立てません。

子を親と違う作業ディレクトリで動かす場合は、 親が読めて子が読めない物が本文に入らないよう、 起動する側で
確かめてください (= 検査は、 子が親と同じ物を読める前提で通します)。

## 立たない時

| 見えること | 原因 |
|---|---|
| 口が `child_session_unknown_parent` を返す | その id の親のタブが無い |
| 口が `invalid_agent_id` を返す | `agent_id` か、 親のエージェントの `child_agent` が `agents` に無い |
| 口が `child_session_empty` を返す | 本文が空 |
| 口が `child_session_limit` を返す | 親の子が上限に届いている。 終わった子を閉じてから立てる |
| 口が `child_session_local_only` を返す | 別の機械から呼ばれた |
| 口が `agent_message_refused` を返す | 検査が本文を通さなかった。 理由が `reason` に入っている |
| `started` が `false` | タブは立ったが、 最初の発話を渡せなかった。 子のタブを開いて発話を送ると、 それが最初の発話として会話が始まる |
