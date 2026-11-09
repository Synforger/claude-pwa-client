# 設定の画面

画面の ⚙ のメニューの「設定」から開く画面です。口座の線・タブの眠りと入れ替え・通知・この機械の状態を、1 か所で
見て変えられます。変えた値は `config.json` に書かれ、**次の見回りから効きます** (backend の再起動は要りません)。

タブごとの設定 (口座の固定・通知・名前) は、会話の一覧の各行の ⋯ メニューに残ります。

## 画面の中身

```
設定
├─ 口座
│  ├─ 会社・個人の今の使用率 (5 時間・7 日) と戻る時刻        見るだけ
│  ├─ 7 日の線 (曜日ごと。逃げ先のある口座は移す線、無い口座は止める線)  変えられる
│  ├─ 5 時間の線 (逃げ先のある口座)                          変えられる
│  ├─ 線で止まっているタブの数 と [全部続ける]                変えられる (線を超えている間は押せない)
│  └─ 口座を固定しているタブの一覧 と 外す                   変えられる
├─ タブの眠りと入れ替え (エージェントごと)
│  ├─ 眠るまでの分数                                        変えられる
│  ├─ 入れ替えの線 (作業中・静かな時の context と分数)          変えられる
│  └─ 子のタブの上限数                                       変えられる
├─ 通知
│  ├─ この端末の通知のオン・オフ                              変えられる
│  └─ 通知の題                                              変えられる
└─ この機械
   ├─ アプリの更新・backend の再起動                          変えられる
   └─ 動いている版・backend の起動時刻・止まりの見張りの最後の記録  見るだけ
```

### 口座

- 使用率は、`rate-limits.jsonl` の口座ごとの最新の行です。5 時間と 7 日の使用率と、その窓が戻る時刻 (`*_resets_at`) を出します。
  行が無い口座は「無し」です
- **逃げ先のある口座** (`fallback`) は、5 時間の線 (`at_pct`) と、7 日の線を曜日ごとに変えられます。曜日を空にすると、
  その曜日は `at_pct` を使います ([口座の逃げ先](account-fallback.md))
- **逃げ先の無い口座** は、7 日の止める線 (`hold`) を曜日ごとに変えられます。曜日を空にすると、その曜日は止めません
  ([口座の止める線](account-hold.md))
- 線で止まっているタブが 1 つ以上ある口座には、その数と「全部続ける」が出ます。使用率が今日の線以上の間は押せません
- 口座を固定しているタブは、一覧と「外す」が出ます。外した時の動きは、タブの ⋯ メニューの「口座の固定を外す」と同じです

### タブの眠りと入れ替え

エージェントごとに、次を変えられます。空にすると、その設定を消します。

| 項目 | 設定の場所 | 意味 |
|---|---|---|
| 眠るまでの分数 | `agents.<エージェント>.sleep.minutes` | 1 以上の整数。空ならそのエージェントのタブは眠らない ([眠り](sleep.md)) |
| 作業中の context | `agents.<エージェント>.rollover.working.context_pct` | 1〜100。入れ替えを頼む線 ([自動の入れ替え](rollover.md)) |
| 静かな時の context | `agents.<エージェント>.rollover.idle.context_pct` | 1〜100 |
| 静かな時の分数 | `agents.<エージェント>.rollover.idle.minutes` | 1 以上 |

子のタブの上限数 (`child_sessions_max`) は 0 以上の整数です。空にすると既定 (5) に戻ります ([子のタブ](child-sessions.md))。

### 通知

- この端末の通知のオン・オフは、この端末だけの設定です (`config.json` には書きません)
- 通知の題は `notification_title` です。空にすると既定 (`Notification`) に戻ります

### この機械

- アプリの更新と backend の再起動は、今までの ⚙ のメニューの項目です。ここへ移りました
- 動いている版は、backend が起動した時の `pyproject.toml` の版です。backend の起動時刻と、止まりの見張り
  (event loop が止まった時に stack を書く仕組み) の最後の記録 (いつ戻ったか・何秒止まったか) も出ます。記録が無い時は「無し」です

## 口

| 口 | 内容 |
|---|---|
| `GET /settings` | 画面が出す値を返す |
| `PUT /settings` | 許した欄だけを部分的に受け、確かめて、`config.json` に書き、読み直す |
| `POST /accounts/{口座}/continue` | 線で止まったタブを続ける ([口座の止める線](account-hold.md#続ける)) |

### `GET /settings`

`accounts` (口座ごとの `usage`・`mode` (`fallback` / `hold` / `none`)・`fallback`・`hold`・`held_count`・`tabs` (その口座で動くタブの数の内訳)・`can_continue`・`pinned_tabs`)、
`agents` (エージェントごとの `sleep_minutes` と `rollover`)、`child_sessions_max`、`notification_title`、`machine`
(`version`・`backend_started_at`・`loop_stall`)、`limits` (入力の上限と下限) を返します。

### `PUT /settings`

`config.json` と同じ形で、変える欄だけを書きます。`null` はその欄を消します。

```json
{
  "accounts": { "personal": { "hold": { "seven_day_at_pct": { "mon": 70, "tue": null } } } },
  "agents": { "agent_a": { "sleep": { "minutes": 30 } } },
  "child_sessions_max": 4
}
```

許す欄は次だけです。それ以外の欄を 1 つでも含むと、全体を `400` (`settings_rejected`) で断り、何も書きません。

| 欄 | 値 |
|---|---|
| `accounts.<口座>.fallback.at_pct` | 1〜100 の整数 (消せない) |
| `accounts.<口座>.fallback.seven_day_at_pct.<曜日>` | 1〜100 の整数、または `null` |
| `accounts.<口座>.hold.seven_day_at_pct.<曜日>` | 1〜100 の整数、または `null` (口座に `hold` が無ければ作る) |
| `agents.<エージェント>.sleep.minutes` | 1 以上の整数、または `null` |
| `agents.<エージェント>.rollover.working.context_pct` / `idle.context_pct` | 1〜100 の数、または `null` |
| `agents.<エージェント>.rollover.idle.minutes` | 1 以上の数、または `null` |
| `child_sessions_max` | 0 以上の整数、または `null` |
| `notification_title` | 空でない文字列、または `null` |

- 値は、読む側 (逃げ先・止める線・眠り・入れ替え) と同じ規則で確かめます。`fallback` を持つ口座への `hold` のように、
  設定の全体として使えなくなる変え方も断ります。`400` の `params.reasons` に、断った欄と理由が 1 行ずつ入ります
- 書くのは、今の `config.json` を読み直した上での変更です。ほかの欄は、値も並びも字下げも変えません。一時 file に書いてから置き換えるので、
  書いている途中の file は読まれません
- 書いた後に、client が設定を読み直します。次の見回りから、逃げ先・止める線・眠り・入れ替え・通知の題・子の上限が新しい値で動きます
- 答えは、変えた後の `GET /settings` と同じ中身です。file を読めない・書けない時は `500` (`settings_not_written`) です
