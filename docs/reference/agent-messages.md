# タブどうしの連絡

あるタブの Claude から、 別のタブの Claude へ連絡を送れます。 アカウントが違うタブどうしでも届きます。
複数のタブで別々の作業をさせている時に、 「向こうのタブが持っている道具の不具合を見つけた」
「直したので新しい版に上げてほしい」 といった用件を、 人が写して運ばずに済ませるための口です。

届いた連絡は、 宛先のタブの画面に「From <送り主のタブ名>」 と付いた別の色の吹き出しで出ます。

## 使い方 (= タブの中の Claude が実行する)

```sh
curl -s http://127.0.0.1:8765/agent-messages \
  -F to='宛先のタブ名' \
  -F from="$PWA_SID" \
  -F 'text=<message.md'
```

| 項目 | 中身 |
|---|---|
| `to` | 宛先のタブの名前、 またはタブの id。 同じ名前のタブが複数ある時は id で指定する |
| `from` | 送り主のタブの id。 各タブの環境変数 `PWA_SID` に入っている |
| `text` | 本文。 `text=<ファイル` と書くとファイルの中身を送る (= 複数行でもそのまま届く) |
| `operator_said` | `true` と書くと、 送り主のタブで人が最後に打った発話を付けて送る。 書かなければ付けない (= 下の「人の発話を付けて送る」) |

port は backend を起動した port に合わせてください。 タブの名前と id の一覧は
`curl -s http://127.0.0.1:8765/sessions` で取れます。

送れるのは backend と同じ機械の中からだけです。 別の機械で動いている backend のタブへ送りたい時は、
下の「別の機械のタブへ送る」 の設定をします。

## 届く形

宛先の Claude には、 次の形で届きます。 1 行目は固定です。

```
Message from another session, relayed by the client (the operator did not type this):
<agent-message from="送り主のタブ名" session="送り主のタブの id">
本文
</agent-message>
```

返事を送る時は、 `session` の値を `to` に指定します。

### 人の発話を付けて送る

`-F operator_said=true` を足すと、 送り主のタブで人が最後に打った発話が封筒の先頭に入ります。
人に「向こうのタブへ伝えて」 と頼まれて送る連絡のように、 **その発話がこの連絡を出させた時**に使います。

```
Message from another session, relayed by the client (the operator did not type this):
<agent-message from="送り主のタブ名" session="送り主のタブの id">
<operator-said>
道具の持ち主に、 題が 2 行になると重なるのを直させて
</operator-said>
題が 2 行になると本体に重なります。 再現は見本の 3 頁目です。
</agent-message>
```

宛先の Claude は、 この連絡が人の指示から出た物かどうかを、 送り主の説明ではなく人の言葉そのもので
判断できます。 `<operator-said>` を書くのは backend だけで、 本文の側からは書けません。 送り主が
決められるのは付けるかどうかだけで、 中身は backend が会話の記録から読みます。

- **書かなければ付きません。** 人の最後の発話は、 その連絡の用件と関係が無いことの方が多く、 付けると
  宛先のタブへの指示として読まれます (= 「今日はここまで」 が、 別の用件の連絡に乗って届く)
- 付けると書いても、 入るのは送り主のタブで**最後に端末から入った発話が人の物だった時**だけです。
  送り主の今の作業が別のタブからの連絡で始まっていた時は入りません
- 画面では、 連絡の吹き出しの上部に引用として出ます
- 応答の `operator_said` が、 入れたかどうかです

人が画面から送った発話には、 この 1 行目は付きません。 Claude の端末への入力を読む外部の道具で
「人が打った発話」 と「別のタブから届いた連絡」 を分けたい時は、 この 1 行目で見分けられます。

## 人の送信と重なった時

連絡は、 宛先の Claude の入力欄へ打って届けます (= 人が画面から送る発話と同じ道)。 同じタブへの発話と連絡は
**1 通ずつ順に**打たれるので、 人が送ったのと同じ頃に連絡が届いても、 どちらも自分の文のまま届きます。
後の 1 通は、 先の 1 通が会話に書かれるのを待ってから打たれます (= Claude が作業中の間は、 打ち終えた所で
次へ進みます)。 停止 (= Escape) は並ばず、 すぐ打たれます。

## 届かない時

| 返ってくる code | 意味 |
|---|---|
| `agent_message_unknown_receiver` | その名前 / id のタブが無い |
| `agent_message_ambiguous_receiver` | 同じ名前のタブが複数ある。 返ってきた id のどれかを指定する |
| `agent_message_receiver_not_running` | 宛先のタブで Claude が動いていない。 連絡で会話を起動することはしない |
| `agent_message_receiver_not_ready` | 宛先の会話がまだ始まっていないため、 検査できない (= 検査を設定している時のみ) |
| `agent_message_refused` | 検査が連絡を通さなかった。 理由が `reason` に入っている |
| `agent_message_check_failed` | 検査を実行できなかった、 または時間内に終わらなかった |
| `agent_message_local_only` | 別の機械から呼ばれた |
| `agent_message_peer_not_allowed` | そのタブは、 その機械と連絡してよい account のタブではない |
| `agent_message_peer_unreachable` | 相手の機械の backend に繋がらなかった |
| `agent_message_unknown_peer` | (= 相手の機械へ返る) 設定されていない接続元から連絡を預けようとした |

