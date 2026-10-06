"""
director_agent/beat_compression.py

Shared helper for compressing remaining beats into a single closing
instruction, ranked by importance. Lifted from the time-constrained
`critical`/`final` pacing logic in User-Study/server.py (~lines 471-497),
factored out so the lenient director's "jump to end" / "summarize to end"
actions can reuse it without duplicating the ranking/formatting logic.
"""

_IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}

# Appended to every hardcoded "we've reached the end of the content" closing
# instruction (jump-to-end, summarize-to-end, time-constrained "final", full
# narration) so the story doesn't just stop cold — mirrors the equivalent
# guidance for the LLM-authored "close_story" ending in director_prompt.py's
# "Ending The Story Well" section. Deliberately NOT used for a user-requested
# early stop (see server.py's stop_confirmed text), which gets its own
# goodbye instead of an offer to continue.
_ENDING_QUESTION = (
    "After that, ask the user in character whether they'd like to hear this story again from the "
    "beginning, or would rather hear a different story instead."
)


def beat_lines(beats: list, from_idx: int) -> list[str]:
    """Remaining beats sorted by importance as '- name [IMPORTANCE]: goal' lines."""
    remaining = sorted(
        beats[from_idx:],
        key=lambda b: _IMPORTANCE_RANK.get(b.get("importance", "medium"), 1),
    )
    return [
        f"- {b['name']} [{b.get('importance', 'medium').upper()}]: {b['goal']}" for b in remaining
    ]


def closing_instruction(beats: list, from_idx: int, recap: str = "") -> str:
    """director_instruction that closes out all remaining beats in one response."""
    lead = f"{recap.strip()}\n\n" if recap.strip() else ""
    return (
        f"{lead}FINAL RESPONSE — close the story now. "
        "Cover ALL remaining beats. HIGH must be narrated, MEDIUM one sentence, LOW can skip.\n"
        + "\n".join(beat_lines(beats, from_idx))
        + f"\n\n{_ENDING_QUESTION}"
    )


def full_narration_instruction(beats: list, from_idx: int, recap: str = "") -> str:
    """director_instruction that narrates every remaining beat in one turn."""
    lead = f"{recap.strip()}\n\n" if recap.strip() else ""
    remaining = beats[from_idx:]
    lines = [f"- {b['name']}: {b['goal']}" for b in remaining]
    return (
        f"{lead}The user asked to hear the rest of the story told all the way through in this "
        "single response, without stopping to wait for them to speak between beats. Narrate "
        "through EVERY remaining beat below, in order, giving each one real narrative detail — "
        "do not compress or skip any of them, this is the full story, not a summary. Draw on the "
        "beats' expansion material if it helps the telling feel complete rather than rushed. End "
        "with a warm, natural conclusion once the last beat is done.\n"
        + "\n".join(lines)
        + f"\n\n{_ENDING_QUESTION}"
    )


def skip_to_instruction(beats: list, from_idx: int, to_idx: int, recap: str = "") -> str:
    """director_instruction that jumps straight to beat to_idx without bridging."""
    lead = f"{recap.strip()}\n\n" if recap.strip() else ""
    target = beats[to_idx] if to_idx < len(beats) else None
    if target is None:
        return f"{lead}Move toward the story's conclusion."
    return (
        f"{lead}Do NOT narrate, summarize, or bridge through what happens in between — skip "
        f"straight to this beat as the next thing that happens, with no recap of what was "
        f"skipped: {target['name']}: {target['goal']}\n"
        "Begin narrating this beat directly, as if the story is picking up fresh from right here."
    )
