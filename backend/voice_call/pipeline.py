"""電話の会話 1 本の組み立て (= Pipecat の標準の並び。 LLM の段にタブの agent が居る)。

    受け口 (= WebRTC) → マイクの関所 (= app がマイクを切っている間の音を捨てる) → 聞き取り → 発話のまとめ役 (= Silero で声の区間、 Smart Turn で言い終え) → agent → 声 → 送り口

間の取り方は、 画面の会話と同じ設定 (= `voice.conversation`) から決める:
    pause_ms            声が途切れたと見る無音 (= Silero の stop_secs)
    wait_ms             言い終えていないと判定された時に、 送るまで待つ無音 (= Smart Turn の stop_secs)
    unfinished_endings  言いさしの語尾 (= agent の段が続きを待つ)
    interrupt           返事の途中で話したら止めるか (= 止めない時は、 返事の間は聞かない)

送り出しの途切れ: Pipecat は返事の音を 10 ms ずつ WebRTC へ渡し、 渡した分が送られてから次を渡す。 次が 10 ms
以内に間に合わないと、 その 10 ms は無音で埋まる (= 聞こえる「ぷつっ」)。 会話を専用の process で動かすのは、
backend 本体の他の仕事でこの受け渡しを遅らせないため。 話している途中に挟まった短い無音の回数を log に出す。

声の大きさ: 端末のつまみの倍率は、 送り口へ渡す時に掛ける。 送り出しは前に渡した音が送られるまで次を渡さないので、
先に溜まるのは 1 回分 (= 40 ms) だけで、 話している途中に動かしても、 その場で大きさが変わる。

無音の間は送らない (= WebRTC の DTX と同じ働き): 通話は誰も話していない間も 20 ms ごとに音を送り合い、 その間も
電話の電波と符号化、 こちらの復号が動き続ける。
    下り  送り口に渡る音が全部 0 の無音のまま DTX_HANGOVER_SECS 続いたら、 そこから先の無音は符号化せず送らない。
          送らなかった長さだけ後の音の時刻を進める (= 電話の側は、 時刻の空いた所を無音として鳴らす)
    上り  電話に DTX を頼む (= worker が答えの SDP の Opus に usedtx=1 を足す)。 電話が無音の間に送らないと、 声の
          区間の判定 (= Silero) は届いた音の長さで時間を数えるので、 話し終えても終わりが決まらない。 受け口の音が
          GAP_FILL_SECS 届かなければ、 その長さの無音を代わりに渡す (= 判定には今までと同じ時間の流れが届く)
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import time
from collections.abc import Callable

from aiortc.codecs.opus import SAMPLE_RATE as OPUS_SAMPLE_RATE
from aiortc.codecs.opus import SAMPLES_PER_FRAME as OPUS_SAMPLES_PER_FRAME
from aiortc.codecs.opus import OpusEncoder
from av import AudioFrame

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection, SmallWebRTCTrack
from pipecat.transports.smallwebrtc.transport import RawAudioTrack, SmallWebRTCTransport
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from backend.voice_call.agent import AgentBridge
from backend.voice_call.client import BackendClient
from backend.voice_call.services import ListenSTT, MicGate, VoiceTTS, Volume, scaled

logger = logging.getLogger(__name__)

# 「話している途中の途切れ」 と数える無音の長さ (= 10 ms の枠の数。 文と文の間は合成を待つので、 これより長い)
GAP_FRAMES_MAX = 5
# 途切れの数を log に出す間隔
REPORT_SECS = 10
# 下り: 無音がこれだけ続いたら送るのをやめる (= libopus の DTX が無音の扱いに入るまでと同じ 200 ms)
DTX_HANGOVER_SECS = 0.2
# 上り: 受け口の音がこれだけ届かなければ、 その長さの無音を渡す (= 声の区間の判定が時間を数える刻み)
GAP_FILL_SECS = 0.1


class OutputGaps:
    """送り出しに挟まった短い無音 (= 次の 10 ms が間に合わなかった) と、 送り出しの遅れの最大を数える。"""

    def __init__(self):
        self.frames = 0
        self.gaps = 0
        self.late_max_ms = 0.0
        self._silent = 0
        self._speaking = False

    def saw(self, empty: bool, late_ms: float) -> None:
        self.frames += 1
        self.late_max_ms = max(self.late_max_ms, late_ms)
        if empty:
            self._silent += 1
            return
        if self._speaking and 0 < self._silent <= GAP_FRAMES_MAX:
            self.gaps += 1
        self._silent = 0
        self._speaking = True

    def line(self) -> str:
        return f"frames={self.frames} gaps={self.gaps} late_max_ms={self.late_max_ms:.0f}"


def watch_output(gaps: OutputGaps) -> None:
    """この process の送り出しの枠を数える (= 会話 1 本につき 1 process なので、 型ごと包んでよい)。"""
    original = RawAudioTrack.recv

    async def recv(self):
        # 送り出しと同じく、 この枠の時刻まで待ってから手元を見る (= 待つ前に見ると、 待つ間に届いた音まで
        # 途切れと数える)。 待った後に元の recv を呼ぶので、 元の recv はもう待たない。
        late_ms = 0.0
        if self._timestamp > 0:
            due = self._start + self._timestamp / self._sample_rate
            if due > time.time():
                await asyncio.sleep(due - time.time())
            late_ms = max(0.0, (time.time() - due) * 1000)
        empty = not self._chunk_queue
        frame = await original(self)
        gaps.saw(empty, late_ms)
        return frame

    RawAudioTrack.recv = recv


def scale_output(volume: Volume) -> None:
    """この process の送り口へ渡す音に、 その時の倍率を掛ける (= 会話 1 本につき 1 process なので、 型ごと包んでよい)。"""
    original = RawAudioTrack.add_audio_bytes

    def add_audio_bytes(self, audio_bytes: bytes):
        return original(self, scaled(audio_bytes, volume.value))

    RawAudioTrack.add_audio_bytes = add_audio_bytes


def skip_silent_output() -> None:
    """この process の Opus の符号化で、 続いた無音を送らない (= 会話 1 本につき 1 process なので、 型ごと包んでよい)。

    aiortc の送り手は、 符号化が何も返さない枠を送らずに飛ばす。 符号化へは、 飛ばした間を詰めた続きの時刻で渡し
    (= 組み直しの部品は時刻の飛びを自分で埋めにいく)、 出てきた音の時刻に飛ばした長さを足す。 飛ばし始めるのは、
    符号化が 20 ms へ組み直す途中に何も残していない枠から (= 残っていると、 その分が鳴り出した音の前に付く)。
    """
    original = OpusEncoder.encode
    zeros: dict[int, bytes] = {}

    def encode(self, frame, force_keyframe=False):
        data = bytes(frame.planes[0])[:frame.samples * len(frame.layout.channels) * frame.format.bytes]
        silent = data == zeros.setdefault(len(data), bytes(len(data)))
        self._quiet_secs = getattr(self, "_quiet_secs", 0.0) + frame.samples / frame.sample_rate if silent else 0.0
        fed, skipped = getattr(self, "_fed", 0), getattr(self, "_skipped", 0)   # 48 kHz の数
        samples = frame.samples * OPUS_SAMPLE_RATE // frame.sample_rate
        if self._quiet_secs > DTX_HANGOVER_SECS and fed % OPUS_SAMPLES_PER_FRAME == 0:
            self._skipped = skipped + samples
            return [], None
        frame.pts = fed * frame.sample_rate // OPUS_SAMPLE_RATE
        frame.time_base = fractions.Fraction(1, frame.sample_rate)
        self._fed = fed + samples
        payloads, timestamp = original(self, frame, force_keyframe)
        return payloads, None if timestamp is None else timestamp + skipped

    OpusEncoder.encode = encode


def fill_input_gaps() -> None:
    """この process の受け口で、 音が届かない間を無音で埋める (= 会話 1 本につき 1 process なので、 型ごと包んでよい)。

    待つたびに元の受け取りを呼び直す (= 元の受け取りは、 2 秒呼ばれないと受け取りを止めて溜まった音を捨てる。 呼んだ
    まま待ち続けると、 無音が 2 秒続いた所で次の声を取りこぼす)。 取り消した待ちは音を失わない (= aiortc の列の get)。
    """
    original = SmallWebRTCTrack.recv

    async def recv(self):
        if self._track.kind != "audio":
            return await original(self)
        try:
            frame = await asyncio.wait_for(original(self), timeout=GAP_FILL_SECS)
        except TimeoutError:
            return _silence(getattr(self, "_last_heard", None), GAP_FILL_SECS)
        if isinstance(frame, AudioFrame):
            self._last_heard = frame
        return frame

    SmallWebRTCTrack.recv = recv


def _silence(like: AudioFrame | None, secs: float) -> AudioFrame:
    """secs 秒の無音 (= 形は前に届いた音に揃える。 まだ何も届いていなければ、 aiortc の Opus の復号と同じ形)。"""
    rate = like.sample_rate if like is not None else OPUS_SAMPLE_RATE
    frame = AudioFrame(format=like.format.name if like is not None else "s16",
                       layout=like.layout.name if like is not None else "stereo", samples=round(rate * secs))
    for plane in frame.planes:
        plane.update(bytes(plane.buffer_size))
    frame.sample_rate = rate
    frame.time_base = fractions.Fraction(1, rate)
    return frame


async def run_call(connection: SmallWebRTCConnection, backend: BackendClient, start: dict, volume: Volume,
                   handover: Callable[[dict], None] | None = None,
                   superseded: asyncio.Event | None = None) -> None:
    """1 本の電話の会話を、 つながっている間走らせる。

    start: backend が渡す、 そのタブの声の設定 (= marks の名前の並び / conversation / turn の model の path)。
           つなぎ直した通話なら resume (= 前の通話の鳴り残し)
    volume: その端末の声の大きさの倍率 (= 通話中に backend から変わる)
    handover: 通話が閉じる時に、 鳴り終えていない文を backend へ渡す (= 次のつなぎ直しが言い直す)
    superseded: 同じタブに新しい通話が来た知らせ (= 立ったら、 鳴り残しを渡して閉じる)
    """
    conversation = start["conversation"]
    gaps = OutputGaps()
    watch_output(gaps)
    scale_output(volume)
    skip_silent_output()
    fill_input_gaps()
    transport = SmallWebRTCTransport(
        webrtc_connection=connection, params=TransportParams(audio_in_enabled=True, audio_out_enabled=True))
    turn = LocalSmartTurnAnalyzerV3(
        smart_turn_model_path=start.get("turn") or None,
        params=SmartTurnParams(stop_secs=conversation["wait_ms"] / 1000))
    user_aggregator, _ = LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=conversation["pause_ms"] / 1000)),
            user_turn_strategies=UserTurnStrategies(stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn)]),
            user_mute_strategies=[] if conversation["interrupt"] else [AlwaysUserMuteStrategy()],
        ),
    )
    runner = WorkerRunner(handle_sigint=False)

    async def lost() -> None:
        logger.info("voice call: another screen opened the conversation; ending the call")
        await runner.cancel()

    bridge = AgentBridge(conversation, send=backend.send, events=backend.events, utterances=backend.utterances,
                         speech=start.get("speech", True), interrupt=backend.interrupt, reading=backend.reading,
                         resume=start.get("resume"), on_handover=handover)
    def microphone_on() -> bool:
        track = connection.audio_input_track()
        return track is None or track.is_enabled()

    pipeline = Pipeline([
        transport.input(),
        MicGate(microphone_on),
        ListenSTT(backend, on_lost=lost, on_words=bridge.heard_words, wants_words=bridge.wants_words),
        user_aggregator,
        bridge,
        VoiceTTS(backend, start["marks"]),
        transport.output(),
    ])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client_):
        logger.info("voice call: the phone hung up")
        await runner.cancel()

    async def report() -> None:
        reported = None
        while True:
            await asyncio.sleep(REPORT_SECS)
            if gaps.line() != reported:
                reported = gaps.line()
                logger.info("voice call: output %s", reported)

    # 会話を取るのは、 電話が実際につながってから (= つながらないまま捨てられた申し込みが、 立ち上がっただけで
    # 会話を取ると、 本物の通話の聞き取りが断られて閉じる。 2026-10-19 に 2 回)
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client_):
        try:
            await backend.claim()
        except Exception as error:  # noqa: BLE001 (= 会話を取れない通話は続けない)
            logger.warning("voice call: could not take the conversation: %s", error)
            await runner.cancel()
            return
        logger.info("voice call: started client=%s", backend.client)

    # 同じタブに新しい通話が来た: 鳴り残しを渡して閉じる (= 1 つのタブに 1 本)
    async def end_when_superseded() -> None:
        await superseded.wait()
        logger.info("voice call: a newer call of this tab came in; ending the call")
        await runner.cancel()

    logger.info("voice call: waiting for the phone client=%s", backend.client)
    reporter = asyncio.create_task(report())
    ender = asyncio.create_task(end_when_superseded()) if superseded is not None else None
    try:
        # 動きの無い間の時間切れは使わない (= 既定は 300 秒。 マイクを切って聞いているだけの間は人が話さないので、
        # 返事が来ないまま 5 分たつと通話ごと閉じ、 app に戻るとスピーカーもマイクも切れていた。 2026-10-19 までに
        # 15 回)。 通話の終わりは、 電話が切れた知らせ (= on_client_disconnected) で見る
        await runner.add_workers(PipelineWorker(pipeline, params=PipelineParams(), idle_timeout_secs=None))
        await runner.run()
    finally:
        reporter.cancel()
        if ender is not None:
            ender.cancel()
        logger.info("voice call: ended output %s", gaps.line())
        try:
            await backend.release()
        except Exception as error:  # noqa: BLE001 (= backend が止まっていても、 会話は終える)
            logger.warning("voice call: could not release the conversation: %s", error)
