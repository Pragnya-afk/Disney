"""
generate_audio.py

Generate an audio file from a transcript JSON.

User inputs are spoken in one voice; Olaf's character responses in another.
Uses OpenAI TTS with PCM output so no extra dependencies are needed beyond
the OpenAI SDK that is already in the project.  Output is a standard WAV file.

OpenAI TTS voices: alloy  echo  fable  onyx  nova  shimmer
Good defaults:
    --character-voice fable    (warm, storytelling feel — suits Olaf)
    --user-voice      shimmer  (soft, clear)

Usage (run from Implementation/):
    python generate_audio.py \\
        --transcript outputs/director_agent/complete_derail_red_riding_hood/batch/run_1.json

    python generate_audio.py \\
        --transcript outputs/director_agent/complete_derail_red_riding_hood/batch/run_1.json \\
        --output audio/my_story.wav \\
        --character-voice fable \\
        --user-voice shimmer \\
        --pause-between-turns 1000 \\
        --pause-after-user 600
"""

import json
import os
import sys
import wave
import argparse
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from audio_fx import get_fx_chain, apply_fx, OLAF_AUDIOFX_CONFIG

IMPLEMENTATION_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(IMPLEMENTATION_DIR, ".env"))

# OpenAI PCM specs (fixed by the API)
SAMPLE_RATE = 24_000
SAMPLE_WIDTH = 2   # 16-bit
CHANNELS = 1


# ──────────────────────────────────────────────────────────────────────────────
# Audio helpers
# ──────────────────────────────────────────────────────────────────────────────

def silence(ms: int) -> bytes:
    """Return ms milliseconds of 16-bit mono silence."""
    n_samples = int(SAMPLE_RATE * ms / 1000)
    return b"\x00\x00" * n_samples


