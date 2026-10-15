# iPhone をエージェントの手にする

[iPhone の app](../setup/ios-app.md) を入れると、 Mac のタブの Claude が、 iPhone にしか無い物を読んだり、
iPhone の中で操作したりできます。 決めるのは Mac のタブの Claude で、 手を動かすのは iPhone の app です。

app にできることは、 app が backend へつないだ時に一覧で知らせます。 Mac では `cpc device` で一覧を見て、
1 つずつ頼みます。

## 頼み方

| 頼み方 | 使う物 |
|---|---|
| Mac のタブの Claude が命令で頼む | `cpc device <種類> <操作>` (= 下の § 命令) |
| 声の会話中に、 声で Claude に頼む | Claude が同じ命令を打つ |
| Siri から、 app を開かずにタブの Claude へ頼む | 「Hey Siri、 <app の名前>で頼む」 (= 下の § Siri とショートカット) |

app が頼みを受けられるのは、 app が起きている間です (= 画面に出ている時か、 声の会話が裏で続いている時)。
そうでない時は、 命令が `not connected` で終わります。

## 命令

```sh
cpc device                          # つながっているかと、 できる操作の一覧
cpc device health                   # その種類の操作と引数
cpc device health read --type steps --days 7
cpc device screen                   # 画面の配信の最後の 1 枚 (= 下の § 画面の配信)
```

- 答えは JSON で出ます。 写真のような file は Mac の `backend/data/device-files/` に書かれ、 答えにはその path が入ります
- 引数は `--<名前> <値>` で渡します。 まとめて渡す時は `--json '{"type": "steps"}'`、 待つ長さは `--timeout <秒>`
- 終わりの番号: `0` 答えた / `2` 書き方が違う / `3` app がつながっていない / `4` 一覧に無い操作 / `5` 時間切れ /
  `6` app ができなかった / `7` backend に届かない
- backend の場所は環境変数 `CPC_URL` (= 既定 `http://127.0.0.1:8765`)。 この命令は backend と同じ Mac の中からだけ使えます

## できること

一覧の真値は app の中にあります (= `cpc device` が出す物が、 入れている app の版でできること)。 下は今の版の物です。
「前に出す」 は、 app が画面に出ていないとできない操作です (= iOS の決まり)。

| 種類 | 操作 | すること |
|---|---|---|
| health | `read` `sleep` `write` | ヘルスケアの値の日ごとの合計や平均 / 睡眠 / 値を 1 つ記録する |
| location | `now` | 今いる所と住所 |
| motion | `steps` `activity` | 歩数・距離・階数 (= 7 日まで) / 歩いていたか乗り物に乗っていたか |
| home | `list` `power` `scene` | 家・部屋・機器・シーンの一覧 / 機器の入と切 / シーンを動かす |
| bluetooth | `scan` | 近くの Bluetooth の機器 |
| nfc | `read` | iPhone にかざした NFC のタグを読む (= 前に出す) |
| camera | `take` | カメラの画面を開き、 撮った写真を返す (= 前に出す。 撮るのは人) |
| photos | `recent` `text` `find_text` `labels` `find` `get` | 新しい写真 / 写っている文字 / 文字で探す / 写っている物 / 写っている物で探す / 1 枚を Mac へ |
| clipboard | `read` `write` | クリップボードの文字 (= 読むのは前に出す) |
| shortcuts | `run` | ショートカット app のショートカットを動かす (= 前に出す) |
| notify | `post` | iPhone に通知を出す |
| music | `search` `play` `pause` `now` | ミュージックのライブラリの曲を探す・鳴らす・止める / 今の曲 |
| alarm | `at` `timer` `list` `cancel` | アラームとタイマー (= iOS 26 以降) |
| translate | `text` | iPhone の中で訳す (= iOS 26 以降) |
| shazam | `listen` | 周りで流れている曲の名前 (= iOS 17 以降) |
| progress | `start` `update` `end` | ロック画面と Dynamic Island に作業の進み具合を出す (= 下の § ロック画面の進み具合) |

- 写っている物 (= `photos.labels` / `photos.find`) の名前は、 iPhone の画像分類の名前で英語です (= 例 `dog` `receipt` `beach`)。
  探す前に `photos.labels` で 1 枚の名前を見ると、 何で探せるかが分かります
- 写真を消す・アルバムに分けるといった整理は、 この app には無い操作です (= iCloud で同期した Mac の写真で行う)

種類ごとに初めて使う時、 iPhone に許可の確認が 1 回出ます。 断った種類は、 **設定 → <app の名前>** で後から許可できます。

## Siri とショートカット

「Hey Siri、 <app の名前>で頼む」 (= Siri の言語が英語なら「Ask <app の名前>」) と言うと、 送り先のタブと頼みの文を
訊かれ、 app を開かずにそのタブへ送ります。
タブの一覧は backend から取るので、 iPhone が backend へ届く所にいる必要があります。

ショートカット app では **Ask the Agent** の操作として出ます。 送り先のタブを決めておいたショートカットを作ると、
頼みの文だけを話せば済みます。

## ウィジェット

ホーム画面とロック画面に **Tabs** のウィジェットを置けます。 作業中のタブと、 答えを待っているタブの数と名前を
出し、 押すとそのタブを開きます。

中身は iPhone が決める間隔で引き直されます (= 頼んでいるのは 15 分ごと)。 今の状態を確かめたい時は、 app を
開いてください。

## ロック画面の進み具合

Claude が `progress.start` で出すと、 ロック画面と Dynamic Island に作業の名前・今していること・進み具合の棒が出ます。
`progress.update` で書き換え、 `progress.end` で終わりの印にして、 少し後に消えます。

```sh
cpc device progress start --title "Build" --detail "compiling" --fraction 0.2
cpc device progress update --detail "testing" --fraction 0.7
cpc device progress end --detail "done"
```

- 出しておけるのは 1 つです (= 新しく出すと前の物は閉じる)。 iOS は 8 時間で自動で閉じます
- 出ない時は **設定 → <app の名前> → ライブアクティビティ** がオンかを見てください

## 画面の配信

iPhone の画面を、 Mac の Claude が見られるように backend へ送ります。 始めるのは人です。

1. コントロールセンターの **画面収録** を長押しする
2. 一覧から **Broadcast** (= この app の配信) を選び、 **ブロードキャストを開始** を押す

配信中は 1 秒に 1 枚、 画面の絵を送ります (= 長辺 1280px の JPEG)。 backend が持つのは最後の 1 枚だけで、
`cpc device screen` がその path と、 配信中か・何秒前の絵かを出します。 止める時は、 画面の上の赤い表示か
コントロールセンターから止めます。

## 起きない時

| 見えること | 原因 |
|---|---|
| `cpc device` が `not connected` | app が起きていない (= app を開くか、 声の会話を始める) |
| 命令が `needs the app on screen` で終わる | その操作は app を前に出さないとできない。 app を開いてからもう 1 度頼む |
| 命令が `... is not allowed` で終わる | その種類の許可が無い。 **設定 → <app の名前>** で許可する |
| `cpc device` が `has no /device` | backend が古い。 backend を更新して再起動する |
| ウィジェットが `Can't reach the server` | iPhone から backend に届かない (= Tailscale がつながっているか) |
| `cpc device screen` の `live` が `false` | 配信していないか、 5 秒より新しい絵が届いていない |
