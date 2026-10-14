# iPhone の app を作る (任意)

iPhone では、 ブラウザで開いた画面はホーム画面へ出るとマイクも声も止まります。 この app は同じ画面を包み、
エージェントとの声の会話だけを、 裏に回っても続けます ([iPhone の app で話す](../reference/voice.md#iphone-の-app-で話す))。
画面そのものは backend から読み込むので、 画面の更新に app の作り直しは要りません。

声の会話を使わないなら、 この app は要りません (= ブラウザの画面で全部の機能が使えます)。

## 要るもの

- macOS と Xcode 26 以降
- Node.js (= `frontend/` を build できる版)
- Apple ID (= 無料の物で足ります)
- iPhone (= iOS 15 以降) と、 Mac をつなぐケーブル
- iPhone から backend へ `https://` で届く URL (= [Tailscale Serve](https://tailscale.com/kb/1312/serve) など)

## 作る

```sh
cd shell
npm ci
CPC_SHELL_SERVER_URL=https://<host>.<tailnet>.ts.net npm run sync
open ios/App/App.xcodeproj
```

`CPC_SHELL_SERVER_URL` は、 iPhone から backend の画面を開く URL です。 `npm run sync` が app の設定に書き込みます
(= URL を変えた時は、 もう 1 度 `npm run sync` してから作り直す)。

Xcode で:

1. 左の一覧で `App` を選び、 **Signing & Capabilities** の **Team** に自分の Apple ID を選ぶ
2. 同じ画面の **Bundle Identifier** を、 自分だけの名前に変える (= 例 `com.example.claudepwa`。 無料の Apple ID
   では、 他の人と同じ名前は使えない)
3. iPhone をケーブルでつなぎ、 上の行き先に iPhone を選んで ▶ を押す

初めて入れた時は、 iPhone で次の 2 つを済ませます。

- **設定 → プライバシーとセキュリティ → デベロッパモード** をオンにする (= iPhone が再起動する)
- **設定 → 一般 → VPN とデバイス管理** で、 自分の Apple ID の app を **信頼** する

app を開いて 🔊 を押すと、 マイクの許可を訊かれます。

## 使う

backend に会話の部品を入れておきます ([iPhone の app で話す](../reference/voice.md#iphone-の-app-で話す))。

- 無料の Apple ID で入れた app は、 7 日で開けなくなります。 Xcode からもう 1 度 ▶ で入れ直すと、 また 7 日使えます
- app には、 組み込まれる部品 (= Capacitor・Pipecat・WebRTC) のライセンス表示が入っています
  (= `shell/ios/App/App/Acknowledgements.txt`)。 部品の版を変えた時は、 この file も新しい版の物に書き直します。
  一覧は repo の [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) にも載っています

## 落ちた時

app が落ちると、 iPhone はその時の記録を残します。 iPhone を Mac につないだまま (= ケーブルか同じ Wi-Fi)、 次で
落ちた理由と場所を出せます。 `<UDID>` は `xcrun devicectl list devices` の Identifier です。

```sh
task ios:crashes DEVICE=<UDID>                     # 一番新しい 1 件
task ios:crashes DEVICE=<UDID> SINCE=2026-10-15    # その日付から後の全部
```

「ended by: TCC — … NS…UsageDescription …」 と出たら、 その許可の文が `Info.plist` に足りていません
(= `task lint` の `ios-privacy-check` が、 足りない文をコードから探します)。

