# エージェントと声で会話する

エージェントの返事を、 音声合成の engine で音にして、 画面で鳴らします。 声を聞き取る engine も足すと、 話すだけで
文が送られ、 返事が声で返る会話になります。 入力欄の 🔊 で返事を声で聞くかを、 🎙 で自分のマイクを使うかを選びます。

音声合成の engine は同梱していません。 [VOICEVOX](https://voicevox.hiroshiba.jp/) と同じ HTTP の口
(= `POST /audio_query` と `POST /synthesis`) を持つ engine を、 自分で起動しておきます
(= VOICEVOX / AivisSpeech など)。

聞き取りの engine は、 [whisper.cpp](https://github.com/ggml-org/whisper.cpp) の `whisper-server` と同じ HTTP の口
(= `POST /inference`) を持つ engine を、 自分で起動しておきます。 macOS 26 以降なら、 macOS に入っている聞き取りを
同じ口で出す engine (= [`engines/apple-speech/`](#macos-の聞き取りを使う)) も使えます。

既定では何もしません。 声を持たせたいエージェントにだけ、 設定を足します。

## 会話する

声を持つエージェントのタブには、 入力欄の右に声のボタンが出ます。

- **🔇 / 🔊 (= 声)**: 押すと 🔊 になり、 返事が声で返ります。 もう 1 度押すと 🔇 に戻り、 マイクも閉じ、 鳴っている
  音もその場で止まり、 以後は鳴らしません (= 普段の文字のチャット)
- **🎙 (= マイク)**: 声がオンで、 聞き取りの engine (= 設定の `listen`) が在るエージェントの時だけ、 🔊 の左に出ます。
  押すたびにマイクを開くと閉じるが入れ替わります。 開いている間は話すだけで送られ、 閉じている間は打って送り、
  返事だけを声で聞きます
- 🔊 にしただけでは、 マイクは開きません (= 声だけを聞く)。 マイクを取るのは 🎙 を押した時だけです。 🎙 を開いた
  まま 🔊 を切ったタブは、 次に 🔊 にした時もマイクを開きます (= 画面を読み込み直すまで)
- **🔊 を長押し**すると、 声の大きさのつまみが出ます (= 0〜200%)。 つまみの外を押すか ✕ で閉じます。 この端末だけの値で、 端末ごとに覚えます
  (= 動画の音など、 端末の他の音と揃える用)。 全端末に共通の基準の大きさは、 設定の声の値 (= `query` や
  `compressor`) が決め、 つまみはその上に掛かります

マイクを開いている間は、 次のように進みます。

1. マイクを開いたまま、 人が話しているかを見続けます
2. 声が 0.7 秒途切れたら、 言い終えたかを判定します (= 語と語の間の短い息継ぎでは判定しません)。 まだ考えている
   途中なら続きを待ち、 声が途切れてから 3 秒黙っていたら送ります
3. 話した部分の音を聞き取りの engine が文字にします。 言い終えていれば、 その文がタブへ送られます。 文が「、」
   や「えーと」「なんか」 のような言いさしで終わる時は、 言い終えたと判定されても送らずに続きを待ちます
   (= 続けて話せば 1 つの文になり、 そのまま 3 秒黙っていたら送ります)
4. エージェントが作業している途中 (= 考えている・ツールを使っている・返事を書いている) に話した文が届くと、
   先にその作業を止めてから送ります (= 端末で Esc を押した時と同じ止め方)。 話した文は必ず届き、 エージェントは
   「やっぱりやめよう」 のような言葉も会話として読めます。 打って送った文も、 🔊 の間は同じです。 停止ボタン
   (= 止めて、 待っている入力も捨てる) とは別の動きです
5. 話した文を送った時点で、 前の返事のまだ鳴っていない声は止まります。 タブの記録にその文が載る (= エージェント
   が新しい文を受け取る) までに届いた前の返事の続きも、 鳴らしません
6. 返事が声で返ります。 返事が鳴っている間も聞いていて、 話し始めるとその場で返事が止まり、 話した事が次の
   文になります (= スピーカーの返事は、 ブラウザのエコー除去がマイクの音から消します)

秒数と、 待たせる言いさしの語と、 割り込みの入切は、 設定の [`conversation`](#会話の間の取り方) で変えられます。

ボタンの色と動きが、 今どこにいるかを示します。

| ボタン | 状態 |
|---|---|
| 🔊 が青の枠 | 返事を声で鳴らす |
| 🔊 の青の枠が脈打つ | 返事を鳴らしている |
| 🎙 が緑の枠 | 聞いている |
| 🎙 の緑の枠が脈打つ | 人が話している |
| 🎙 の緑の枠が薄く点滅する | 聞く準備をしている / 言い終えたかを見ている / 話した文を文字にしている |
| 🎙 が薄く、 斜線が入る | マイクを閉じている |
| 🔊 が赤の枠 | 失敗した。 理由がボタンの上に出る |

- 鳴らすのは、 🔊 にした後に届いた返事だけです。 それまでの会話と、 タブを開いた時に読み込まれる履歴は
  鳴らしません
- 読むのは返事の文です (= ツールを使う合間に書いた文も読みます)。 thinking と、 ツールの呼び出し (= 何をしているか
  の説明の 1 行も) は読みません
- 返事が書き終わってから鳴り始めます。 1 文目の音が出来た時点で鳴らし、 続きは鳴らしている間に作ります
- 文と文は間を置かずに続けて鳴らします。 文の間の長さは、 engine の `postPhonemeLength` (= 文の後ろに付ける無音、
  `query` か `marks` に書く) で決まります。 `prePhonemeLength` と `postPhonemeLength` は書いた秒数のまま空きます (= engine は無音も
  `speedScale` で縮めるので、 backend が速さを掛けて渡す。 速さを上げても文の間は詰まらない)
- 🔊 の間に送った文には、 エージェントへ向けた印が付きます (= [声で聞いている印](#声で聞いている印))。
  話して送った文にも、 打って送った文にも (= マイクを閉じている間も) 付きます
- 声でない音 (= 物音や咳) は、 文字にすると空になるので、 何も送りません
- 入力欄に打っている途中の文には触れません
- 🔊 にできるのは、 同時に 1 つのタブだけです。 別のタブを見ている間も、 🔊 のタブの会話は続きます (= そのタブの
  返事を鳴らし、 話した文はそのタブへ送る)。 別のタブで 🔊 にすると、 前のタブの声とマイクはオフになります
- 画面を読み込み直すと、 声もマイクもオフに戻ります (= ブラウザは、 人が画面を押した後でないと音とマイクを
  扱わせません)
- マイクを開けるのは、 1 つのタブにつき 1 つの画面です。 別の端末や別のウィンドウで同じタブのマイクを
  開くと、 先に開いていた画面は、 次に話した時に声もマイクもオフになり、 理由がボタンの上に出ます
- 初めてマイクを開いた時に、 ブラウザがマイクの許可を訊きます。 許されなかった時は、 マイクは閉じたままで、
  返事の声は鳴ります。 マイクは、 `https://` か `localhost` で開いた画面
  でしか使えません (= ブラウザの決まり)
- 人の声かの判定と、 言い終えたかの判定は、 ブラウザの中で行います。 判定に使う部品 (= 言い終えを判定する
  model を含めて約 26 MB) は、 画面を読み込んでから初めてマイクを開いた時に読み込まれます

## iPhone の app で話す

iPhone では、 ブラウザで開いた画面は、 ホーム画面へ出たり別の app へ移ったりすると、 マイクも声も止まります
(= iOS は、 裏に回った Web の画面の音を止める)。 iPhone の app (= [作り方](../setup/ios-app.md)) で開くと、
🔊 にしたタブの会話は、 ホーム画面へ出ても、 画面を消しても続きます。

- ボタンと使い方は、 ブラウザと同じです (= 🔊 で声、 🎙 でマイク)
- app の中では、 マイクと声を app が持ち、 backend と WebRTC でつなぎます。 人が話しているかと言い終えたかの判定、
  聞き取り、 タブへの送信、 返事の声は、 全部 backend の中で行います。 間の取り方と言い方の印は、 ブラウザと同じ
  設定に従います
- app の中で別のタブを見ている間も、 app の外へ出ている間も、 🔊 のタブの会話は続きます
- 返事の声は、 誰が送った文への返事でも鳴ります (= 別の画面から打った文への返事も、 iPhone で聞ける)
- エコー除去は iPhone の通話用の音声処理が行います
- 会話を開けるのは、 ブラウザと合わせて 1 つのタブにつき 1 つです。 app で開くと、 先に開いていた画面は次に
  話した時に閉じます

backend には、 会話の部品を足して入れます (= 使う時だけ。 約 670 MB)。

```sh
pip install -r backend/requirements-voice-call.txt
```

入れた後に backend を再起動します。 部品が入っていない backend では、 app で 🔊 にすると
`voice_call_unavailable` が出ます。 iPhone と backend の間の音は、 外部のサービスを通さず、 直接つなぎます
(= iPhone から backend の機械へ届く網の中で使う。 Tailscale の中など)。

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
        "prompt": "Claude、PWA。",
        "turn": "/path/to/smart-turn-v3.2-cpu.onnx"
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
| `conversation` (任意) | 話して送る会話の間の取り方。 [下の表](#会話の間の取り方) |
| `compressor` (任意) | 文ごとの音に掛けるコンプレッサー。 [下の表](#音の強弱を均す) |
| `tuning` (任意) | 声の調整の file の path。 [調整の file](#調整の-file) |

`listen` の項目:

| 項目 | 中身 |
|---|---|
| `engine` | 聞き取りの engine の URL (= `http://` か `https://`) |
| `prompt` (任意) | 聞き取りの手がかりにする語 (= 固有名詞や略語を、 句点で区切って並べる)。 engine の `prompt` にそのまま渡る |
| `turn` (任意) | 言い終えたかを判定する model (= Smart Turn) の file の path。 省くと、 声が少し途切れた所で送る (= 言葉を探して黙った所でも送られる) |

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

### 会話の間の取り方

`conversation` に書いた項目だけが変わり、 書いていない項目は既定のままです。

| 項目 | 既定 | 中身 |
|---|---|---|
| `pause_ms` | `700` | 声が途切れてから、 言い終えたかの判定に入るまでの無音 (ミリ秒)。 短いほど早く送られ、 語と語の間でも判定する |
| `wait_ms` | `3000` | 言い終えていない時に、 送るまで待つ無音 (ミリ秒。 声が途切れた時から数える)。 `pause_ms` より長く |
| `resume_ms` | `400` | 言い終えたと判定した後、 送る前に待つ時間 (ミリ秒)。 この間に話し始めると、 続きとつなげて 1 つの発話にする (= 長く話している途中の間で「言い終えた」 と判定されても、 文が切れない)。 長いほど切れにくく、 送るのが遅れる。 `0` なら待たない |
| `unfinished_endings` | 読点・三点と、 「なんか」「えーと」「えっと」「えー」「あのー」「あの」「うーん」「まあ」「その」 | 聞き取った文がこれで終わる時は、 言い終えた判定でも `wait_ms` まで待つ (= 文末の句点は外して見る)。 書くと一覧ごと置き換わる |
| `interrupt` | `true` | 返事が鳴っている間も聞き、 話し始めたら返事を止める。 `false` なら、 鳴っている間は聞かない (= スピーカーの返事を拾ってしまう時に) |

値はマイクを開いた時に読みます。 変えた後は、 🎙 を開き直すと効きます。

### 音の強弱を均す

声のスタイルによっては、 文の中の山と谷の差が大きく、 スタイルを切り替えると音量が揃っていないように聞こえます。
`compressor` を書くと、 文ごとの音に [ffmpeg](https://ffmpeg.org/) のコンプレッサー (= `acompressor`) を掛けてから
画面へ返します。 書かなければ掛けません。 backend の機械に ffmpeg が要ります。

```json
"compressor": { "threshold_db": -18, "ratio": 3, "attack_ms": 10, "release_ms": 150, "makeup_db": 6, "limit_db": -1 }
```

| 項目 | 既定 | 中身 |
|---|---|---|
| `threshold_db` | `-18.06` | これより大きい所を縮める (dB) |
| `ratio` | `2` | 縮める比 (= 1〜20) |
| `attack_ms` / `release_ms` | `20` / `250` | 縮め始める速さ / 戻す速さ (ミリ秒) |
| `makeup_db` | `0` | 縮めた後に全体を持ち上げる量 (dB)。 縮めると全体が小さくなるので、 戻す時に書く |
| `limit_db` | 無し | 書くと、 最後に音の山がこの大きさを超えないように抑える (dB、 `alimiter`) |

- 書いていない項目は ffmpeg の既定です。 値の範囲は ffmpeg が受ける範囲で、 外れた値は形の違う設定として扱います
- 1 文に掛かるのは 0.1 秒ほどです (= 音の長さにほぼよらない)
- ffmpeg が無い / 失敗した時は、 掛けずに engine の音のまま返し、 backend の log に理由を 1 行出します

### 調整の file

`tuning` に path を書くと、 その file (= JSON) の値を設定の値の上に重ねます。 声と間の取り方を、 backend の設定に
触れずに変える置き場です (= エージェントに自分の声を調整させる時は、 この file をエージェントの folder に置く)。

```json
{
  "speaker": 3,
  "marks": {
    "calm":  { "speedScale": 1.1 },
    "happy": { "speedScale": 1.15, "intonationScale": 1.3 }
  },
  "default": "calm",
  "conversation": { "pause_ms": 800 }
}
```

- 書ける項目は `speaker` / `query` / `marks` / `default` / `conversation` / `compressor` です。 engine の URL と `listen` は、
  backend の設定にだけ書きます
- 書いた項目は、 設定の同じ項目をまるごと置き換えます (= `marks` を書くと、 設定の `marks` は使わない)
- backend は file を毎回読みます。 書き換えると、 声は次の文から、 間の取り方は次にマイクを開いた時から効きます。
  backend の再起動は要りません
- file が無い / JSON として読めない / 書けない項目がある / 値の形が違う時は、 設定の値のまま動き、 理由を
  [`GET /sessions/<タブの id>/voice`](#声を持つタブか訊く) の `tuning_error` に返します (= backend の log にも 1 行出る)

### 聞き取りの engine を起動する

`whisper-server` を、 日本語と、 形式の変換と、 声の区間の検出を有効にして起動する例です。

```sh
whisper-server --host 127.0.0.1 --port 10102 \
  --model /path/to/ggml-large-v3-turbo-q5_0.bin --language ja \
  --convert --no-timestamps \
  --vad --vad-model /path/to/ggml-silero-v5.1.2.bin \
  --vad-threshold 0.3 --vad-speech-pad-ms 300 --vad-min-speech-duration-ms 100
```

- `--convert` は、 ブラウザが録る形式 (= Chromium は webm/opus、 Safari は mp4/AAC) を engine の側で変換します。
  [ffmpeg](https://ffmpeg.org/) が要ります。 変換の途中の file は、 engine を起動した folder に置かれます
- `--vad` を付けないと、 無音や小さな雑音だけの録音に、 話していない文が返ることがあります
- 画面は、 声の前に 0.5 秒の無音を付けて送ります。 `--vad` の既定の値のままだと、 柔らかい出だし (= 「おはよう」
  の「お」) や短い語 (= 「はい」「うん」) を声と見ずに削ることがあります。 上の 3 つの値は、 声と見なす境目を画面の
  声の検出と同じ 0.3 にし、 声の前後を 0.3 秒残し、 0.1 秒の短い語も残します
- model は whisper.cpp の配布物から選びます (= 日本語は多言語の model を使う。 `.en` の付く model は英語だけ)

### macOS の聞き取りを使う

`engines/apple-speech/` は、 macOS に入っている聞き取り (= Speech framework の SpeechTranscriber) を、 `whisper-server`
と同じ口で出す engine です。 聞き取りは Mac の中で行い、 音は外へ出ません。 macOS 26 以降と、 Swift の compiler
(= Xcode か Command Line Tools) が要ります。

```sh
bash engines/apple-speech/build.sh
engines/apple-speech/.build/apple-speech --host 127.0.0.1 --port 10104 --locale ja-JP
```

`listen.engine` を `http://127.0.0.1:10104` にすると、 この engine で聞き取ります。

- `prompt` の語 (= 句読点で区切った固有名詞など) は、 聞き取りの手がかりの語として渡ります
- 受ける音は、 macOS が読める形式です (= WAV / AIFF / CAF / m4a など)。 画面は WAV で送ります
- 起動した時に、 その言語の model が Mac に無ければ入れ、 1 度空の音で温めます。 端末で聞き取れない言語なら、
  起動せずに理由を出して終わります
- 聞き取った文は log に書きません (= 書くのは、 要求ごとの状態・音の長さ・掛かった時間)
- `whisper-server` の `--vad` に当たる設定はありません。 雑音と無音は、 空の文で返ります

### 言い終えを判定する model を置く

[Smart Turn](https://huggingface.co/pipecat-ai/smart-turn-v3) (= BSD-2-Clause) の CPU 版の model を取って、
`listen.turn` にその path を書きます。

```sh
mkdir -p ~/.local/share/smart-turn
curl -L -o ~/.local/share/smart-turn/smart-turn-v3.2-cpu.onnx \
  https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx
```

画面は、 マイクを開いた時に、 backend からこの file を受け取ってブラウザの中で動かします。 file を差し替えた
時は、 画面を読み込み直すと新しい方を使います。

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

### 声にしない行 (= `[mute]`)

`[mute]` は予約の印で、 その行を声にしません。 吹き出しには出るので、 目で見せたい文 (= 長い引用や一覧の説明) を、
表やコードブロックにしないまま声から外せます。

```
これで全部通ったよ！
[mute] 通ったテスト: 声の印 12 件、 会話 9 件、 画面 4 件。
詳しくは上に書いておいたね。
```

- 効く範囲は他の印と同じく、 その行の終わりまでです。 行の中で別の印が出れば、 そこから声に戻ります
- `marks` には書きません (= 書いても、 予約の印として扱います)
- 吹き出しには、 印は出ません

### 印に値を添える

印の名前の後に `名前=数` を空白で区切って並べると、 その文だけ、 印の値の上にその値を重ねて言います。
感情の強さや速さを、 文ごとに選べます。

```
[happy i=1.4] やった！ 全部通ったよ！
[soft i=0.6 s=0.9] 今日はここまでにしようか。
```

| 短い名前 | engine の名前 | 範囲 | 中身 |
|---|---|---|---|
| `i` | `intonationScale` | 0〜2.0 | 感情の強さ (= スタイルの言い方にどれだけ寄せるか) |
| `s` | `speedScale` | 0.5〜2.0 | 速さ |
| `t` | `tempoDynamicsScale` | 0〜2.0 | 緩急 |
| `p` | `pitchScale` | -0.15〜0.15 | 高さ |
| `v` | `volumeScale` | 0〜2.0 | 大きさ |

- 短い名前でも、 engine の名前 (= `[happy intonationScale=1.4]`) でも書けます。 範囲は AivisSpeech Engine
  1.2.0 が示す範囲です
- 添えた値は、 印と同じく、 その行の終わりまで効きます。 行の中で別の印が出れば、 そこからはその印の値です
- 範囲の外の値と、 表に無い名前の値は、 その文では使わず、 印の値で言います (= 声は止めません)。 使わなかった
  値は backend の log に出ます
- 画面の吹き出しには、 値ごと印は出ません

印を使うかどうかは、 エージェントへの指示 (= そのエージェントの `CLAUDE.md` など) で決めます。 backend は、
書かれた印を読むだけです。

## 声で聞いている印

会話がオンのタブで送った文には、 頭に `[voice]` が付いてエージェントに届きます。 エージェントからは、 画面の
会話がオンかが見えません。 この印を見れば、 返事が声で聞かれると分かり、 声に向いた書き方 (= 短く、 表や
path を文に混ぜない) へ切り替えられます。

```
[voice] 明日の予定を教えて
```

- 印が付くのは、 送った画面で会話がオンの時だけです (= 話して送った文にも、 打って送った文にも付きます)
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
`synthesis` に渡して音を受け取ります。 1 文目の音が返った時点で鳴らし始められます。

人の声は、 会話を開いてから聞きます。 `conversation` で会話を開き (= この画面が持ち主になる)、 `turn-model` で
言い終えを判定する model を受け取ります。 言い終えた声を `transcription` に渡して文を受け取り、 普段の送信と
同じ口で送ります。 閉じる時は `conversation` を消します。

`<タブの id>` は、 そのエージェントのタブの id です。 port は backend を起動した port に合わせてください。

### 声を持つタブか訊く

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice
```

```json
{
  "enabled": true, "marks": ["calm", "happy"], "default": "calm", "listen": true, "turn": true,
  "conversation": { "pause_ms": 700, "wait_ms": 3000, "resume_ms": 400, "unfinished_endings": ["、", "えーと"], "interrupt": true },
  "tuning_error": ""
}
```

- `listen` は、 そのエージェントが人の声を聞き取るか (= 設定に `listen` が在るか) です
- `turn` は、 言い終えを判定する model が設定に在るか (= `listen.turn` が在るか) です
- `conversation` は、 調整の file を重ねた後の会話の間の取り方です (= 書いていない項目は既定)
- `tuning_error` は、 調整の file を使えない理由です (= 使えている / `tuning` を書いていなければ空)
- 声を持たないエージェントのタブは
  `{"enabled": false, "marks": [], "default": "", "listen": false, "turn": false, "conversation": null, "tuning_error": ""}`
  を返します

### 返事の文を、 声にする文の並びにする

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/utterances \
  -H 'Content-Type: application/json' \
  -d '{"text": "[happy i=1.4] できたよ！\n場所は `~/notes/a.md` だよ。"}'
```

```json
{ "utterances": [
  { "mark": "happy", "text": "できたよ！", "values": { "intonationScale": 1.4 } },
  { "mark": "calm",  "text": "場所は だよ。", "values": {} }
] }
```

`values` は印に添えた値です (= engine の名前 → 数。 添えていなければ空)。

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
| `values` (任意) | 印に添えた値 (= `utterances` が返した `values`)。 印の値の上に重ねます |

engine が返した音 (= WAV 形式) を、 そのまま返します。 backend は音を保存しません。

### 会話を開く・閉じる

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/conversation \
  -H 'Content-Type: application/json' -d '{"client": "screen-a"}'
```

```json
{ "client": "screen-a" }
```

- `client` は、 画面が名乗る名前です (= 英数字と `-` `_` の 64 文字まで。 画面は読み込むたびに作る)
- 開いた画面が、 そのタブの会話の持ち主になります。 前に開いていた画面からの `transcription` は断られます
  (= `voice_conversation_elsewhere`)
- 閉じる時は、 同じ本文で `DELETE` を送ります。 持ち主の画面からなら `{"closed": true}`、 別の画面が持って
  いれば何もせず `{"closed": false}` を返します
- 持ち主は backend の中だけに持ちます (= 再起動すると忘れ、 次に音を送った画面が持ち主になる)

### 電話の会話をつなぐ

iPhone の app が使う口です。 本文の形は [Pipecat](https://github.com/pipecat-ai/pipecat) の SmallWebRTC の口と
同じで、 app は Pipecat の iOS の部品で申し込みます。

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/call \
  -H 'Content-Type: application/json' -d '{"sdp": "<SDP の offer>", "type": "offer"}'
```

```json
{ "sdp": "<SDP の answer>", "type": "answer", "pc_id": "SmallWebRTCConnection#…" }
```

- つながると、 その電話がタブの会話の持ち主になります (= [会話を開く・閉じる](#会話を開く閉じる) と同じ決まり)
- 経路の候補は、 同じ URL へ `PATCH` で `{"pc_id": "…", "candidates": [{"candidate": "…", "sdp_mid": "0",
  "sdp_mline_index": 0}]}` を送ります
- 声を持たないタブ・聞き取りを持たないタブは、 つなぐ前に断ります
- 会話は、 通話ごとに backend が起こす別の process で動きます (= 音の送り出しを、 backend の他の仕事で遅らせない)。
  会話の process の log は `logs/voice-call.log` です (= backend の log と同じく 5 MB で回し、 3 世代まで残す)。
  通話の終わりに、 送り出しに短い無音が挟まった回数が出ます (= `voice call: ended output … gaps=…`)

### 通話の声の大きさを変える

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/call/volume \
  -H 'Content-Type: application/json' -d '{"volume": 0.8}'
```

```json
{ "calls": 1 }
```

- `volume` は 0〜2 の倍率です (= 1 で engine の音のまま)。 そのタブの通話の声に、 話している途中でもその場で掛かります
- 通話をつなぐ時は、 `POST …/voice/call?volume=0.8` で最初の倍率を渡します (= 省けば 1)
- `calls` は伝えた通話の数です (= 通話が無ければ 0)

### 言い終えを判定する model を受け取る

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/turn-model -o smart-turn.onnx
```

`listen.turn` の file を、 そのまま返します。 設定に `turn` が無い時と、 file が無い時は 404 です。

### 録った音を文にする

```sh
curl -s http://127.0.0.1:8765/sessions/<タブの id>/voice/transcription \
  -H 'Content-Type: audio/wav' -H 'X-Voice-Conversation: screen-a' --data-binary @speech.wav
```

```json
{ "text": "明日の予定を教えて" }
```

- 本文は録った音そのものです。 `Content-Type` は `audio/` で始まる形式にします
- `X-Voice-Conversation` (任意) は、 会話を開いた時の `client` です。 付けると、 持ち主でない画面の音を断ります
  (= 誰も開いていなければ、 その画面が持ち主になる)
- engine が区切りごとに挟む改行は、 空白 1 つにまとめて 1 行で返します
- 声が聞き取れなかった時は `{"text": ""}` を返します

## 起きない時

| 見えること | 原因 |
|---|---|
| 声のボタンが出ない | そのタブのエージェントに `voice` が無い / 形が違う (= backend の log に 1 行出ている) / 設定の後に backend を再起動していない |
| 🔊 にしても 🎙 が出ない | そのエージェントの `voice` に `listen` が無い / 形が違う (= `listen` の形が違うと、 声そのものが無い扱いになる) |
| 🔊 にしても鳴らない | 鳴るのは 🔊 にした後に届いた返事だけ。 端末の音量と消音も見る |
| 🔊 にしても話を聞かない | 🔊 だけではマイクを開かない。 🎙 を押す |
| 🎙 を開くと「マイクを使えません」 と出る | ブラウザがマイクを許していない / 画面を `https://` でも `localhost` でもない URL で開いている |
| 話しても何も送られない | 声が聞き取れなかった (= 会話の間は、 空の文は黙って捨てる)。 engine を `--vad` 無しで起動していると、 逆に話していない文が送られることがある |
| 話している途中で送られる | `listen.turn` が無い (= 声が `pause_ms` 途切れた所で送る)。 在る時は `conversation.resume_ms` か `pause_ms` を延ばすか、 途中で言いがちな語を `unfinished_endings` に足す |
| 返事が自分で止まる / 返事の文が送られる | スピーカーの返事をマイクが拾っている。 イヤホンを使うか、 `conversation.interrupt` を `false` にする |
| 声や間の取り方を変えても効かない | 調整の file を使えていない (= `GET /sessions/<タブの id>/voice` の `tuning_error` に理由が出る)。 間の取り方は 🎙 を開き直すと効く |
| 「別の画面で会話が開かれたので、 ここは閉じました」 と出る | 同じタブのマイクを、 別の端末か別のウィンドウで開いた |
| iPhone の app で、 裏に回ると声が止まる | app ではなくブラウザ (= Safari やホーム画面に置いた Web の画面) で開いている |
| iPhone の app で 🔊 にしても、 つながらない | backend に会話の部品が入っていない (= `voice_call_unavailable`) / iPhone から backend の機械へ直接届かない網にいる |
| ボタンの上に理由が出る | 下の表の code に当たる文が出ている |

口の失敗は、 HTTP の状態と `detail.code` で返ります。

| 返る code | 状態 | 原因 |
|---|---|---|
| `voice_unknown_session` | 404 | その id のタブが無い |
| `voice_not_enabled` | 409 | そのタブのエージェントに `voice` が無い / 形が違う / 設定の後に backend を再起動していない |
| `voice_bad_request` | 400 | 本文が JSON でない / `text` が文字列でない / `mark` が文字列でない / 聞き取りの本文が `audio/` の形式でない / 音が空 / 会話の `client` が無い・形が違う |
| `voice_unknown_mark` | 400 | `mark` が、 そのエージェントの `marks` に無い |
| `voice_nothing_to_say` | 400 | `text` に読む文字 (= 文字か数字) が無い |
| `voice_text_too_long` | 413 | 文が上限より長い。 上限の文字数が `detail.params.limit` に入っている |
| `voice_engine_unreachable` | 502 | engine に繋がらない。 engine が起動しているか、 `engine` の URL と port が合っているかを見る |
| `voice_engine_failed` | 502 | engine が断った。 `detail.params.step` がどの段か (= `audio_query` か `synthesis`)、 `detail.params.status` が engine の返した状態。 `speaker` の番号が engine に在るかを見る |
| `voice_listen_not_enabled` | 409 | そのタブのエージェントの `voice` に `listen` が無い |
| `voice_audio_too_large` | 413 | 録った音が上限より大きい。 上限のバイト数が `detail.params.limit` に入っている |
| `voice_listen_unreachable` | 502 | 聞き取りの engine に繋がらない。 engine が起動しているか、 `listen.engine` の URL と port が合っているかを見る |
| `voice_listen_failed` | 502 | 聞き取りの engine が断った / 文を返さなかった。 `detail.params.status` が engine の返した状態 (= 形式の変換に失敗すると 500。 `--convert` と ffmpeg を見る) |
| `voice_turn_model_missing` | 404 | 言い終えを判定する model が無い。 `listen.turn` の path に file が在るかを見る (= 在る場所を書いていて file が無い時は、 backend の log に 1 行出る) |
| `voice_conversation_elsewhere` | 409 | そのタブの会話は、 別の画面が開いている |
| `voice_call_unavailable` | 501 | backend に会話の部品が入っていない (= `pip install -r backend/requirements-voice-call.txt` の後に再起動) |
| `voice_call_unknown` | 404 | 経路の候補を、 まだつないでいない接続へ送った |
| `voice_call_failed` | 502 | 会話をつなげなかった。 理由が `detail.params.reason` に入っている (= backend の log にも 1 行出る) |
