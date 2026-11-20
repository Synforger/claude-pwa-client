# API の誤りで切れたターンの続き

Claude Code は、網や API の一時的な誤り (接続が切れた・応答が途中で切れた・時間切れ・5xx・混雑) を自分で何回か
打ち直し、途中で切れた応答も決まった回数までは自分で続けます。それでも通らないとターンを終わらせ、
`API Error: Connection lost mid-response. The response above may be incomplete.` のような誤りの行を残して、人が
打つまで止まります。上限の時と違い、後から自分で続ける予約はしません。この仕組みは、**そうして止まったタブに、
続けての連絡を送ります。** 眠っているタブは、この連絡で同じ会話のまま起きます。続けても同じ誤りで止まり続ける
時は、間を空けて打ち直し、決まった回数で諦めて、親のタブか操作者に 1 回知らせます。

設定はありません。全部のタブが対象です。

## 続ける誤り

会話の記録の最後の行 (サブエージェントの行を除く) が、次の「続ける」の行の時に、タブは止まっていると見ます。
誤りの行は `type: "assistant"`・`isApiErrorMessage: true` を持ち、判定は文ではなく値だけで行います。

| `error` | 条件 | 中身 | 続けるか |
|---|---|---|---|
| `server_error` | 下の行以外 (`apiError` が無い・`connection_failed`・`computer_slept`・`stream_idle_timeout`・それ以外の値) | 接続切れ、応答の途中で切れた、時間切れ、5xx、混雑 | 続ける |
| `server_error` | `apiError` が `tls_` で始まる、または `gateway_content_type` | 証明書と中継の設定の誤り | 続けない (設定の直しが要る) |
| `rate_limit` | `apiErrorIsTransient` が真 | 一時の混雑 | 続ける |
| `rate_limit` | それ以外 | 使用量の上限 | 続けない ([上限が戻った時の続き](limit-resume.md) が受け持つ) |
| `invalid_request`・`authentication_failed`・`model_not_found`・`max_output_tokens`・`unknown` | ― | 要求・認証・model・出力の上限など | 続けない (続けても同じか、人の判断が要る) |

誤りの行の後に何か行が来れば、止まりは消えます。人の発話、連絡、道具の結果、Esc の中断の行
(`[Request interrupted by user]`)、Claude Code が自分で続ける時の隠れた行 (`isMeta`)、誤りでない答えです。

## 送る時と待つ時

見回りは [自動の入れ替え](rollover.md) と同じ 60 秒ごとで、止まったタブごとに上から順に見ます。

| 何か | すること |
|---|---|
| 誤りの行が 1 時間より古い | 送らない (backend が長く止まっていた時の古い止まりで、まとめて起こさない) |
| program に聞かれる用のタブ ([ask.md](ask.md))・報告を終えた子・[止める線](account-hold.md) で止めたタブ・動ける口座が無いタブ・別の続けての連絡を持つタブ ([口座の移し替え](account-fallback.md) の借りか、止めている間に預かった連絡) | 送らない (それぞれの仕組みが続けさせる) |
| Claude が動いていない、眠ってもいないタブ | 送らない (このために起動はしない) |
| 起きていて区切りにいない (答えの途中・裏の仕事。Claude Code は答え終えた後も数分は仕事中に見える) | 待つ |
| 続けての連絡を送ってから 3 分たっていない | 待つ (届けば、その発話の行で止まりが消える) |
| 送ってから 3 分たっても止まりが同じ | 届かなかったと見て、もう 1 回だけ送る。2 回送っても同じなら諦める |
| 連続の数が 3 | 待たずに諦める |
| 誤りの行から、連続の数で決まる待ちがたっていない | 待つ |
| それ以外 | 送る |

**連続の数**は、記録の終わりから数えて、この仕組みの連絡で始まったターンが、また続ける誤りで終わった回数です。
途中まで答えを書いてから切れたターンも数えます (途中で切れた応答は、必ず前半を書いてから誤りの行を書くので、
数えないと、切れ続ける障害の間ずっと送り続けます)。人の発話や別の連絡でターンが始まると 0 に戻ります。裏の仕事の
終わりの知らせ (`origin.kind: "task-notification"`) では戻りません。記録から毎回数え直すので、backend を
再起動しても変わりません。

| 連続の数 | 誤りの行から送るまでの待ち |
|---|---|
| 0 (最初の誤り) | 30 秒 |
| 1 | 5 分 |
| 2 | 15 分 |
| 3 | 諦める |

送る直前に、タブを ([口座の移し替え](account-fallback.md) などと共通の印で) 押さえ、記録を読み直して判定し直します。
同じ見回りの間に別の仕組みが先に連絡を送っていれば、止まりは消えているので送りません。

連絡は、client の連絡の 1 行目で始まります。誤りの文は API や中継が返した物なので、封筒の札に似た文字列は潰します。

```
Sent by the client (the operator did not type this):
<api-error-resume error="server_error" cause="connection_failed" streak="0">
Your last turn ended on an API error, so what you wrote before it may be incomplete. Carry on from where it stopped.
> API Error: Connection lost mid-response. The response above may be incomplete.
</api-error-resume>
```

`cause` は誤りの行の `apiError` (無ければ `streamCutCause`) で、`streak` は送る時の連続の数です。送ったことは、
タブの定義の `error_resumed` (誤りの行の uuid・送った時刻・送った回数。[data-schemas.md](data-schemas.md)) に
残します。

## 諦めた時

- 子のタブ: 親のタブへ、[止まった子の見回り](child-sessions.md#止まった子の見回り) と同じ連絡を `reason="api_error"`
  で 1 通送ります。見回りは、この仕組みが続けさせている間と、諦めて知らせた後は、その止まりについて黙ります
- それ以外のタブ: 操作者へ push を 1 通送ります。題はタブの名前、本文は誤りの文です

諦めた止まりは、タブの定義の `error_gave_up` に誤りの行の uuid で残し、2 回は知らせません。その後に人か別の連絡で
ターンが始まれば止まりは消え、次の誤りは連続の数 0 から数えます。

## 見え方

backend の log に出る行です。

```
error resume: session=ses_0123456789ab stop=2f6c… cause=connection_failed streak=0 asleep=0 sent=True sent_count=1
error resume: gave up session=ses_0123456789ab stop=2f6c… streak=3 sent_count=1 told=operator
```

## 動かない時

| 見えること | 原因 |
|---|---|
| 誤りで止まったのに送られない | 誤りの値が「続けない」の行 / 上の表で送らないタブ / 区切りに来ていない (`caffeinate` が残る数分) / 誤りの行が 1 時間より古い |
| 送られたのに止まったまま | 誤りが続いている。待ちを空けて送り直し、連続の数 3 で諦めて知らせる |
| 眠っているタブが起きない | `error resume: … sent=False` と、`client message:` の警告を見る (起動できなかった、または入力を受けられなかった)。2 回目でも届かなければ諦めて知らせる |
