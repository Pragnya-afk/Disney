"""
director_agent/realtime_main.py

Option B — Director Agent as a tool call inside an OpenAI Realtime API session.

Architecture:
  User speaks → Realtime session (actor lives here) → calls get_director_decision tool
                                                        │
                                                        ▼
                                           director_core.get_director_decision()
                                           (standard chat.completions call, unchanged)
                                                        │
                                                        ▼
                                           tool result returned to Realtime session
                                                        │
                                                        ▼
                                           Actor speaks character response (audio)

The offline versions (main.py, auto_main.py, runner.py) are untouched.

Requires:
    OPENAI_API_KEY in Implementation/.env
    PulseAudio (parec / paplay) for audio — already present in WSLg

Example:
    python director_agent/realtime_main.py \\
      --character character_prompts.olaf \\
      --scenario scenarios.olaf_anna_courtyard
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
IMPLEMENTATION_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(IMPLEMENTATION_DIR)
sys.path.append(CURRENT_DIR)

from director_core import get_director_decision

load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

REALTIME_MODEL = "gpt-realtime"
DIRECTOR_MODEL = "gpt-4o-mini"
AUDIO_SAMPLE_RATE = 24_000
AUDIO_CHANNELS = 1
MIC_CHUNK_FRAMES = 1024  # ~43ms per chunk at 24 kHz


# ─────────────────────────────────────────────────────────────────────────────
# Session system prompt (rebuilt each turn to reflect current story state)
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(
    character: dict,
    story_topic: str,
    story_state: dict,
    beats: list,
) -> str:
    idx = story_state["beat_index"]
    safe_idx = min(idx, len(beats) - 1)
    current_beat = beats[safe_idx]
    next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"
    story_tail = story_state["story_so_far"][-800:] if story_state["story_so_far"] else "(story has not started yet)"

    return f"""
You are an interactive storytelling engine voicing an AI character.
You speak AS the character. Stay in character at all times.

CRITICAL: Before EVERY response you MUST call the get_director_decision tool.
Do not speak a single word until you have received the director instruction.
After you receive the tool result, use its director_instruction to shape your response.

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

## Current Story State

Beat {idx + 1} of {len(beats)}: {current_beat["name"]}
Goal: {current_beat["goal"]}
Next beat: {next_beat}
Completed beats: {json.dumps(story_state["completed_beats"])}

Story so far (last excerpt):
{story_tail}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Director tool schema (Realtime API format)
# ─────────────────────────────────────────────────────────────────────────────

