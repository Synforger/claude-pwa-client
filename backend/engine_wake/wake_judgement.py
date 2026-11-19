"""Which voice engines the client wakes and puts to rest, and what to do with one on a look of the patrol. Pure: it
takes what was read and answers; it reads no file, no socket and no state. Used by `wake_patrol.py`.

An agent names the resident service of its speech engine in `voice.engine_service`
(`{"label": "<launchd label>", "idle_minutes": 10}`). Agents that point at the same engine URL share one engine.
"""
from __future__ import annotations

from dataclasses import dataclass

# How long an engine no voice has used is left running when the agent does not say
DEFAULT_IDLE_MINUTES = 10.0

# What the patrol does with an engine on a look
WAKE = "wake"
STOP = "stop"
LEAVE = "leave"

# What a screen is told of an engine (= `GET /sessions/{id}/voice/engine`)
READY = "ready"
WAKING = "waking"
ASLEEP = "asleep"
FAILED = "failed"
# What the engine is being put through right now
STARTING = "starting"
RESTING = "resting"


@dataclass(frozen=True)
class EngineService:
    """One speech engine the client wakes and puts to rest: its URL, its resident service, how long it may sit unused,
    and the voice that warms it up (= the speaker of the first agent that names it)."""
    url: str
    label: str
    idle_minutes: float
    speaker: object


def engine_services(agents: dict) -> tuple[dict[str, EngineService], list[str]]:
    """The engines the agents' `voice.engine_service` name, by engine URL, and a warning for each one written wrongly
    or in conflict (= the first agent's label is kept; of several idle times, the longest)."""
    services: dict[str, EngineService] = {}
    warnings: list[str] = []
    for agent_id, agent in agents.items():
        voice = agent.get("voice") if isinstance(agent, dict) else None
        if not isinstance(voice, dict) or "engine_service" not in voice:
            continue
        problem = _problem(voice)
        if problem:
            warnings.append(f"agent {agent_id}: voice.engine_service {problem}; its engine is left to its service")
            continue
        raw = voice["engine_service"]
        url = voice["engine"].rstrip("/")
        idle = float(raw.get("idle_minutes", DEFAULT_IDLE_MINUTES))
        known = services.get(url)
        if known is None:
            services[url] = EngineService(url, raw["label"], idle, voice.get("speaker"))
            continue
        if known.label != raw["label"]:
            warnings.append(f"agent {agent_id}: voice.engine_service.label {raw['label']} differs from {known.label} "
                            f"for {url}; {known.label} is used")
        services[url] = EngineService(url, known.label, max(known.idle_minutes, idle), known.speaker)
    return services, warnings


def next_step(*, voice_open: bool, answers: bool, busy: bool, waiting_to_retry: bool, idle_minutes: float,
              quiet_minutes: float, kept_alive: bool = False) -> str:
    """What to do with an engine on a look. `voice_open`: a screen or a call that uses it has voice on; `answers`: it
    takes a connection; `busy`: it is being woken or put to rest; `waiting_to_retry`: a wake failed a short while ago;
    `quiet_minutes`: since it was last used (= a speech asked of it, a look that found its voice open, its waking, or
    the backend's start); `kept_alive`: it came back by itself after it was put to rest (= its service is declared to
    be kept alive, so a rest would only restart it)."""
    if busy:
        return LEAVE
    if voice_open:
        return WAKE if not answers and not waiting_to_retry else LEAVE
    if answers and quiet_minutes >= idle_minutes and not kept_alive:
        return STOP
    return LEAVE


def engine_state(*, phase: str | None, up: bool, waiting_to_retry: bool) -> str:
    """What a screen is told of a handled engine. `phase`: it is being started or put to rest (None = neither); `up`:
    it took a connection when last looked at (= by the patrol, a wake or a rest); `waiting_to_retry`: a wake failed a
    short while ago."""
    if phase == STARTING:
        return WAKING
    if phase == RESTING:
        return ASLEEP
    if waiting_to_retry:
        return FAILED
    return READY if up else ASLEEP


def _problem(voice: dict) -> str:
    raw = voice["engine_service"]
    if not isinstance(voice.get("engine"), str) or not voice["engine"].startswith(("http://", "https://")):
        return "needs voice.engine, the engine's URL"
    if not isinstance(raw, dict):
        return "is not an object"
    if not isinstance(raw.get("label"), str) or not raw["label"].strip():
        return "needs a label (= the name of the engine's resident service)"
    idle = raw.get("idle_minutes", DEFAULT_IDLE_MINUTES)
    if isinstance(idle, bool) or not isinstance(idle, (int, float)) or idle <= 0:
        return "has an idle_minutes that is not a positive number"
    return ""
