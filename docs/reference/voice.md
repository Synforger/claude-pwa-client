# エージェントの返事を声にする

エージェントの返事を、 音声合成の engine で音にして、 画面で鳴らします。 上部の 🔇 を押すと 🔊 になり、
そのタブに新しく届いた返事が、 文ごとに声で返ります。

音声合成の engine は同梱していません。 [VOICEVOX](https://voicevox.hiroshiba.jp/) と同じ HTTP の口
(= `POST /audio_query` と `POST /synthesis`) を持つ engine を、 自分で起動しておきます
(= VOICEVOX / AivisSpeech など)。

既定では何もしません。 声を持たせたいエージェントにだけ、 設定を足します。

## 画面で聞く

声を持つエージェントのタブには、 上部に 🔇 のボタンが出ます。 押すと 🔊 になり、 鳴らし始めます。

- 鳴らすのは、 ON にした後に届いた返事だけです。 それまでの会話と、 タブを開いた時に読み込まれる履歴は
  鳴らしません
- 返事の文に加えて、 ツールの呼び出しに付いた説明の 1 行 (= 何をしているか) も読みます。 thinking と、
  ツールの中身は読みません
- 鳴るのは、 画面に出しているタブです。 別のタブを見ている間に届いた返事は、 戻っても鳴りません
- もう 1 度押すと 🔇 に戻り、 鳴っている音もその場で止まります
- 画面を読み込み直すと 🔇 に戻ります (= ブラウザは、 人が画面を押した後でないと音を鳴らさせません)
- 鳴らせなかった時は、 ボタンの枠が赤くなり、 理由がボタンの下に出ます。 次の文が鳴るか、 🔇 に戻すと
  消えます。 理由の意味は [起きない時](#起きない時) の表にあります

返事が書き終わってから鳴り始めます。 1 文目の音が出来た時点で鳴らし、 続きは鳴らしている間に作ります。

## 設定

`backend/config.json` の、 声を持たせたいエージェントに `voice` を足します。

```json
"agents": {
  "agent_a": {
    "cwd": "/path/to/agent_a",
    "launch_alias": "agent_a",
    "voice": {
      "engine": "http://127.0.0.1:50021",
      "speaker": 3,
      "query": { "prePhonemeLength": 0.05 },
      "marks": {
        "calm":  { "speedScale": 1.1 },
        "happy": { "speedScale": 1.15, "intonationScale": 1.3 }
      },
      "default": "calm"
    }
  }
}
```

| 項目 | 中身 |
|---|---|
| `engine` | engine の URL (= `http://` か `https://`)。 port は engine を起動した port に合わせる |
| `speaker` | 声の番号 (= 整数)。 engine の `GET /speakers` が返す `styles[].id` |
| `query` (任意) | どの文にも当てる値。 engine が `POST /audio_query` に返す値のうち、 同じ名前の物を上書きする |
| `marks` (任意) | 言い方の印。 名前 (= 英字だけ) → その印の文に当てる値 |
| `default` (任意) | 印の無い文に使う印。 省くと `marks` の最初の印 |

- `query` と `marks` に書ける名前と値の範囲は、 engine が決めます (= `speedScale` / `pitchScale` /
  `intonationScale` など。 engine の説明を見てください)。 engine が返す値に無い名前は、 送りません
- 印の値に `speaker` を書くと、 その印の文だけ別の声の番号で言います (= 同じ声の別のスタイルへ切り替える時)
- 形の違う設定 (= `speaker` が文字列 / 値が数でない / `default` が `marks` に無い、 など) は、 声なしとして
  扱います。 その時は backend の log に 1 行出ます
- 設定を変えた後は backend を再起動してください

声の番号は、 engine に訊くと一覧が返ります。

```sh
curl -s http://127.0.0.1:50021/speakers
```

返事の文は、 そのまま `engine` の URL へ送られます。 engine を別の機械に置くと、 返事の文がその機械へ
渡ります。 同じ機械で、 `127.0.0.1` だけを待ち受ける形で起動するのを勧めます。

## 言い方の印

エージェントが文の頭に `[名前]` を書くと、 その文は `marks` の同じ名前の値で言われます。 どの文をどの
言い方で言うかを、 エージェントが文ごとに選べます。

```
[happy] できたよ！ 次はどうする？
結果は表にまとめておいたよ。
```

- 印は声にしません (= 文から外します)
- 画面の吹き出しにも、 印は出ません (= 会話の記録には、 書かれたまま残ります)
- 印は、 その行の終わりまで効きます。 行の中で別の印が出れば、 そこから切り替わります
- 印の無い行は `default` の印で言います
- `marks` に無い名前の `[…]` と、 文の途中の `[…]` は、 ただの文として読みます

印を使うかどうかは、 エージェントへの指示 (= そのエージェントの `CLAUDE.md` など) で決めます。 backend は、
書かれた印を読むだけです。

## 声にする物・しない物

返事は markdown で書かれています。 声で聞いて意味を成す所だけを取り出します。

| 返事の中の物 | 扱い |
|---|---|
| 文 | 句点・感嘆符・疑問符と改行で切って、 1 文ずつ声にする |
| コードブロック / 表 / 区切りの線 | 声にしない |
| インラインのコード / path / URL / 画像 / 絵文字 | その部分だけ外す |
| リンク | 表示の文字だけ読む |
| 見出し・箇条書き・引用・強調の記号 | 記号だけ外して、 文は読む |

## 口

画面が使っている backend の口です。 画面を使うだけなら、 読まなくて構いません。

呼ぶ順は 2 段です。 返事の文を `utterances` に渡して声にする文の並びを受け取り、 1 文ずつ `synthesis` に
渡して音を受け取ります。 1 文目の音が返った時点で鳴らし始められます。

`<タブの id>` は、 そのエージェントのタブの id です。 port は backend を起動した port に合わせてください。

### 声を持つタブか訊く

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice
```

```json
{ "enabled": true, "marks": ["calm", "happy"], "default": "calm" }
```

声を持たないエージェントのタブは `{"enabled": false, "marks": [], "default": ""}` を返します。

### 返事の文を、 声にする文の並びにする

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/utterances \
  -H 'Content-Type: application/json' \
  -d '{"text": "[happy] できたよ！\n場所は `~/notes/a.md` だよ。"}'
```

```json
{ "utterances": [
  { "mark": "happy", "text": "できたよ！" },
  { "mark": "calm",  "text": "場所は だよ。" }
] }
```

声にする物が無い返事 (= コードだけ、 など) は、 空の並びを返します。 この口は engine を呼びません。

### 1 文を音にする

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/synthesis \
  -H 'Content-Type: application/json' \
  -d '{"text": "できたよ！", "mark": "happy"}' -o out.wav
```

| 項目 | 中身 |
|---|---|
| `text` | 声にする 1 文 (= `utterances` が返した `text`) |
| `mark` (任意) | 言い方の印。 省くと `default` の印 |

engine が返した音 (= WAV 形式) を、 そのまま返します。 backend は音を保存しません。

## 起きない時

| 見えること | 原因 |
|---|---|
| 🔇 のボタンが出ない | そのタブのエージェントに `voice` が無い / 形が違う (= backend の log に 1 行出ている) / 設定の後に backend を再起動していない |
| 🔊 にしても鳴らない | 鳴るのは ON にした後に届いた返事だけ。 端末の音量と消音も見る |
| ボタンの下に理由が出る | 下の表の code に当たる文が出ている |

口の失敗は、 HTTP の状態と `detail.code` で返ります。

| 返る code | 状態 | 原因 |
|---|---|---|
| `voice_unknown_session` | 404 | その id のタブが無い |
| `voice_not_enabled` | 409 | そのタブのエージェントに `voice` が無い / 形が違う / 設定の後に backend を再起動していない |
| `voice_bad_request` | 400 | 本文が JSON でない / `text` が文字列でない / `mark` が文字列でない |
| `voice_unknown_mark` | 400 | `mark` が、 そのエージェントの `marks` に無い |
| `voice_nothing_to_say` | 400 | `text` に読む文字 (= 文字か数字) が無い |
| `voice_text_too_long` | 413 | 文が上限より長い。 上限の文字数が `detail.params.limit` に入っている |
| `voice_engine_unreachable` | 502 | engine に繋がらない。 engine が起動しているか、 `engine` の URL と port が合っているかを見る |
| `voice_engine_failed` | 502 | engine が断った。 `detail.params.step` がどの段か (= `audio_query` か `synthesis`)、 `detail.params.status` が engine の返した状態。 `speaker` の番号が engine に在るかを見る |
