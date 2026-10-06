"""
director_agent/story_summary.py

Keeps the director's view of `story_so_far` bounded in length by periodically
folding older turns into a short prose summary, while the raw, unmutated
`story_so_far` keeps feeding the actor's own tail/transcript needs elsewhere.
"""

import re
from openai import OpenAI


# Same turn-splitting convention as director_core.last_character_opener —
# turns are split on "<character_name>: "/"User: " prefixes, not on every
# newline, since a single turn's body can itself contain blank lines.
def _turn_split_re(character_name: str) -> re.Pattern:
    return re.compile(rf"\n(?=(?:{re.escape(character_name)}|User): )")


DEFAULT_KEEP_LAST_TURNS = 6
DEFAULT_RESUMMARIZE_EVERY_TURNS = 4
MAX_SUMMARY_WORDS = 200


def _prefix_re(character_name: str) -> re.Pattern:
    return re.compile(rf"^(?:{re.escape(character_name)}|User):\s*", re.IGNORECASE)


SUMMARY_SYSTEM_PROMPT = (
    "You compress the earlier portion of an interactive children's story into a short, "
    "neutral prose recap for an internal story-tracking system. You are not a storyteller "
    "and your output is never shown to the end user directly."
)


def split_turns(story_so_far: str, character_name: str = "Olaf") -> list[str]:
    """Split story_so_far into individual '<character>: ...' / 'User: ...' turns."""
    text = story_so_far or ""
    if not text.strip():
        return []
    return [p for p in _turn_split_re(character_name).split(text) if p.strip()]


def build_director_story_context(
    state: dict,
    keep_last_turns: int = DEFAULT_KEEP_LAST_TURNS,
    character_name: str = "Olaf",
) -> str:
    """Story context for the director: summary of older turns plus recent turns."""
    story_so_far = state.get("story_so_far", "") or ""
    story_summary = (state.get("story_summary") or "").strip()
    if not story_summary:
        return story_so_far

    turns = split_turns(story_so_far, character_name)
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
    character_name: str = "Olaf",
) -> bool:
    """Decide whether enough new content has accumulated to (re)summarize."""
    story_so_far = state.get("story_so_far", "") or ""
    total_turns = split_turns(story_so_far, character_name)
    if len(total_turns) <= keep_last_turns:
        return False  # everything is still within the verbatim window

    summarized_chars = state.get("summarized_chars", 0) or 0
    new_turns = split_turns(story_so_far[summarized_chars:], character_name)

    if not (state.get("story_summary") or "").strip():
        return True  # first activation — there's already foldable content
    return len(new_turns) >= resummarize_every


def _sanitize_summary(text: str, character_name: str = "Olaf") -> str:
    """Strip any stray "<character_name>: "/"User: " line prefixes from summarizer output.

    last_character_opener() scans story context for exactly those prefixes,
    so summary text must never accidentally introduce one.
    """
    if not text:
        return ""
    prefix_re = _prefix_re(character_name)
    lines = []
    for line in text.splitlines():
        stripped = prefix_re.sub("", line.strip(), count=1).strip()
        if stripped:
            lines.append(stripped)
    return " ".join(lines).strip()


def _build_summary_prompt(
    story_topic: str, previous_summary: str, fold_text: str, character_name: str = "Olaf"
) -> str:
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
- Do NOT start any line with "{character_name}:" or "User:" — describe events, don't quote turns.
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
    character_name: str = "Olaf",
) -> dict:
    """Fold everything except the last keep_last_turns turns into story_summary."""
    story_so_far = state.get("story_so_far", "") or ""
    turns = split_turns(story_so_far, character_name)

    if len(turns) <= keep_last_turns:
        return {
            "story_summary": state.get("story_summary", "") or "",
            "summarized_chars": state.get("summarized_chars", 0) or 0,
        }

    to_fold = turns[:-keep_last_turns]
    fold_text = "\n".join(t.strip() for t in to_fold)
    previous_summary = state.get("story_summary", "") or ""

    prompt = _build_summary_prompt(story_topic, previous_summary, fold_text, character_name)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    summary = _sanitize_summary(raw, character_name)

    return {
        "story_summary": summary,
        "summarized_chars": len(story_so_far),
    }
