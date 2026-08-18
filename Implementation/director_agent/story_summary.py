"""
director_agent/story_summary.py

Keeps the director's view of `story_so_far` bounded in length by periodically
folding older turns into a short prose summary, while the raw, unmutated
`story_so_far` keeps feeding the actor's own tail/transcript needs elsewhere.
"""

import re
from openai import OpenAI

# Same turn-splitting convention as director_core.last_character_opener —
# turns are split on "Olaf: "/"User: " prefixes, not on every newline, since
# a single turn's body can itself contain blank lines.
_TURN_SPLIT_RE = re.compile(r"\n(?=(?:Olaf|User): )")

DEFAULT_KEEP_LAST_TURNS = 6
DEFAULT_RESUMMARIZE_EVERY_TURNS = 4
MAX_SUMMARY_WORDS = 200

_PREFIX_RE = re.compile(r"^(?:Olaf|User):\s*", re.IGNORECASE)

SUMMARY_SYSTEM_PROMPT = (
    "You compress the earlier portion of an interactive children's story into a short, "
    "neutral prose recap for an internal story-tracking system. You are not a storyteller "
    "and your output is never shown to the end user directly."
)


def split_turns(story_so_far: str) -> list[str]:
    """Split story_so_far into individual "Olaf: ..."/"User: ..." turns.

    Returns each turn as the exact substring produced by the split (not
    re-stripped), so callers that need to slice story_so_far by turn
    boundaries can do so consistently.
    """
    text = story_so_far or ""
    if not text.strip():
        return []
    return [p for p in _TURN_SPLIT_RE.split(text) if p.strip()]


def build_director_story_context(state: dict, keep_last_turns: int = DEFAULT_KEEP_LAST_TURNS) -> str:
    """Return the story context to hand to the director prompt.

    Once a story_summary exists, this returns a bounded "summary + recent
    verbatim turns" block instead of the full story_so_far. Before that
    (no summary yet), it returns story_so_far unchanged — the raw log
    itself is never mutated by this module.
    """
    story_so_far = state.get("story_so_far", "") or ""
    story_summary = (state.get("story_summary") or "").strip()
    if not story_summary:
        return story_so_far

    turns = split_turns(story_so_far)
    recent = turns[-keep_last_turns:] if keep_last_turns else turns
    recent_text = "\n".join(t.strip() for t in recent)

    return (
        f"## Summary Of Earlier Story\n{story_summary}\n\n"
        f"## Recent Turns (verbatim)\n{recent_text}"
    ).strip()


def needs_resummarize(
    state: dict,
    keep_last_turns: int = DEFAULT_KEEP_LAST_TURNS,
    resummarize_every: int = DEFAULT_RESUMMARIZE_EVERY_TURNS,
) -> bool:
    """Decide whether enough new content has accumulated to (re)summarize.

    summarized_chars is a snapshot of len(story_so_far) taken the last time
    update_summary ran, so slicing story_so_far from that offset gives
    exactly the turns added since then.
    """
    story_so_far = state.get("story_so_far", "") or ""
    total_turns = split_turns(story_so_far)
    if len(total_turns) <= keep_last_turns:
        return False  # everything is still within the verbatim window

    summarized_chars = state.get("summarized_chars", 0) or 0
    new_turns = split_turns(story_so_far[summarized_chars:])

    if not (state.get("story_summary") or "").strip():
        return True  # first activation — there's already foldable content
    return len(new_turns) >= resummarize_every


def _sanitize_summary(text: str) -> str:
    """Strip any stray "Olaf: "/"User: " line prefixes from summarizer output.

    last_character_opener() scans story context for exactly those prefixes,
    so summary text must never accidentally introduce one.
    """
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        stripped = _PREFIX_RE.sub("", line.strip(), count=1).strip()
        if stripped:
            lines.append(stripped)
    return " ".join(lines).strip()


def _build_summary_prompt(story_topic: str, previous_summary: str, fold_text: str) -> str:
    previous_block = previous_summary.strip() or "(none yet — this is the first summary)"
    return f"""
Story topic: {story_topic}

Existing summary of everything before this new material:
{previous_block}

New story turns to fold into the summary (do not lose plot-relevant details):
{fold_text}

Write an updated summary that combines the existing summary with the new turns.

Rules:
- Third-person prose only, no dialogue transcription.
- Do NOT start any line with "Olaf:" or "User:" — describe events, don't quote turns.
- Keep it under {MAX_SUMMARY_WORDS} words.
- Preserve concrete plot points (what happened, what was decided, what the user asked for)
  over incidental phrasing.
- Output only the summary text, nothing else.
""".strip()


def update_summary(
    client: OpenAI,
    model: str,
    state: dict,
    story_topic: str,
    keep_last_turns: int = DEFAULT_KEEP_LAST_TURNS,
) -> dict:
    """Fold everything except the last keep_last_turns turns into story_summary.

    Returns {"story_summary": str, "summarized_chars": int}. Callers are
    responsible for writing these back onto their own state under a lock —
    this function does not mutate `state`.
    """
    story_so_far = state.get("story_so_far", "") or ""
    turns = split_turns(story_so_far)

    if len(turns) <= keep_last_turns:
        return {
            "story_summary": state.get("story_summary", "") or "",
            "summarized_chars": state.get("summarized_chars", 0) or 0,
        }

    to_fold = turns[:-keep_last_turns]
    fold_text = "\n".join(t.strip() for t in to_fold)
    previous_summary = state.get("story_summary", "") or ""

    prompt = _build_summary_prompt(story_topic, previous_summary, fold_text)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    summary = _sanitize_summary(raw)

    return {
        "story_summary": summary,
        "summarized_chars": len(story_so_far),
    }
