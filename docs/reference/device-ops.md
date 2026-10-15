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
| maps | `search` `route` | 場所を探す / 2 つの場所の間の経路と所要時間 (= 電車とバスは所要時間だけ) |
| home | `list` `power` `scene` | 家・部屋・機器・シーンの一覧 / 機器の入と切 / シーンを動かす |
| bluetooth | `scan` | 近くの Bluetooth の機器 |
| nfc | `read` | iPhone にかざした NFC のタグを読む (= 前に出す) |
| camera | `take` | カメラの画面を開き、 撮った写真を返す (= 前に出す。 撮るのは人) |
| scan | `document` `code` | 書類をスキャンしてページと文字を返す / QR コードやバーコードを読む (= 前に出す) |
| room | `scan` | 部屋を写して回り、 壁・ドア・窓・家具の寸法と 3D の file を返す (= 前に出す。 LiDAR の付いた iPhone) |
| photos | `recent` `text` `find_text` `labels` `find` `get` `delete` | 新しい写真 / 写っている文字 / 文字で探す / 写っている物 / 写っている物で探す / 1 枚を Mac へ / 消す (= 前に出す) |
| audio | `record` `transcribe` `sounds` `speak` | 録音 / 録った声を文字にする / 周りの音の種類 (= サイレン・拍手など) / 読み上げる (= どれも前に出す) |
| shazam | `listen` | 周りで流れている曲の名前 (= iOS 17 以降) |
| music | `search` `play` `pause` `now` `catalog_search` `catalog_play` | ライブラリの曲を探す・鳴らす・止める / 今の曲 / Apple Music のカタログを探す・鳴らす |
| alarm | `at` `timer` `list` `cancel` | アラームとタイマー (= iOS 26 以降) |
| translate | `text` | iPhone の中で訳す (= iOS 26 以降) |
| clipboard | `read` `write` | クリップボードの文字 (= 読むのは前に出す) |
| shortcuts | `run` | ショートカット app のショートカットを動かす (= 前に出す) |
| app | `open` | URL や他の app を開く (= `tel:` `sms:` `maps://` など。 前に出す) |
| message / mail | `compose` | SMS とメールの下書きの画面を出す (= 送るのは人。 前に出す) |
| auth | `check` | Face ID (= か、 パスコード) で本人か確かめる (= 前に出す) |
| notify | `post` | iPhone に通知を出す |
| focus | `status` | 集中モード (= おやすみモードなど) か |
| screentime | `pick` `block` `unblock` | 止める app を人が選ぶ / 止める / 戻す (= 使った時間は iOS が渡さない) |
| workout | `schedule` `scheduled` | Apple Watch のワークアウトの予定に足す / 予定の一覧 |
| journal | `pick` | iPhone が覚えている出来事 (= 場所・曲・運動) から人が 1 つ選んで渡す (= 前に出す) |
| device | `status` | 電池・充電中か・低電力モード・熱・空き容量・機種・iOS の版・音量・明るさ |
| network | `status` | つながっている回線 (= Wi-Fi・携帯・無し) と、 読める時は Wi-Fi の名前 |
| haptic / torch / screen | `play` / `set` / `brightness` | 振動させる (= 前に出す) / ライトの入と切 / 画面の明るさ (= 前に出す) |
| progress | `start` `update` `end` | ロック画面と Dynamic Island に作業の進み具合を出す (= 下の § ロック画面の進み具合) |

- 写っている物 (= `photos.labels` / `photos.find`) の名前は、 iPhone の画像分類の名前で英語です (= 例 `dog` `receipt` `beach`)。
  探す前に `photos.labels` で 1 枚の名前を見ると、 何で探せるかが分かります。 どこから「写っている」 と見なすかは
  `--min` (= 0〜1、 既定 0.3) で頼むたびに変えられます
- `photos.delete` は、 消す前に iPhone の画面に毎回確かめが出ます (= iOS の決まりで、 app からは飛ばせない)。 消した写真は
  「最近削除した項目」 に入ります。 アルバムに分けるといった整理は、 iCloud で同期した Mac の写真で行います

- audio と shazam はマイクかスピーカーを使うので、 声の会話の間は断ります (= 会話の途中で音の設定を変えると、 その会話の残りで
  エコー消しが効かなくなる)。 会話を終えてから頼んでください
- health・home・nfc・screentime・journal・network の Wi-Fi の名前・focus・music のカタログは、 Apple がその機能の権利を付けた
  app でしか動きません。 使える権利は Apple ID の種類 (= 無料か、 開発者の会員か) で違い、 使えない物は `... is not allowed` などで
  終わります

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

配信中は既定で 1 秒に 1 枚、 画面の絵を送ります (= 長辺 1280px の JPEG)。 backend が持つのは最後の 1 枚だけで、
`cpc device screen` がその path と、 配信中か・何秒前の絵かを出します。 止める時は、 画面の上の赤い表示か
コントロールセンターから止めます。

間隔・大きさ・画質は `backend/config.json` の `device_screen` で変えられます ([config.md](config.md) の全体オプション)。
app は配信を始める時にこの値を受け取るので、 変えた後は backend を再起動し、 配信を始め直してください。

## 起きない時

| 見えること | 原因 |
|---|---|
| `cpc device` が `not connected` | app が起きていない (= app を開くか、 声の会話を始める) |
| 命令が `needs the app on screen` で終わる | その操作は app を前に出さないとできない。 app を開いてからもう 1 度頼む |
| 命令が `... is not allowed` で終わる | その種類の許可が無い。 **設定 → <app の名前>** で許可する |
| `cpc device` が `has no /device` | backend が古い。 backend を更新して再起動する |
| ウィジェットが `Can't reach the server` | iPhone から backend に届かない (= Tailscale がつながっているか) |
| `cpc device screen` の `live` が `false` | 配信していないか、 5 秒より新しい絵が届いていない |