def save_wav(pcm: bytes, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


# ──────────────────────────────────────────────────────────────────────────────
# TTS
# ──────────────────────────────────────────────────────────────────────────────

def tts(client: OpenAI, text: str, voice: str, model: str, instructions: str | None = None, speed: float = 1.0) -> bytes:
    """Call OpenAI TTS and return raw PCM bytes."""
    kwargs = dict(model=model, voice=voice, input=text, response_format="pcm", speed=speed)
    if instructions:
        kwargs["instructions"] = instructions
    response = client.audio.speech.create(**kwargs)
    return response.content


# ──────────────────────────────────────────────────────────────────────────────
# Transcript parsing
# ──────────────────────────────────────────────────────────────────────────────

def extract_turns(transcript: list) -> list[tuple[str, str]]:
    """
    Return a list of (speaker, text) pairs in dialogue order.
    speaker is either "user" or "character".
    """
    turns = []
    for turn in transcript:
        user_text = turn.get("user_input", "").strip()
        if "actor_output" in turn:
            char_text = turn["actor_output"].get("character_response", "").strip()
        elif "model_output" in turn:
            char_text = turn["model_output"].get("character_response", "").strip()
        else:
            char_text = ""

        if user_text:
            turns.append(("user", user_text))
        if char_text:
            turns.append(("character", char_text))

    return turns


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a WAV audio file from a story transcript JSON."
    )
    parser.add_argument(
        "--transcript", required=True,
        help="Path to the transcript JSON file.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output WAV file path. Defaults to <transcript_stem>.wav next to the input.",
    )
    parser.add_argument(
        "--character-voice", default="fable",
        choices=["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "shimmer", "verse"],
        help="OpenAI TTS voice for the character (default: fable; --olaf overrides to verse).",
    )
    parser.add_argument(
        "--user-voice", default="shimmer",
        choices=["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "shimmer", "verse"],
        help="OpenAI TTS voice for the user (default: shimmer).",
    )
    parser.add_argument(
        "--model", default="tts-1",
        choices=["tts-1", "tts-1-hd", "gpt-4o-mini-tts"],
        help="OpenAI TTS model. gpt-4o-mini-tts supports --character-instructions (default: tts-1).",
    )
    parser.add_argument(
        "--olaf", action="store_true",
        help=(
            "Shortcut: sets model=gpt-4o-mini-tts and applies Olaf-style voice instructions. "
            "Overrides --character-instructions."
        ),
    )
    parser.add_argument(
        "--child", action="store_true",
        help=(
            "Shortcut: sets model=gpt-4o-mini-tts and applies child voice instructions for the user. "
            "Overrides --user-instructions."
        ),
    )
    parser.add_argument(
        "--character-instructions", default=None,
        help=(
            "Voice style instructions for the character (only used with gpt-4o-mini-tts). "
            'Example: "Speak like an enthusiastic, childlike snowman."'
        ),
    )
    parser.add_argument(
        "--user-instructions", default=None,
        help="Voice style instructions for the user speaker (only used with gpt-4o-mini-tts).",
    )
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="Playback speed for all voices: 0.25 (slowest) to 4.0 (fastest). Default: 1.0.",
    )
    parser.add_argument(
        "--user-speed", type=float, default=None,
        help="Speed override for user voice only. Overrides --speed for user turns.",
    )
    parser.add_argument(
        "--character-speed", type=float, default=None,
        help="Speed override for character voice only. Overrides --speed for character turns.",
    )
    parser.add_argument(
        "--pause-between-turns", type=int, default=900,
        help="Silence in ms between a character response and the next user input (default: 900).",
    )
    parser.add_argument(
        "--pause-after-user", type=int, default=500,
        help="Silence in ms between a user input and the character response (default: 500).",
    )
    args = parser.parse_args()

    OLAF_INSTRUCTIONS = (
        "Speak as Olaf, a warm, innocent, and enthusiastic snowman. "
        "Your voice is bright, slightly high-pitched, and full of childlike wonder. "
        "You are cheerful and kind, and you love giving warm hugs. "
        "Deliver each line with gentle excitement and a playful storytelling rhythm."
    )

    CHILD_INSTRUCTIONS = (
        "You are a 6-year-old child. "
        "Speak with a very high-pitched, small, light voice. "
        "Sound genuinely excited and innocent. "
        "Slightly breathless, like a child who just ran in from outside. "
        "Pronounce words simply and clearly, with natural childlike energy."
    )

    if args.olaf:
        args.model = "gpt-4o-mini-tts"
        args.character_instructions = OLAF_INSTRUCTIONS
        if args.character_voice == "fable":  # only override if still at default
            args.character_voice = "verse"

    if args.child:
        args.model = "gpt-4o-mini-tts"
        args.user_instructions = CHILD_INSTRUCTIONS
        if args.user_voice == "shimmer":  # only override if still at default
            args.user_voice = "nova"

    character_instructions = args.character_instructions
    user_instructions = args.user_instructions

    character_fx = get_fx_chain(OLAF_AUDIOFX_CONFIG) if args.olaf else None

    if (character_instructions or user_instructions) and args.model != "gpt-4o-mini-tts":
        print(
            "Warning: --character-instructions / --user-instructions only work with "
            "--model gpt-4o-mini-tts. Switching model automatically.",
            file=sys.stderr,
        )
        args.model = "gpt-4o-mini-tts"

    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        print(f"Error: transcript not found: {transcript_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output) if args.output else transcript_path.with_suffix(".wav")

    with open(transcript_path, encoding="utf-8") as f:
        transcript = json.load(f)

    turns = extract_turns(transcript)
    if not turns:
        print("Error: no turns found in transcript.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    voice_map = {
        "user": args.user_voice,
        "character": args.character_voice,
    }
    instructions_map = {
        "user": user_instructions,
        "character": character_instructions,
    }

    print(f"Transcript: {transcript_path}")
    print(f"Output:     {output_path}")
    print(f"Model:      {args.model}")
    print(f"Voices:     user={args.user_voice}  character={args.character_voice}")
    if character_instructions:
        print(f"Char style: {character_instructions[:80]}...")
    if character_fx is not None:
        print(f"Char FX:    pitch+2 semitones, warm reverb (Olaf)")
    print(f"Turns:      {len(turns)}")
    print()

    pcm_segments = []
    prev_speaker = None

    for i, (speaker, text) in enumerate(turns, start=1):
        # Insert pause between segments
        if prev_speaker is not None:
            if prev_speaker == "user" and speaker == "character":
                pcm_segments.append(silence(args.pause_after_user))
            elif prev_speaker == "character" and speaker == "user":
                pcm_segments.append(silence(args.pause_between_turns))

        label = "User" if speaker == "user" else "Character"
        preview = text[:60] + "..." if len(text) > 60 else text
        print(f"[{i}/{len(turns)}] {label}: {preview}")

        speed = (
            args.user_speed if speaker == "user" and args.user_speed is not None
            else args.character_speed if speaker == "character" and args.character_speed is not None
            else args.speed
        )
        pcm = tts(
            client, text,
            voice=voice_map[speaker],
            model=args.model,
            instructions=instructions_map[speaker],
            speed=speed,
        )
        if speaker == "character" and character_fx is not None:
            pcm = apply_fx(pcm, character_fx)
        pcm_segments.append(pcm)
        prev_speaker = speaker

    full_pcm = b"".join(pcm_segments)
    save_wav(full_pcm, output_path)

    duration_s = len(full_pcm) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)
    print(f"\nSaved: {output_path}  ({duration_s:.1f}s, {len(full_pcm) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