## 別の機械のタブへ送る (任意)

backend を 2 台の機械で動かしている時、 片方のタブからもう片方のタブへ連絡を送れます。
**両方の機械の** `backend/config.json` に、 相手を 1 つずつ書きます。

```json
"agent_message_peers": {
  "home": {
    "url": "https://home-mac.example.ts.net",
    "address": "100.64.0.2",
    "accounts": ["personal"]
  }
}
```

| 項目 | 中身 |
|---|---|
| 名前 (= 上の `home`) | 宛先に書く相手の呼び名。 英数字・ハイフン・下線で 32 文字まで。 機械ごとに好きに付けてよい |
| `url` | 相手の backend に、 この機械から届く URL |
| `address` | 相手の backend からの呼び出しが、 この機械に届く時の接続元。 この接続元から来た連絡だけを、 その相手の物として受け取る |
| `accounts` | (任意) この相手と連絡してよいタブの account。 書くと、 送るのも受けるのもその account のタブだけになり、 相手に見せるタブの一覧にも他のタブは出ない。 書かなければ全部のタブ |

送る時は、 宛先を `相手の名前:タブ` と書きます。

```sh
curl -s http://127.0.0.1:8765/agent-messages \
  -F to='home:宛先のタブ名' \
  -F from="$PWA_SID" \
  -F 'text=<message.md'
```

相手の機械で連絡を受けられるタブは `curl -s http://127.0.0.1:8765/agent-messages/peers` で取れます。

別の機械から届いた連絡は、 **1 行目が別の文**になります (= この 1 行目も固定です)。 封筒の形は同じで、
`from` に相手の名前が付き、 `session` が `相手の名前:送り主のタブの id` になります。
返事は、 その `session` の値をそのまま `to` に書けば送り主へ戻ります。

```
Message from a session on another machine, relayed by the client (the operator did not type this):
<agent-message from="送り主のタブ名 @home" session="home:送り主のタブの id">
本文
</agent-message>
```

- **人の発話は機械を跨ぎません。** `operator_said=true` を付けて送っても、 別の機械への連絡には入りません。
  受け取った側も、 相手の backend が何を送ってきても `<operator-said>` を書きません。 人の発話を書けるのは
  それが打たれた機械の backend だけで、 別の機械の backend が「人がこう打った」 と言ってきても、 受け取った側には
  確かめる手段が無いからです (= 相手の機械に誰かが入っていれば、 その言葉も作れます)
- 受け取った Claude も、 端末の入力を読む外部の道具も、 1 行目だけで「この機械の外から来た連絡」 と
  見分けられます。 別の機械から来た連絡を、 人が確かめるまで止めておきたい時は、 この 1 行目で判定してください

- **どの機械から来たかは、 受け取った側が接続元で決めます。** 封筒に入る相手の名前は受け取った側の設定の物で、
  届いた中身からは取りません
- 検査を設定している時は、 **送る側と受け取る側の両方**で、 本文に対して走ります。 送る側では、 宛先の会話がその機械に
  無いので、 `{session}` には `相手の名前:タブ` (= 宛先に書いたまま) が入ります。 受け取る側では、 自分の機械の
  宛先の会話の session id が入ります
- 相手の機械のタブで Claude が動いていなければ届きません (= 同じ機械の中と同じく、 連絡で会話を起動しません)
- backend どうしの通信に、 この機能は鍵や合言葉を足しません。 **両方の backend が、 信頼できる機械だけの
  ネットワーク (= Tailscale の tailnet など) の中に在ること**が前提です

## 届ける前に検査する (任意)

連絡を届ける前に、 中身を自分のコマンドで検査できます。 `backend/config.json` の
`agent_message_check` にコマンドを 1 語ずつ書きます。

```json
"agent_message_check": ["python3", "~/bin/check-message.py", "--to", "{session}", "--text", "{file}"]
```

- `{file}` は本文を書いたファイルの path に、 `{session}` は宛先の Claude の session id に置き換わります
- 終了コードが 0 なら届けます。 0 以外なら届けず、 標準エラーの最後の 1 行を理由として送り主に返します
- 書いていなければ、 検査なしで届けます

タブごとに読ませている資料が違い、 あるタブの資料の中身を別のタブへ流したくない場合に使います。

人の発話を付けてよいかは、 別のコマンドで決められます。

```json
"agent_message_operator_check": ["python3", "~/bin/check-words.py", "--to", "{session}", "--typed-in", "{sender_session}", "--text", "{file}"]
```

- `{file}` は人の発話を書いたファイルの path に、 `{session}` は宛先の、 `{sender_session}` は送り主の
  Claude の session id に置き換わります
- 終了コードが 0 なら発話を付けます。 0 以外なら**発話を付けずに本文だけ届けます** (= 連絡は止めません)
- 書いていなければ、 送り主が付けると書いた発話はそのまま付きます
- 送り主が付けると書いていない連絡では、 このコマンドは走りません