DIRECTOR_TOOL = {
    "type": "function",
    "name": "get_director_decision",
    "description": (
        "Get the director's instruction for this story turn. "
        "You MUST call this before every response. "
        "Use the returned director_instruction to guide what the character says."
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


# ─────────────────────────────────────────────────────────────────────────────
# Audio workers (run in threads, bridge to asyncio via queues)
# ─────────────────────────────────────────────────────────────────────────────

def playback_worker(q: stdlib_queue.Queue) -> None:
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_module(name: str):
    return importlib.import_module(name)


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


# ─────────────────────────────────────────────────────────────────────────────
# Main realtime loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_realtime(
    character: dict,
    scenario: dict,
    output_dir: str,
    voice: str,
) -> None:
    sync_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    beats = scenario["beats"]
    story_topic = scenario["story_topic"]
    scenario_name = scenario["scenario_name"]

    story_state = {
        "beat_index": 0,
        "completed_beats": [],
        "story_so_far": "",
        "turns_in_current_beat": 0,
    }
    transcript: list[dict] = []

    # Per-turn state, reset after each response.done
    turn: dict = {
        "user_input": "",
        "director_decision": None,
        "actor_text": "",
        "beat_advanced": False,
    }

    story_ended = asyncio.Event()
    mic_queue: asyncio.Queue = asyncio.Queue()
    playback_queue: stdlib_queue.Queue = stdlib_queue.Queue()
    mic_stop = threading.Event()

    loop = asyncio.get_event_loop()

    playback_thread = threading.Thread(
        target=playback_worker, args=(playback_queue,), daemon=True
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

    async def handle_events(connection):
        async for event in connection:
            etype = event.type

            # User speech transcribed by the server
            if etype == "conversation.item.input_audio_transcription.completed":
                turn["user_input"] = event.transcript.strip()
                print(f"\nYou: {turn['user_input']}")

            # Director tool call from the actor model
            elif etype == "response.function_call_arguments.done":
                if event.name != "get_director_decision":
                    continue

                args = json.loads(event.arguments)
                user_input = args.get("user_input") or turn["user_input"]
                turn["user_input"] = user_input
                story_state["turns_in_current_beat"] += 1
                turn["beat_advanced"] = False

                # Run the director (unchanged offline pipeline)
                decision = get_director_decision(
                    client=sync_client,
                    model=DIRECTOR_MODEL,
                    user_input=user_input,
                    story_state=story_state,
                    character=character,
                    story_topic=story_topic,
                    beats=beats,
                )
                turn["director_decision"] = decision

                dtype = decision.get("decision_type", "?")
                instr = decision.get("director_instruction", "")[:80]
                print(f"[Director: {dtype}] {instr}...")

                safe_idx = min(story_state["beat_index"], len(beats) - 1)
                current_beat = beats[safe_idx]
                next_beat = beats[safe_idx + 1]["name"] if safe_idx < len(beats) - 1 else "None"

                # Return tool result — actor uses this to shape its spoken response
                await connection.conversation.item.create(
                    item={
                        "type": "function_call_output",
                        "call_id": event.call_id,
                        "output": json.dumps({
                            "director_instruction": decision.get("director_instruction", ""),
                            "decision_type": dtype,
                            "current_beat": current_beat["name"],
                            "current_beat_goal": current_beat["goal"],
                            "next_beat": next_beat,
                            "story_so_far_tail": story_state["story_so_far"][-400:],
                        }),
                    }
                )
                await connection.response.create()

                # Advance beat if director says so
                if decision.get("should_complete_beat") and story_state["beat_index"] < len(beats):
                    advance_beat(story_state, beats)
                    turn["beat_advanced"] = True

                # Refresh system prompt so next turn sees updated story state
                await connection.session.update(session={
                    "type": "realtime",
                    "instructions": build_system_prompt(character, story_topic, story_state, beats),
                })

                if story_state["beat_index"] >= len(beats):
                    story_ended.set()

            # Stream actor audio to speakers
            elif etype == "response.audio.delta":
                playback_queue.put(base64.b64decode(event.delta))

            # Accumulate actor transcript
            elif etype == "response.audio_transcript.delta":
                turn["actor_text"] += event.delta

            # Full response finished — update state and log
            elif etype == "response.done":
                actor_text = turn["actor_text"].strip()
                decision = turn["director_decision"]

                if actor_text and decision:
                    print(f"\n{character['name']}: {actor_text}")

                    # Fallback beat detection via text heuristic
                    if not turn["beat_advanced"] and story_state["beat_index"] < len(beats):
                        current_beat_name = beats[story_state["beat_index"]]["name"]
                        if text_indicates_next_beat(actor_text, current_beat_name):
                            advance_beat(story_state, beats)
                            turn["beat_advanced"] = True

                    story_state["story_so_far"] += (
                        f"\nUser: {turn['user_input']}"
                        f"\nDirector: {decision.get('decision_type')}"
                        f"\n{character['name']}: {actor_text}\n"
                    )
                    transcript.append({
                        "method": "realtime_director_agent",
                        "character": character["name"],
                        "scenario": scenario_name,
                        "beat": beats[min(story_state["beat_index"], len(beats) - 1)]["name"],
                        "user_input": turn["user_input"],
                        "director_decision": decision,
                        "actor_response_text": actor_text,
                    })

                # Reset per-turn state
                turn["user_input"] = ""
                turn["director_decision"] = None
                turn["actor_text"] = ""
                turn["beat_advanced"] = False

                if story_state["beat_index"] >= len(beats):
                    story_ended.set()

            elif etype == "error":
                print(f"\n[Realtime error] {getattr(event, 'error', event)}")

            if story_ended.is_set():
                break

    async with async_client.beta.realtime.connect(
        model=REALTIME_MODEL,
        extra_headers={"OpenAI-Beta": Omit()},  # strip the beta header — API is now GA
    ) as connection:
        await connection.session.update(session={
            "type": "realtime",
            "model": REALTIME_MODEL,
            "instructions": build_system_prompt(character, story_topic, story_state, beats),
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

        print(f"\nRealtime storytelling started.")
        print(f"Character: {character['name']}")
        print(f"Scenario:  {scenario_name}")
        print(f"Speak to begin. Press Ctrl+C to stop.\n")

        mic_task = asyncio.create_task(stream_mic(connection))
        event_task = asyncio.create_task(handle_events(connection))

        try:
            done, pending = await asyncio.wait(
                [mic_task, event_task],
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


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True, help="e.g. character_prompts.olaf")
    parser.add_argument("--scenario", required=True, help="e.g. scenarios.olaf_anna_courtyard")
    parser.add_argument(
        "--voice",
        default="verse",
        choices=["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"],
        help="Realtime API voice for the character (default: verse).",
    )
    args = parser.parse_args()

    character_mod = load_module(args.character)
    scenario_mod = load_module(args.scenario)
    character = character_mod.CHARACTER
    scenario = scenario_mod.SCENARIO

    scenario_folder = args.scenario.split(".")[-1]
    output_dir = os.path.join(
        IMPLEMENTATION_DIR, "outputs", "director_agent", scenario_folder, "realtime"
    )

    asyncio.run(run_realtime(character, scenario, output_dir, args.voice))


if __name__ == "__main__":
    main()
