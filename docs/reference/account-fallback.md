# 口座の逃げ先

口座の使用量が上限に近づいたら、その口座のタブを別の口座へ移して作業を続けさせ、上限が戻ったら元の口座へ戻す
仕組みです。タブは同じまま (タブの id・名前・親子の関係は変わりません)、動く口座だけが変わります。

既定では何もしません。使う口座にだけ、設定を足します。

> **想定している使い分け**: 勤務先から支給された口座と自分の口座のように、**元々別の主体に属する口座**どうしの
> 切り替えです。1 人が上限を回避する目的で複数の個人契約を回す使い方は想定していません
> ([config.md](config.md) の `accounts` を参照)。

## 設定

`config.json` の、移したい側の口座に `fallback` を足します。

```json
"accounts": {
  "work": {
    "display_name": "Work",
    "env": { "CLAUDE_CONFIG_DIR": "~/.claude-work" },
    "fallback": { "to": "personal", "at_pct": 95 }
  },
  "personal": { "display_name": "Personal", "env": {} }
}
```

| 項目 | 意味 |
|---|---|
| `to` | 逃げ先の口座 (`accounts` のキー) |
| `at_pct` | この使用率 (%) 以上になった口座のタブを移す。1 以上 100 以下の整数。既定は無い |

- 向きは「`fallback` を書いた口座 → 逃げ先」の 1 本だけです。**逃げ先の口座のタブは、その口座が上限でも移しません**
- 次の `fallback` は無いものとして扱い、起動時に log へ警告を 1 行出します
  - `to` が `accounts` に無い、または口座自身
  - 逃げ先の口座が自分の `fallback` を持っている (逆向きと、つながった連鎖)
  - `at_pct` が 1〜100 の整数でない (書いていない場合も含む)
- 逃げ先の口座の使用率は見ません。逃げ先は使い切ります
- 設定を変えた後は backend を再起動してください
- 見回りは、[自動の入れ替え](rollover.md) と同じ 60 秒ごとです

## 移す条件

次の**全部**がそろったタブを移します。

| 条件 | 内容 |
|---|---|
| 元の口座が線に届いている | その口座の最新の使用率の行 (`rate-limits.jsonl`) で、5 時間か 7 日のどちらかが `at_pct` 以上で、その窓の `*_resets_at` をまだ過ぎていない。口座の行が 1 つも無い時は何も言えないので移さない |
| タブが元の口座で動いている | すでに逃げ先へ移っているタブは対象外 |
| タブが止めても壊れない区切りにある | [眠り](sleep.md) の判定を「親が手で眠らせる時」の形で使う (下の表) |
| タブが眠っていない | 眠っているタブを移すと起こしてしまうので、見回りでは移さない。起こす時に移す (下) |

区切りの判定は、[眠り](sleep.md) の `judge(..., by_hand=True)` です。**60 分の静かな時間は待たず、入れ替えの線
(`rollover.idle.context_pct`) も見ません。** 次のどれかに当たるタブは移さず、当たらなくなった次の回に移します。

| 当たる条件 | 理由 (log) |
|---|---|
| そのタブで Claude が動いていない | `claude_not_running` |
| Claude が起動の途中 | `starting` |
| Claude が返事を作っている、または積まれた発話がある | `turn_open` |
| 会話の記録が見つからない | `no_record` |
| Claude のプロセスの下に、言語の道具以外のプロセスがある (裏のコマンド) | `processes_running` |
| 起こす予約 (`ScheduleWakeup`) が残っている | `wakeup_scheduled` |
| 定期の予約 (`CronCreate`) が残っている | `cron_scheduled` |
| 会話の最後が、結果のまだ無い道具の呼び出し (結果待ち) | `awaiting_tool_result` |
| 声の通話中 | `voice_call` |
| 自動の入れ替えの最中 | `rolling_over` |

**ターンの途中で上限に当たって止まったタブは、止まったこと自体を区切りとして移します。** 会話の最後が、
Claude Code が上限で止まった時に書く行 (`isApiErrorMessage: true`、`error: "rate_limit"`、一時的な混雑を示す
`apiErrorIsTransient` が付かないもの) のタブです。この場合、返事の途中・裏のコマンド・予約は見ません。
声の通話中と自動の入れ替えの最中だけは、止まったタブでも移しません。

区切りに当たらなかった理由は、同じ理由が続いている間は log に 1 回だけ出ます。

