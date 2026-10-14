"""電話の会話 1 本の組み立て (= Pipecat の標準の並び。 LLM の段にタブの agent が居る)。

    受け口 (= WebRTC) → 聞き取り → 発話のまとめ役 (= Silero で声の区間、 Smart Turn で言い終え) → agent → 声 → 送り口

間の取り方は、 画面の会話と同じ設定 (= `voice.conversation`) から決める:
    pause_ms            声が途切れたと見る無音 (= Silero の stop_secs)
    wait_ms             言い終えていないと判定された時に、 送るまで待つ無音 (= Smart Turn の stop_secs)
    unfinished_endings  言いさしの語尾 (= agent の段が続きを待つ)
    interrupt           返事の途中で話したら止めるか (= 止めない時は、 返事の間は聞かない)
"""
from __future__ import annotations

import logging

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
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from backend.routes.voice import claim_conversation, owns_conversation, release_conversation
from backend.voice_call.agent import AgentBridge
from backend.voice_call.services import ListenSTT, VoiceTTS

logger = logging.getLogger(__name__)

async def run_call(session_id: str, connection: SmallWebRTCConnection, client: str, send) -> None:
    """1 本の電話の会話を、 つながっている間走らせる。 send(session_id, text) -> 送れたか。"""
    settings = claim_conversation(session_id, client)
    conversation = settings["conversation"]
    listen = settings["listen"]

    transport = SmallWebRTCTransport(
        webrtc_connection=connection, params=TransportParams(audio_in_enabled=True, audio_out_enabled=True))
    turn = LocalSmartTurnAnalyzerV3(
        smart_turn_model_path=listen["turn"] or None,
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
        await runner.cancel()

    agent = AgentBridge(
        session_id, settings,
        send=lambda text: send(session_id, text),
        owns=lambda: owns_conversation(session_id, client),
        on_lost=lost,
    )
    pipeline = Pipeline([
        transport.input(),
        ListenSTT(session_id),
        user_aggregator,
        agent,
        VoiceTTS(session_id, settings["marks"]),
        transport.output(),
    ])
    worker = PipelineWorker(pipeline, params=PipelineParams())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client_):
        logger.info("voice call: session=%s the phone hung up", session_id)
        await runner.cancel()

    logger.info("voice call: session=%s started client=%s", session_id, client)
    try:
        await runner.add_workers(worker)
        await runner.run()
    finally:
        release_conversation(session_id, client)
        logger.info("voice call: session=%s ended", session_id)
