"""
director_agent/beat_compression.py

Shared helper for compressing remaining beats into a single closing
instruction, ranked by importance. Lifted from the time-constrained
`critical`/`final` pacing logic in User-Study/server.py (~lines 471-497),
factored out so the lenient director's "jump to end" / "summarize to end"
actions can reuse it without duplicating the ranking/formatting logic.
"""

_IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}


def beat_lines(beats: list, from_idx: int) -> list[str]:
    """Return the beats from from_idx onward, sorted by importance
    (high first), formatted as "- name [IMPORTANCE]: goal" lines.
    """
    remaining = sorted(
        beats[from_idx:],
        key=lambda b: _IMPORTANCE_RANK.get(b.get("importance", "medium"), 1),
    )
    return [
        f"- {b['name']} [{b.get('importance', 'medium').upper()}]: {b['goal']}"
        for b in remaining
    ]


def closing_instruction(beats: list, from_idx: int, recap: str = "") -> str:
    """Build a director_instruction that closes out all remaining beats
    in one response. HIGH beats must be narrated, MEDIUM compressed to
    one sentence, LOW can be skipped.

    `recap` is an optional short lead-in (e.g. an acknowledgment of the
    user's request to skip/summarize) prepended before the beat list.
    """
    lead = f"{recap.strip()}\n\n" if recap.strip() else ""
    return (
        f"{lead}FINAL RESPONSE — close the story now. "
        "Cover ALL remaining beats. HIGH must be narrated, MEDIUM one sentence, LOW can skip.\n"
        + "\n".join(beat_lines(beats, from_idx))
    )
