# エージェントの返事を声にする

エージェントの返事を、 音声合成の engine で音にして、 画面で鳴らします。 上部の 🔇 を押すと 🔊 になり、
そのタブに新しく届いた返事が、 文ごとに声で返ります。

音声合成の engine は同梱していません。 [VOICEVOX](https://voicevox.hiroshiba.jp/) と同じ HTTP の口
(= `POST /audio_query` と `POST /synthesis`) を持つ engine を、 自分で起動しておきます
(= VOICEVOX / AivisSpeech など)。

声を聞き取る engine も足すと、 入力欄の 🎙 を押して話し、 聞き取った文をそのまま送れます。 聞き取りの
engine も同梱していません。 [whisper.cpp](https://github.com/ggml-org/whisper.cpp) の `whisper-server` と同じ
HTTP の口 (= `POST /inference`) を持つ engine を、 自分で起動しておきます。

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
- ON の間に送った文には、 エージェントへ向けた印が付きます (= [声で聞いている印](#声で聞いている印))

返事が書き終わってから鳴り始めます。 1 文目の音が出来た時点で鳴らし、 続きは鳴らしている間に作ります。

## 話して送る

設定に `listen` を足したエージェントのタブには、 入力欄の右に 🎙 のボタンが出ます。

1. 🎙 を押すと、 録り始めます (= ボタンが赤くなり、 枠が脈打つ)。 🔇 だった時は 🔊 になり、 鳴っている返事はその場で止まります
2. 話し終えたら、 もう 1 度押します。 録った音が聞き取られ、 その文がそのまま送られます
3. 返事は声で返ります

- 送る文には、 打った時と同じく [声で聞いている印](#声で聞いている印) が付きます
- 入力欄に打っている途中の文には触れません
- 1 回に録れる長さには上限があり (= `GET /sessions/<タブの id>/voice` の `listen.max_seconds` 秒)、 超えるとそこで
  止まって送られます
- 何も聞き取れなかった時は、 何も送らず、 理由が 🔊 の下に出ます
- 聞き取りを待つ間に別のタブへ移ると、 その文は送りません
- マイクがまだ開いていない間 (= 許可を訊かれている間など) にもう 1 度押すと、 録り始めを取りやめます
- 初めて押した時に、 ブラウザがマイクの許可を訊きます。 マイクは、 `https://` か `localhost` で開いた画面でしか
  使えません (= ブラウザの決まり)

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
      "default": "calm",
      "listen": {
        "engine": "http://127.0.0.1:10102",
        "prompt": "Claude、PWA。"
      }
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
| `listen` (任意) | 人の声を聞き取る engine。 書くと 🎙 が出る。 下の表 |

`listen` の項目:

| 項目 | 中身 |
|---|---|
| `engine` | 聞き取りの engine の URL (= `http://` か `https://`) |
| `prompt` (任意) | 聞き取りの手がかりにする語 (= 固有名詞や略語を、 句点で区切って並べる)。 engine の `prompt` にそのまま渡る |

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

### 聞き取りの engine を起動する

`whisper-server` を、 日本語と、 形式の変換と、 声の区間の検出を有効にして起動する例です。

```sh
whisper-server --host 127.0.0.1 --port 10102 \
  --model /path/to/ggml-large-v3-turbo-q5_0.bin --language ja \
  --convert --no-timestamps \
  --vad --vad-model /path/to/ggml-silero-v5.1.2.bin
```

- `--convert` は、 ブラウザが録る形式 (= Chromium は webm/opus、 Safari は mp4/AAC) を engine の側で変換します。
  [ffmpeg](https://ffmpeg.org/) が要ります。 変換の途中の file は、 engine を起動した folder に置かれます
- `--vad` を付けないと、 無音や小さな雑音だけの録音に、 話していない文が返ることがあります
- model は whisper.cpp の配布物から選びます (= 日本語は多言語の model を使う。 `.en` の付く model は英語だけ)

録った音は、 そのまま `listen.engine` の URL へ送られます。 返事の文と同じく、 同じ機械で `127.0.0.1` だけを
待ち受ける形で起動するのを勧めます。 backend は音を保存しません。

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

## 声で聞いている印

🔊 が ON のタブで送った文には、 頭に `[voice]` が付いてエージェントに届きます。 エージェントからは、 画面の
🔊 が ON かが見えません。 この印を見れば、 返事が声で聞かれると分かり、 声に向いた書き方 (= 短く、 表や
path を文に混ぜない) へ切り替えられます。

```
[voice] 明日の予定を教えて
```

- 印が付くのは、 送った端末で 🔊 が ON の時だけです (= 別の端末で ON にしていても、 🔇 の端末から送った文には
  付きません)
- `/` で始まる command、 `!` で始まる shell、 `#` で始まる memory への文には付けません (= 頭に印が入ると、
  claude がそれを普通の発話として読むため)
- 画面の吹き出しには、 印は出ません (= 会話の記録には残ります)

印を見て書き方を変えるかどうかは、 言い方の印と同じく、 エージェントへの指示で決めます。

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

返事を声にする時は 2 段です。 返事の文を `utterances` に渡して声にする文の並びを受け取り、 1 文ずつ
`synthesis` に渡して音を受け取ります。 1 文目の音が返った時点で鳴らし始められます。 人の声は 1 段で、 録った音を
`transcription` に渡して文を受け取ります (= 送るのは、 普段の送信と同じ口です)。

`<タブの id>` は、 そのエージェントのタブの id です。 port は backend を起動した port に合わせてください。

### 声を持つタブか訊く

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice
```

```json
{ "enabled": true, "marks": ["calm", "happy"], "default": "calm", "listen": { "max_seconds": 110.8 } }
```

- `listen` は、 設定に `listen` が無ければ `null` です。 `max_seconds` は 1 回に録る長さの上限 (= 秒) です
- 声を持たないエージェントのタブは `{"enabled": false, "marks": [], "default": "", "listen": null}` を返します

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

### 録った音を文にする

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/transcription \
  -H 'Content-Type: audio/webm' --data-binary @speech.webm
```

```json
{ "text": "明日の予定を教えて" }
```

- 本文は録った音そのものです。 `Content-Type` は `audio/` で始まる形式にします
- engine が区切りごとに挟む改行は、 空白 1 つにまとめて 1 行で返します
- 声が聞き取れなかった時は `{"text": ""}` を返します

## 起きない時

| 見えること | 原因 |
|---|---|
| 🔇 のボタンが出ない | そのタブのエージェントに `voice` が無い / 形が違う (= backend の log に 1 行出ている) / 設定の後に backend を再起動していない |
| 🔊 にしても鳴らない | 鳴るのは ON にした後に届いた返事だけ。 端末の音量と消音も見る |
| 🎙 のボタンが出ない | そのエージェントの `voice` に `listen` が無い / 形が違う (= `listen` の形が違うと、 声そのものが無い扱いになる) |
| 🎙 を押すと「マイクを使えません」 と出る | ブラウザがマイクを許していない / 画面を `https://` でも `localhost` でもない URL で開いている |
| 🎙 で何も送られない | 声が聞き取れなかった (= 理由が 🔊 の下に出る)。 engine を `--vad` 無しで起動していると、 逆に話していない文が送られることがある |
| ボタンの下に理由が出る | 下の表の code に当たる文が出ている |

口の失敗は、 HTTP の状態と `detail.code` で返ります。

| 返る code | 状態 | 原因 |
|---|---|---|
| `voice_unknown_session` | 404 | その id のタブが無い |
| `voice_not_enabled` | 409 | そのタブのエージェントに `voice` が無い / 形が違う / 設定の後に backend を再起動していない |
| `voice_bad_request` | 400 | 本文が JSON でない / `text` が文字列でない / `mark` が文字列でない / 聞き取りの本文が `audio/` の形式でない / 音が空 |
| `voice_unknown_mark` | 400 | `mark` が、 そのエージェントの `marks` に無い |
| `voice_nothing_to_say` | 400 | `text` に読む文字 (= 文字か数字) が無い |
| `voice_text_too_long` | 413 | 文が上限より長い。 上限の文字数が `detail.params.limit` に入っている |
| `voice_engine_unreachable` | 502 | engine に繋がらない。 engine が起動しているか、 `engine` の URL と port が合っているかを見る |
| `voice_engine_failed` | 502 | engine が断った。 `detail.params.step` がどの段か (= `audio_query` か `synthesis`)、 `detail.params.status` が engine の返した状態。 `speaker` の番号が engine に在るかを見る |
| `voice_listen_not_enabled` | 409 | そのタブのエージェントの `voice` に `listen` が無い |
| `voice_audio_too_large` | 413 | 録った音が上限より大きい。 上限のバイト数が `detail.params.limit` に入っている |
| `voice_listen_unreachable` | 502 | 聞き取りの engine に繋がらない。 engine が起動しているか、 `listen.engine` の URL と port が合っているかを見る |
| `voice_listen_failed` | 502 | 聞き取りの engine が断った / 文を返さなかった。 `detail.params.status` が engine の返した状態 (= 形式の変換に失敗すると 500。 `--convert` と ffmpeg を見る) |
