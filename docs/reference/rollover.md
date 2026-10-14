# 会話の自動の入れ替え

会話が長くなると context が埋まり、 応答が遅く高くなります。 自動の入れ替えは、 context が決めた割合に
届いた会話に「区切りで締めて、 次の会話へ引き継いで」 と頼み、 締め終えたら同じタブで新しい会話を
起動し直す仕組みです。 人が「終わり」 と言ったり、 タブを作り直したりしなくても、 会話が入れ替わります。

何を書き残して引き継ぐかは Claude の側 (= そのエージェントの `CLAUDE.md` など) が決めます。 この仕組みが
するのは、 頼む時機を見張ることと、 頼まれたらタブを起動し直すことの 2 つです。

既定では何もしません。 使うエージェントにだけ、 条件を設定します。

## 設定

`backend/config.json` の、 使いたいエージェントに `rollover` を足します。

```json
"agents": {
  "agent_a": {
    "cwd": "/path/to/agent_a",
    "launch_alias": "agent_a",
    "rollover": {
      "working": { "context_pct": 60 },
      "idle":    { "context_pct": 40, "minutes": 50 }
    }
  }
}
```

| 項目 | いつ頼むか |
|---|---|
| `working.context_pct` | Claude が作業している最中に、 context がこの割合 (%) に届いた時 |
| `idle.context_pct` と `idle.minutes` | 手が空いているタブの context がこの割合を超えていて、 会話がこの分数だけ動いていない時 |

- 片方だけ書いても構いません。 書いていない方の条件では頼みません
- 手が空いているタブは、 context の割合だけでは頼みません。 Claude の返事を読んでいる・返事を打っている
  最中の会話を締めないためです
- context の割合は、 画面の上部に出ている値と同じ物です
- 頼むのは 1 度に 1 つのタブだけです。 頼まれたタブが締めの作業をしている間は、 次のタブに頼みません
  (= 同じ作業ディレクトリを使う会話の締めが重なるのを避けます)
- 同じ会話には、 人がそのタブで最後に発話してから 1 度だけ頼みます。 人が発話すると数え直します
- 設定を変えた後は backend を再起動してください

`idle.minutes` は、 プロンプトキャッシュが生きているうちに締めさせたい時に、 その寿命より短く置きます
(= 例: 寿命が 60 分なら 50 分)。 見張りは 60 秒ごとなので、 頼むのが最大 60 秒遅れます。

見張りは、 どれかのタブで Claude が作業を始めた時 (= 人の発話でも、 別のタブからの連絡でも) にも、
60 秒を待たずに見回ります。 作業を始めたタブは、 その見回りでは作業中と数えます。 数秒で終わる作業
(= 連絡への短い返事など) が見回りの間に収まっても、 割合を超えていれば `working` の条件で頼みます。
作業を始めた時を知るのは Claude の `UserPromptSubmit` の hook で、 導入の手順で入れる hook に含まれています。

## 流れ

1. backend が、 条件の立ったタブの Claude へ**締めを頼む発話**を届けます
2. Claude は、 作業を区切りまで進め、 次の会話に要る物を書き残してから、 **起動し直す口**を呼びます
3. backend がそのタブの Claude を終了し、 口に渡された本文を**最初の発話**にして新しい会話を起動します

画面では、 1 と 3 の発話が「自動の入れ替え」 と付いた別の色の吹き出しで出ます。 それまでの会話は
タブに残ります。

### 締めを頼む発話

1 行目は固定です。 `reason` は `context` (= 作業中に割合へ届いた) か `idle` (= 静かなまま割合を超えている) です。

```
Automatic session rollover, sent by the client (the operator did not type this):
<session-rollover phase="close" reason="context" context_pct="62" idle_minutes="0">
Context is at 62%. Wrap up at the next stopping point and hand over: write down what the next session needs, then ask the client to start it (POST /sessions/<タブの id>/rollover, form field `text` = what the next session opens with).
</session-rollover>
```

Claude が作業している最中に届いた発話は、 作業の合間に読まれます。

### 起動し直す口 (= タブの中の Claude が実行する)

```sh
curl -s http://127.0.0.1:8765/sessions/"$PWA_SID"/rollover -F 'text=<handover.txt'
```

| 項目 | 中身 |
|---|---|
| `text` | 新しい会話の最初の発話に入る本文。 次の会話が何から始めるかを書く |

port は backend を起動した port に合わせてください。 受け付けると `202` と `{"rolling": true}` を返し、
約 1 秒後にそのタブの Claude を終了します。 この口は、 締めを頼まれていない会話からも呼べます
(= Claude が自分の判断で会話を入れ替える)。 呼べるのは backend と同じ機械の中からだけです。

### 新しい会話の最初の発話

```
Automatic session rollover, sent by the client (the operator did not type this):
<session-rollover phase="start">
口に渡された本文
</session-rollover>
```

エージェントに `launcher: true` を設定している場合は、 この発話が起動ラッパに
`--first-message-file` で渡ります ([config.md](config.md) の `agents`)。

## 人の発話との見分け

2 つの発話は、 人が画面から送る発話と同じ道 (= Claude の入力欄) で届くので、 会話の記録では人の発話と
同じ行になります。 見分けは 1 行目で付けます。 この行は自動の入れ替えの発話にだけ付き、 人の送信には
付きません。

人の発話だけを指示として扱う道具 (= 端末の入力を読んで判定する hook など) を使っている場合は、
この 1 行目で始まる発話を人の発話から外してください。 [タブどうしの連絡](agent-messages.md) の
1 行目と同じ扱いです。

## 引き継ぐ本文を検査する (任意)

[タブどうしの連絡](agent-messages.md) に検査 (= `agent_message_check`) を設定している場合は、
起動し直す口に渡された本文にも同じ検査が掛かります。 新しい会話はまだ何も読んでいないので、
宛先 (= `{session}`) には、 どの会話の id でもない `rollover:<タブの id>` が渡ります。

## 起きない時

| 見えること | 原因 |
|---|---|
| 条件を超えているのに頼まれない | そのエージェントに `rollover` が無い / 設定の後に backend を再起動していない / そのタブで Claude が動いていない / 別のタブが締めの最中 / その会話にはもう頼んである |
| 口が `rollover_unknown_session` を返す | その id のタブが無い |
| 口が `rollover_empty` を返す | 本文が空 |
| 口が `rollover_local_only` を返す | 別の機械から呼ばれた |
| 口が `agent_message_refused` を返す | 検査が本文を通さなかった。 理由が `reason` に入っている |
| タブが終了した後、 会話が始まらない | 起動に失敗している。 そのタブで発話を送ると、 それが最初の発話として会話が始まる |
