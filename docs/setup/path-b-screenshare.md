# Path B: デスクトップ画面共有 (任意)

> このセクションは Rust nightly での自前ビルドが必要なため、 デスクトップ画面共有が
> 不要であれば [Path A](./path-a-chat.md) だけで完結する。
>
> Sunshine は Windows / Linux / macOS で動作するためホスト OS は問わない。 以下の例は
> macOS をベースに記述しており、 他 OS では同等のパッケージマネージャ / 権限設定に
> 読み替える (本リポでの動作確認は macOS)。

[Path A](./path-a-chat.md) の構成に [Sunshine](https://github.com/LizardByte/Sunshine) +
[moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) を追加すると、
PWA の 🖥 ボタンからホスト機のデスクトップ画面共有とタッチによる遠隔操作が利用できる。

## Sunshine (画面キャプチャ + Moonlight プロトコルサーバ)

```bash
# macOS の例 (Windows は scoop / インストーラ、 Linux は apt / rpm / AUR を利用):
brew tap LizardByte/homebrew
brew install sunshine-beta

# 初回起動して config UI でユーザ作成 + アプリ登録 ("Desktop" がデフォルトで入る)
sunshine
# ブラウザで https://localhost:47990 → 管理者アカウント作成
```

ホスト OS 側で画面キャプチャと入力注入の許可を Sunshine に与える:

- **macOS**: System Settings → プライバシーとセキュリティ で「画面録画」と「入力監視 /
  アクセシビリティ」の両方に Sunshine を追加する。 後者はブラウザからのタップ ・ キー入力
  をホストに注入するために必須で、 未設定の場合は画面は映るが操作が効かない
- **Windows**: 通常は追加設定不要 (UAC レベルで実行される)
- **Linux**: X11 / Wayland のキャプチャ設定が必要 (Sunshine 公式ドキュメント参照)

自動起動の例 (macOS LaunchAgent、 `~/Library/LaunchAgents/dev.lizardbyte.sunshine.plist`):

```xml
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.lizardbyte.sunshine</string>
  <key>ProgramArguments</key>
  <array><string>/opt/homebrew/bin/sunshine</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict>
</plist>
```

`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/dev.lizardbyte.sunshine.plist` で
有効化する。 Linux は systemd user service、 Windows はサービス登録で同等の常駐構成が
取れる。

> Sunshine の encoder hang / 再起動時のリソース解放問題は
> [../ops/troubleshoot.md](../ops/troubleshoot.md) の Sunshine encoder hang section を参照。

## moonlight-web-stream (Sunshine ↔ ブラウザの WebRTC ブリッジ)

公式リリースが無い OS では Rust から自前ビルドする。

```bash
# Rust nightly のインストール (macOS の例。 他 OS は rustup 公式手順)
brew install rustup
rustup default nightly

# clone + build (cargo / npm が必要)
git clone --recurse-submodules https://github.com/MrCreativ3001/moonlight-web-stream.git
cd moonlight-web-stream
cargo build --release
npm install
npm run build
cp -r dist static   # release mode は static/ を参照する

# 起動
./target/release/web-server
```

`server/config.json` の `web_server` セクション:

```json
{
  "web_server": {
    "url_path_prefix": "/moonlight",
    "default_user_id": <ペアリング後に決まる user_id>
  }
}
```

- `url_path_prefix = /moonlight` で Tailscale Serve の `/moonlight` プロキシと整合させる
- `default_user_id` を設定すると PWA の iframe が認証なしで起動できる (URL 共有のみで
  接続可能)

**自動起動** (macOS LaunchAgent 例、 `~/Library/LaunchAgents/com.example.moonlight-web-stream.plist`):

```xml
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.moonlight-web-stream</string>
  <key>ProgramArguments</key>
  <array><string>/path/to/moonlight-web-stream/target/release/web-server</string></array>
  <key>WorkingDirectory</key><string>/path/to/moonlight-web-stream</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

**ペアリング** (初回のみ):

1. ブラウザで `http://localhost:8080/` を開きユーザを作成する
2. Hosts に localhost を追加 → Pair で PIN が表示される
3. Sunshine Web UI (`https://localhost:47990`) → PIN タブで上記 PIN を入力 → Send
4. moonlight-web-stream 側で「Paired」表示になれば完了

> ペアリングが壊れた / cert 不整合の復旧は [../ops/troubleshoot.md](../ops/troubleshoot.md) の
> moonlight-web-stream ペアリング section を参照。

## Tailscale Serve で同一オリジン公開

PWA から `/moonlight/` 配下にリバースプロキシで届かせるため Tailscale Serve を設定する
(Path A で backend を `/` に提供済みの前提、 追加で `/moonlight` をマウント):

```bash
tailscale serve --bg --set-path=/moonlight http://localhost:8080/moonlight
```

これで `https://<your-host>.tail<xxxx>.ts.net/moonlight/...` の同一オリジンで
moonlight-web-stream にアクセスでき、 PWA の iframe / CORS / Cookie 制約を回避できる。

## 音声を PWA に流す (任意、 macOS 例)

Sunshine がキャプチャできる audio sink を別途用意する。 macOS では通常出力を直接 Sunshine
に渡せないため、 [BlackHole](https://github.com/ExistentialAudio/BlackHole) 等の仮想
オーディオデバイスを経由する:

```bash
brew install blackhole-2ch
```

`~/.config/sunshine/sunshine.conf` に:

```
audio_sink = BlackHole 2ch
```

この設定のままだとホスト本体のスピーカーから音が出なくなる (出力先が BlackHole に固定
されるため)。 「PWA 接続中だけ BlackHole に切り替え、 接続終了時に元の出力に戻す」 を
LaunchAgent と `switchaudio-osx` を用いた常駐スクリプトで自動化できる:

```bash
brew install switchaudio-osx
```

`~/Library/Application Support/sunshine-audio-switch/switch.sh` (抜粋):

```bash
#!/bin/bash
LOG="$HOME/.config/sunshine/sunshine.log"
TARGET="BlackHole 2ch"
STATE="/tmp/sunshine-audio-prev"
SWITCH="/opt/homebrew/bin/SwitchAudioSource"
tail -n0 -F "$LOG" | while IFS= read -r line; do
  case "$line" in
    *"New streaming session started"*)
      PREV=$("$SWITCH" -c); [ "$PREV" != "$TARGET" ] && { printf '%s' "$PREV" > "$STATE"; "$SWITCH" -s "$TARGET"; } ;;
    *"CLIENT DISCONNECTED"*)
      [ -f "$STATE" ] && { "$SWITCH" -s "$(cat $STATE)"; rm -f "$STATE"; } ;;
  esac
done
```

これを `com.example.sunshine-audio-switch.plist` として LaunchAgent 化し常駐させる。

Windows / Linux では OS のループバックオーディオで直接キャプチャできる場合が多く、 仮想
デバイスが不要なケースが多い (Sunshine 公式ドキュメントの OS 別注記を参照)。