```
account fallback: waits session=ses_0123456789ab account=work reasons=turn_open,processes_running
```

## 移す手順

1. 元の口座が線に届いていることと、タブが区切りにあることを、移す直前に確かめます
2. タブの会話を、**逃げ先の口座の** projects folder に新しい会話として書きます
   - 止まっていないタブ: 最後の「終わったターン、または人の発話」まで
   - 止まったタブ: そのターンの道具の結果までを残し、上限で止まった時の行だけを落とす
3. 設定に `lineage_hook` があれば、その命令を 1 回呼びます ([config.md](config.md))。失敗した時はタブに触らず、
   書いた会話を消して、次の回にもう一度試します
4. タブの Claude を止め、同じタブを、書いた会話の `--resume` で立て直します
5. タブの定義 (`session_meta.json`) に、本来の口座 (`fallback_from`) と、書いた会話の path (`fallback_copy`) を保存します
6. **止まっていたタブには、続けての連絡を 1 通送ります。** 止まっていないタブには何も送りません

続けての連絡は、client の連絡の 1 行目 (「client が送った、人が打っていない」と分かる固定の行) で始まります。

```
Sent by the client (the operator did not type this):
<account-move from="work" to="personal" reason="limit">
A usage limit stopped this session, so the client moved it to another account. Carry on with the work you were doing before it stopped.
</account-move>
```

どこかの手順が失敗した時、タブは元の口座のまま残り、log に理由が 1 行出ます。

```
account fallback: could not move session=ses_0123456789ab from=work to=personal: <理由>
```

### 眠っているタブ

見回りは眠っているタブを移しません (移すと起こしてしまうため)。眠っているタブが起きる時に、元の口座が線に届いて
いれば、その場で逃げ先へ移してから起こします。眠っているタブは、眠った時点で区切りにあります。

## 戻す

移っているタブは、元の口座が**線を下回った**か、**線に届いていた窓の `*_resets_at` を過ぎた**ら、同じ区切りの
判定で元の口座へ戻します。手順は移す時と同じで、向きだけが逆です。止まっていたタブには、同じ形の続けての連絡を
1 通送ります。

- 戻した時、**逃げ先の口座の folder に client が書いた会話の写し (`fallback_copy`) は、client 自身が消します。**
  消すのは、設定した口座の projects folder の直下にある `.jsonl` だけです。タブの会話の記録は消しません
- 全部のタブが逃げ先へ移っている間は、元の口座に新しい使用率の行が増えません。そのため戻るのは、線に届いていた
  窓の `*_resets_at` を過ぎた時です (7 日の窓が線に届いている間は、その窓が戻るまで戻りません)
- 移っている間に `fallback` を設定から消した時も、タブは区切りで元の口座へ戻します

## 見え方

- 会話の一覧の口座の札は、**今動いている口座**を示します (移っている間は逃げ先)
- 別の機械へ連絡してよいかの判定 ([agent-messages.md](agent-messages.md) の `accounts`) は、**タブの本来の口座**で
  行います。逃げ先へ移っている間だけ送れるようにはなりません
- プッシュ通知は出しません
- backend の log に、移した・戻した・写しを消した、が 1 行ずつ出ます

```
account fallback: moved session=ses_0123456789ab from=work to=personal stopped_by_limit=False
account fallback: returned session=ses_0123456789ab from=personal to=work stopped_by_limit=False
account move: deleted the record the client wrote path=~/.claude/projects/-path-to-agent/3f2a….jsonl
```

上限で止まったまま残ったタブを、上限が戻った時に続けさせる仕組みは [limit-resume.md](limit-resume.md) です。

## 動かない時

| 見えること | 原因 |
|---|---|
| 移らない | 口座に `fallback` が無い / 警告の出た `fallback` / 設定の後に backend を再起動していない / `rate-limits.jsonl` にその口座の行が無い |
| `account fallback: waits ... reasons=` が出続ける | 区切りに当たっていない。理由は上の表の通り |
| `account fallback: could not move ...` が出る | 会話を写せない (切れ目がまだ無い等) / `lineage_hook` が失敗した / 移した先で会話を開けなかった。次の回にもう一度試す |
| 戻らない | 元の口座の使用率の行が、まだ線以上で `*_resets_at` が先 / タブが区切りにいない |
| 上限で止まったのに移らない | 会話の最後の行が上の形の行でない (一時的な混雑など)。または元の口座の使用率が線に届いていない |
