# Troubleshooting

セットアップ / 運用時にハマりやすい事例と復旧手順。

## Tailscale: Chromium 系ブラウザで HTTPS 証明書エラー

`NET::ERR_CERTIFICATE_TRANSPARENCY_REQUIRED` 等で接続が拒否される場合。 Tailscale が
発行する Let's Encrypt 証明書周辺で Chromium 系ブラウザが拒否するケースが Tailscale 側の
既知 issue として残存している
([tailscale/tailscale#16179](https://github.com/tailscale/tailscale/issues/16179))。

以下を順に試す:

1. **シークレット / プライベートウィンドウで開き直す** (過去の cert state を回避する。
   上記 issue で workaround として有効報告あり)
2. **Tailscale 管理画面で HTTPS Certificates が有効か確認する**
   ([Tailscale docs](https://tailscale.com/docs/how-to/set-up-https-certificates))
3. **OS の時刻が正しいか確認する** (時刻ズレが大きいと CT 検証に失敗する)

上記で解決しない場合、 direct IP の HTTP フォールバックで暫定回避できる:

```
http://<your-tailscale-ip>:8765
```

- `<your-tailscale-ip>` は Tailscale 管理画面または `tailscale ip` で確認できる (`100.x.x.x`)
- tailnet 内の通信は WireGuard で暗号化されているため、 HTTPS を剥がしても tailnet 内では
  実害が出ない
- HTTP URL のままでもホーム画面追加 (PWA 化) は可能

## Tailscale serve: 状態確認 / 解除

```bash
tailscale serve status        # 現在の serve 設定を表示
tailscale serve reset         # 全 serve 設定をクリア
tailscale serve --bg http://localhost:8765    # backend を / に再マウント
```

複数の path mount (= `/` に backend + `/moonlight` に moonlight-web-stream) を併用する
場合は `tailscale serve status` で意図通りに登録されているか確認する。

## backend: import 事故 / `__pycache__` 残骸

backend のサブパッケージ構成や import 構造を変更した時は、 古い `__pycache__/*.pyc` が
import 事故 (= 旧名 module が残って ImportError) の温床になる。 再起動前に下記で purge:

```bash
find backend -name __pycache__ -type d -exec rm -rf {} +
```

リネーム / 移動を伴う backend の構造変更後に「直したはずなのに ImportError が出続ける」
場合はまず purge を疑う。

## SW (Service Worker) 登録が失効した / 通知が来なくなった

PWA の Service Worker が古い世代のまま居座って Web Push を受け取らなくなる場合がある:

1. iOS Safari の場合は ホーム画面のアイコンを長押し → 削除 → 再度 共有 → ホーム画面に
   追加 で再登録する
2. 通知設定もリセットされるため ⋯ メニューから「通知を有効にする」を再度実行する
3. backend 側で旧 subscription が残っている場合は backend 再起動で stale subscription を
   破棄する

`backend/secrets/` 配下の push subscription JSON を直接削除して backend を再起動すれば
完全リセットできる。

## Sunshine (macOS): encoder hang 対策

`launchctl kickstart -k` (SIGTERM) での再起動時に、 ScreenCaptureKit / VideoToolbox の
リソースが graceful shutdown 中に中途解放され、 respawn 後の encoder 初期化でハングする
事例がある。

復旧手順:

```bash
kill -9 <sunshine pid>    # SIGKILL
# KeepAlive による 10 秒後の respawn でクリーンな状態で起動する
```

OS 再起動経由では発生しない。 SIGTERM 経路を避け SIGKILL → KeepAlive respawn を運用標準
にすると安定する。

## moonlight-web-stream: ペアリング cert 不整合の復旧

ホスト再起動の挙動で moonlight-web-stream の `data.json` 内 `pair_info` と Sunshine の
`named_devices` 内 cert が不整合になる場合がある。

復旧手順:

1. moonlight-web-stream の `data.json` の `hosts` エントリを空にする
2. moonlight-web-stream を再起動
3. PWA から Add Host → Pair で PIN を表示
4. Sunshine admin (`https://localhost:47990`) の PIN タブで入力 → Send
5. 再ペアリング完了

## 音声が出ない (macOS + BlackHole 構成)

[Path B](./setup/path-b-screenshare.md) の音声ルーティングで BlackHole を audio_sink に
設定すると、 PWA 未接続時にもホスト本体スピーカーから音が出なくなる。 これは出力先が
BlackHole に固定されているため。

`switchaudio-osx` + LaunchAgent で「PWA 接続中だけ BlackHole に切り替え、 接続終了時に
元の出力に戻す」常駐スクリプトを動かす運用が前提。 詳細手順は
[Path B](./setup/path-b-screenshare.md) の「音声を PWA に流す」 section を参照。

スクリプトが死んでいると BlackHole に固定されたままになるので、 `launchctl list` で
`com.example.sunshine-audio-switch` が動いているか確認する。
