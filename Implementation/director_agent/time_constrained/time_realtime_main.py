"""
director_agent/time_constrained/time_realtime_main.py

Option B — Time-Constrained Director as a tool call inside an OpenAI Realtime API session.

Same architecture as realtime_main.py, but uses the time-constrained director
(time_director_core.get_time_director_decision) and a TemporalMonitor to track
pacing. The temporal state is included in every tool result so the actor can
pace the story accordingly.

When time runs out, a close-story message is injected into the session and the
actor is asked to wrap up immediately.

The offline versions (time_main.py, time_auto_main.py, time_runner.py) are untouched.

Requires:
    OPENAI_API_KEY in Implementation/.env
    PulseAudio (parec / paplay) for audio — already present in WSLg

Example:
    python director_agent/time_constrained/time_realtime_main.py \\
      --character character_prompts.olaf \\
      --scenario scenarios.olaf_derailment_scenario_suite \\
      --scenario-name olaf_arendelle_tour_complete_derailment \\
      --time-limit 5
"""

import os
import sys
import json
import asyncio
import base64
import argparse
import importlib
import threading
import queue as stdlib_queue
from datetime import datetime

import subprocess
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI
from openai._types import Omit

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DIRECTOR_AGENT_DIR = os.path.dirname(CURRENT_DIR)
IMPLEMENTATION_DIR = os.path.dirname(DIRECTOR_AGENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)
sys.path.append(DIRECTOR_AGENT_DIR)
sys.path.append(CURRENT_DIR)

from time_director_core import get_time_director_decision
from time_control import TemporalMonitor
from audio_fx import get_fx_chain, apply_fx, OLAF_AUDIOFX_CONFIG

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

REALTIME_MODEL = "gpt-realtime"
DIRECTOR_MODEL = "gpt-4o-mini"
AUDIO_SAMPLE_RATE = 24_000
AUDIO_CHANNELS = 1
MIC_CHUNK_FRAMES = 1024
TIME_CHECK_INTERVAL = 4.0  # seconds between time-up checks


# System prompt

def build_system_prompt(
    character: dict,
    story_topic: str,
    story_state: dict,
    beats: list,
    time_limit: float,
) -> str:
    idx = story_state["beat_index"]
    safe_idx = min(idx, len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    story_tail = story_state["story_so_far"][-800:] if story_state["story_so_far"] else "(story has not started yet)"

    return f"""
You are an interactive storytelling engine voicing an AI character.
You speak AS the character. Stay in character at all times.
The story has a target duration of {time_limit} minutes.

CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak a single word until you have received the director instruction.
After receiving the tool result, use its director_instruction AND pacing_mode
to shape your response.

## Character

Name: {character["name"]}

{character["character_prompt"]}

## Story Topic

{story_topic}

## Actor Rules

- Speak only as the character. Never mention the Director or the tool call.
- Keep responses short: 2–4 sentences, natural spoken aloud.
- The response must contain a concrete new story development.
- The director_instruction in the tool result is mandatory — realize it.
- If the user interrupted, acknowledge briefly, then return to the story.
- Vary tone: sometimes excited, sometimes curious, sometimes gentle, sometimes direct.
- Do not start most turns with "Oh". Do not repeat the same catchphrases.

## Pacing Rules (from tool result pacing_mode field)

- too_fast: story is ahead of schedule — expand the current beat with detail, emotion, suspense.
  Do NOT rush to the next beat.
- normal: continue naturally, no rush.
- hurry: make faster progress, avoid lingering.
- critical: compress story events, move toward the ending quickly.
- final: time is up — give a complete, satisfying ending NOW covering all remaining beats.

## Current Story State

Beat {idx + 1} of {len(beats)}: {current_beat["name"]}
Goal: {current_beat["goal"]}
Next beat: {next_beat}
Completed beats: {json.dumps(story_state["completed_beats"])}

Story so far (last excerpt):
{story_tail}
""".strip()


# Director tool schema

DIRECTOR_TOOL = {
    "type": "function",
    "name": "get_director_decision",
    "description": (
        "Get the time-aware director instruction for this story turn. "
        "You MUST call this before every response. "
        "Use the returned director_instruction and pacing_mode to guide the character."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_input": {
                "type": "string",
                "description": "Verbatim transcription of what the user just said.",
            }
        },
        "required": ["user_input"],
    },
}


