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

送れるのは backend と同じ機械の中からだけです。

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
