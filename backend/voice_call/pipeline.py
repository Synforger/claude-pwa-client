"""電話の会話 1 本の組み立て (= Pipecat の標準の並び。 LLM の段にタブの agent が居る)。

    受け口 (= WebRTC) → 聞き取り → 発話のまとめ役 (= Silero で声の区間、 Smart Turn で言い終え) → agent → 声 → 送り口

間の取り方は、 画面の会話と同じ設定 (= `voice.conversation`) から決める:
    pause_ms            声が途切れたと見る無音 (= Silero の stop_secs)
    wait_ms             言い終えていないと判定された時に、 送るまで待つ無音 (= Smart Turn の stop_secs)
    unfinished_endings  言いさしの語尾 (= agent の段が続きを待つ)
    interrupt           返事の途中で話したら止めるか (= 止めない時は、 返事の間は聞かない)

送り出しの途切れ: Pipecat は返事の音を 10 ms ずつ WebRTC へ渡し、 渡した分が送られてから次を渡す。 次が 10 ms
以内に間に合わないと、 その 10 ms は無音で埋まる (= 聞こえる「ぷつっ」)。 会話を専用の process で動かすのは、
backend 本体の他の仕事でこの受け渡しを遅らせないため。 話している途中に挟まった短い無音の回数を log に出す。
"""
from __future__ import annotations

import asyncio
import logging
import time

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import RawAudioTrack, SmallWebRTCTransport
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from backend.voice_call.agent import AgentBridge
from backend.voice_call.client import BackendClient
from backend.voice_call.services import ListenSTT, VoiceTTS

logger = logging.getLogger(__name__)

# 「話している途中の途切れ」 と数える無音の長さ (= 10 ms の枠の数。 文と文の間は合成を待つので、 これより長い)
GAP_FRAMES_MAX = 5
# 途切れの数を log に出す間隔
REPORT_SECS = 10


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


async def run_call(connection: SmallWebRTCConnection, backend: BackendClient, start: dict) -> None:
    """1 本の電話の会話を、 つながっている間走らせる。

    start: backend が渡す、 そのタブの声の設定 (= marks の名前の並び / conversation / turn の model の path)
    """
    conversation = start["conversation"]
    gaps = OutputGaps()
    watch_output(gaps)
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

    pipeline = Pipeline([
        transport.input(),
        ListenSTT(backend, on_lost=lost),
        user_aggregator,
        AgentBridge(conversation, send=backend.send, events=backend.events, utterances=backend.utterances),
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

    await backend.claim()
    logger.info("voice call: started client=%s", backend.client)
    reporter = asyncio.create_task(report())
    try:
        await runner.add_workers(PipelineWorker(pipeline, params=PipelineParams()))
        await runner.run()
    finally:
        reporter.cancel()
        logger.info("voice call: ended output %s", gaps.line())
        try:
            await backend.release()
        except Exception as error:  # noqa: BLE001 (= backend が止まっていても、 会話は終える)
            logger.warning("voice call: could not release the conversation: %s", error)