# Audio workers

def playback_worker(q: stdlib_queue.Queue, fx_chain=None) -> None:
    """Writes PCM bytes to speakers via paplay (PulseAudio). None = stop."""
    proc = subprocess.Popen(
        ["paplay", "--raw", "--format=s16le",
         f"--rate={AUDIO_SAMPLE_RATE}", "--channels=1"],
        stdin=subprocess.PIPE,
    )
    while True:
        chunk = q.get()
        if chunk is None:
            break
        try:
            if fx_chain is not None:
                chunk = apply_fx(chunk, fx_chain, AUDIO_SAMPLE_RATE)
            proc.stdin.write(chunk)
            proc.stdin.flush()
        except BrokenPipeError:
            break
    proc.stdin.close()
    proc.wait()


def mic_capture_worker(
    async_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    """Captures mic audio via parec (PulseAudio) and forwards chunks to asyncio."""
    proc = subprocess.Popen(
        ["parec", "--format=s16le",
         f"--rate={AUDIO_SAMPLE_RATE}", "--channels=1"],
        stdout=subprocess.PIPE,
    )
    chunk_bytes = MIC_CHUNK_FRAMES * 2  # 16-bit = 2 bytes per sample
    while not stop_event.is_set():
        chunk = proc.stdout.read(chunk_bytes)
        if chunk:
            loop.call_soon_threadsafe(async_queue.put_nowait, chunk)
    proc.terminate()
    proc.wait()


# Helpers

def load_module(name: str):
    return importlib.import_module(name)


def load_scenario(scenario_module: str, scenario_name: str | None) -> dict:
    mod = load_module(scenario_module)
    if scenario_name:
        if not hasattr(mod, "SCENARIOS"):
            raise ValueError(f"{scenario_module} has no SCENARIOS dict.")
        if scenario_name not in mod.SCENARIOS:
            raise ValueError(f"Scenario '{scenario_name}' not found. Available: {list(mod.SCENARIOS.keys())}")
        return mod.SCENARIOS[scenario_name]
    return mod.SCENARIO


def text_indicates_next_beat(text: str, current_beat_name: str) -> bool:
    text = text.lower()
    beat_keywords = {
        "story_opening": ["mother warned", "stay on the path", "entered the forest"],
        "home_and_family_setup": ["stay on the path", "avoid strangers", "into the woods"],
        "warning_before_departure": ["entered the forest", "flowers", "birds", "wolf"],
        "forest_entry": ["wolf", "talked to the wolf", "asked where she was going"],
        "forest_distraction": ["grandmother's cottage", "where does your grandmother live"],
        "wolf_appears": ["shared details", "grandmother's cottage", "butterfly"],
        "conversation_and_disclosure": ["cottage", "disguised", "grandmother in bed"],
        "wolf_manipulates_delay": ["big eyes", "big teeth", "revealed his true nature"],
        "wolf_reaches_cottage_first": ["woodcutter", "rescued", "safe now"],
        "grandmother_in_danger": ["reflected", "lessons learned", "shared treats"],
        "red_approaches_cottage": ["lessons learned", "safe together", "look out for each other"],
    }
    return any(kw in text for kw in beat_keywords.get(current_beat_name, []))


def advance_beat(story_state: dict, beats: list) -> None:
    idx = story_state["beat_index"]
    if idx < len(beats):
        story_state["completed_beats"].append(beats[idx]["name"])
        story_state["beat_index"] += 1
        story_state["turns_in_current_beat"] = 0
        if story_state["beat_index"] < len(beats):
            print(f"[Beat complete → {beats[story_state['beat_index']]['name']}]")
        else:
            print("[Final beat complete — story ending]")


# Main realtime loop

async def run_realtime(
    character: dict,
    scenario: dict,
    output_dir: str,
    voice: str,
    time_limit: float,
    fx_chain=None,
) -> None:
    sync_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    beats = scenario["beats"]
    story_topic = scenario["story_topic"]
    scenario_name = scenario["scenario_name"]

    monitor = TemporalMonitor(
        time_limit_minutes=time_limit,
        total_beats=len(beats),
    )

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }
    transcript: list[dict] = []

    turn: dict = {
        "user_input": "",
        "director_decision": None,
        "actor_text": "",
        "beat_advanced": False,
    }

    story_ended = asyncio.Event()
    response_in_progress = False  # guard: don't inject time-up during active response
    mic_queue: asyncio.Queue = asyncio.Queue()
    playback_queue: stdlib_queue.Queue = stdlib_queue.Queue()
    mic_stop = threading.Event()

    loop = asyncio.get_event_loop()

    playback_thread = threading.Thread(
        target=playback_worker, args=(playback_queue, fx_chain), daemon=True
    )
    playback_thread.start()

    mic_thread = threading.Thread(
        target=mic_capture_worker, args=(mic_queue, loop, mic_stop), daemon=True
    )
    mic_thread.start()

    async def stream_mic(connection):
        while not story_ended.is_set():
            try:
                chunk = await asyncio.wait_for(mic_queue.get(), timeout=0.05)
                await connection.input_audio_buffer.append(
                    audio=base64.b64encode(chunk).decode()
                )
            except asyncio.TimeoutError:
                continue

    async def check_time(connection):
        """Periodically check if time is up and inject a close-story trigger."""
        nonlocal response_in_progress
        while not story_ended.is_set():
            await asyncio.sleep(TIME_CHECK_INTERVAL)
            if story_ended.is_set():
                break
            if monitor.should_stop_for_time() and not response_in_progress:
                print("\n[Time's up — injecting story close]")
                await connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "[Story time ended — wrap up all remaining story beats immediately with a complete, satisfying ending]",
                            }
                        ],
                    }
                )
                await connection.response.create()
                story_ended.set()

    async def handle_events(connection):
        nonlocal response_in_progress

        async for event in connection:
            etype = event.type

            if etype == "response.created":
                response_in_progress = True

            elif etype == "conversation.item.input_audio_transcription.completed":
                turn["user_input"] = event.transcript.strip()
                print(f"\nYou: {turn['user_input']}")

            elif etype == "response.function_call_arguments.done":
                if event.name != "get_director_decision":
                    continue

                args = json.loads(event.arguments)
                user_input = args.get("user_input") or turn["user_input"]
                turn["user_input"] = user_input
                story_state["turns_in_current_beat"] += 1
                turn["beat_advanced"] = False

                # Compute temporal state at the moment of this tool call
                safe_idx = min(story_state["beat_index"], len(beats) - 1)
                temporal_state = monitor.state(safe_idx, beats)
                pacing_mode = temporal_state["pacing_mode"]

                print(f"[Pacing: {pacing_mode} | Elapsed: {temporal_state['elapsed_seconds']:.0f}s | Remaining: {temporal_state['remaining_seconds']:.0f}s]")

                decision = get_time_director_decision(
                    client=sync_client,
                    model=DIRECTOR_MODEL,
                    user_input=user_input,
                    story_state=story_state,
                    character=character,
                    story_topic=story_topic,
                    beats=beats,
                    temporal_state=temporal_state,
                )
                turn["director_decision"] = decision

                dtype = decision.get("decision_type", "?")
                instr = decision.get("director_instruction", "")[:80]
                print(f"[Director: {dtype}] {instr}...")

                current_beat = beats[safe_idx]
                next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"

                # Tool result includes both director instruction and temporal state
                await connection.conversation.item.create(
                    item={
                        "type": "function_call_output",
                        "call_id": event.call_id,
                        "output": json.dumps({
                            "director_instruction": decision.get("director_instruction", ""),
                            "decision_type": dtype,
                            "pacing_mode": pacing_mode,
                            "elapsed_seconds": temporal_state["elapsed_seconds"],
                            "remaining_seconds": temporal_state["remaining_seconds"],
                            "current_beat": current_beat["name"],
                            "current_beat_goal": current_beat["goal"],
                            "next_beat": next_beat,
                            "story_so_far_tail": story_state["story_so_far"][-400:],
                        }),
                    }
                )
                await connection.response.create()

                if decision.get("should_complete_beat") and story_state["beat_index"] < len(beats):
                    advance_beat(story_state, beats)
                    turn["beat_advanced"] = True

                # Update system prompt for next turn
                await connection.session.update(session={
                    "type": "realtime",
                    "instructions": build_system_prompt(
                        character, story_topic, story_state, beats, time_limit
                    ),
                })

                if story_state["beat_index"] >= len(beats):
                    story_ended.set()

            elif etype == "response.audio.delta":
                playback_queue.put(base64.b64decode(event.delta))

            elif etype == "response.audio_transcript.delta":
                turn["actor_text"] += event.delta

            elif etype == "response.done":
                response_in_progress = False
                actor_text = turn["actor_text"].strip()
                decision = turn["director_decision"]

                if actor_text and decision:
                    print(f"\n{character['name']}: {actor_text}")

                    if not turn["beat_advanced"] and story_state["beat_index"] < len(beats):
                        current_beat_name = beats[story_state["beat_index"]]["name"]
                        if text_indicates_next_beat(actor_text, current_beat_name):
                            advance_beat(story_state, beats)
                            turn["beat_advanced"] = True

                    safe_idx = min(story_state["beat_index"], len(beats) - 1)
                    temporal_state = monitor.state(safe_idx, beats)

                    story_state["story_so_far"] += (
                        f"\nUser: {turn['user_input']}"
                        f"\nTemporal Mode: {temporal_state['pacing_mode']}"
                        f"\nDirector: {decision.get('decision_type')}"
                        f"\n{character['name']}: {actor_text}\n"
                    )
                    transcript.append({
                        "method": "realtime_target_duration_director_agent",
                        "character": character["name"],
                        "scenario": scenario_name,
                        "time_limit_minutes": time_limit,
                        "beat": beats[safe_idx]["name"],
                        "user_input": turn["user_input"],
                        "temporal_state": temporal_state,
                        "director_decision": decision,
                        "actor_response_text": actor_text,
                    })

                turn["user_input"] = ""
                turn["director_decision"] = None
                turn["actor_text"] = ""
                turn["beat_advanced"] = False

                if story_state["beat_index"] >= len(beats):
                    story_ended.set()

            elif etype == "error":
                print(f"\n[Realtime error] {getattr(event, 'error', event)}")
                response_in_progress = False

            if story_ended.is_set():
                break

    async with async_client.beta.realtime.connect(
        model=REALTIME_MODEL,
        extra_headers={"OpenAI-Beta": Omit()},  # strip the beta header — API is now GA
    ) as connection:
        await connection.session.update(session={
            "type": "realtime",
            "model": REALTIME_MODEL,
            "instructions": build_system_prompt(character, story_topic, story_state, beats, time_limit),
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": 700,
                        "threshold": 0.5,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "voice": voice,
                },
            },
            "tools": [DIRECTOR_TOOL],
            "tool_choice": "auto",
        })

        print(f"\nRealtime time-constrained storytelling started.")
        print(f"Character:      {character['name']}")
        print(f"Scenario:       {scenario_name}")
        print(f"Target duration: {time_limit} min")
        print(f"Speak to begin. Press Ctrl+C to stop.\n")

        mic_task = asyncio.create_task(stream_mic(connection))
        event_task = asyncio.create_task(handle_events(connection))
        time_task = asyncio.create_task(check_time(connection))

        try:
            done, pending = await asyncio.wait(
                [mic_task, event_task, time_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            mic_stop.set()
            playback_queue.put(None)
            playback_thread.join(timeout=2)

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"realtime_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)
    print(f"\nTranscript saved to {path}")


# Entry point

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_derailment_scenario_suite")
    parser.add_argument("--scenario-name", default=None, help="For suite modules: e.g. olaf_arendelle_tour_complete_derailment")
    parser.add_argument("--time-limit", type=float, default=5.0, help="Target story duration in minutes (default: 5).")
    parser.add_argument(
        "--voice",
        default="verse",
        choices=["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"],
        help="Realtime API voice for the character (default: verse).",
    )
    args = parser.parse_args()

    character_mod = load_module(args.character)
    character = character_mod.CHARACTER
    scenario = load_scenario(args.scenario, args.scenario_name)

    scenario_folder = scenario["scenario_name"]
    output_dir = os.path.join(
        IMPLEMENTATION_DIR,
        "outputs",
        "target_duration_director_agent",
        scenario_folder,
        f"{args.time_limit}min",
        "realtime",
    )

    fx_chain = None
    char_name = character.get("name", "").lower()
    if char_name == "olaf":
        fx_chain = get_fx_chain(OLAF_AUDIOFX_CONFIG)
        print(f"[AudioFX] Olaf: pitch+2 semitones, warm reverb enabled")

    asyncio.run(run_realtime(character, scenario, output_dir, args.voice, args.time_limit, fx_chain))


if __name__ == "__main__":
    main()
