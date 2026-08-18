"""
director_agent/lenient/consent.py

Deterministic two-turn (one-turn for "summarize") confirmation state machine
for the lenient director's irreversible actions: stop, jump-to-end,
summarize-to-end, and the "want to continue?" derailment nudge.

This module makes no LLM calls and trusts nothing the LLM says beyond the
`confirmation_response` classification of the user's reply. The actual
gating — how many affirmations are required, whether the pending request
survives an ambiguous reply — is pure code, mirroring the codebase's existing
pattern of not trusting LLM self-compliance for behaviour that must be exact
(see director_core.strip_banned_opener for the same philosophy).
"""

REQUIRED_CONFIRMS = {
    "stop": 2,
    "jump": 2,
    "summarize": 1,
    "continue": 1,
}

# decision_type the LLM emits to *initiate* each kind of pending confirmation.
_ASK_TRIGGER_DECISION_TYPES = {
    "request_stop_confirmation": "stop",
    "request_jump_confirmation": "jump",
    "request_continue_confirmation": "continue",
    # summarize has no separate "request_*" type — its only decision_type
    # doubles as both the initiating ask and (once confirmed) the executed
    # action; which one it means is disambiguated by whether a "summarize"
    # confirmation is already pending.
    "summarize_to_end": "summarize",
}

# decision_type re-asserted while a confirmation of this kind is pending
# (re-ask) — deliberately the same "request_*" type regardless of how many
# times we've re-asked, so the actor prompt stays predictable.
_ASK_DECISION_TYPE = {
    "stop": "request_stop_confirmation",
    "jump": "request_jump_confirmation",
    "summarize": "summarize_to_end",
    "continue": "request_continue_confirmation",
}

# decision_type assigned once a pending confirmation is actually executed.
_EXECUTE_DECISION_TYPE = {
    "stop": "stop_confirmed",
    "jump": "jump_to_end",
    "summarize": "summarize_to_end",
    "continue": "progress_story",  # "continuing" just means resuming the story
}

# Escalating prompt text shown to the user while a confirmation is pending —
# index by (confirm_count so far), clamped to the last entry.
_ASK_TEXT = {
    "stop": [
        "Just to check — would you like me to stop the story here?",
        "Really stop the story now? Say yes again and I will.",
    ],
    "jump": [
        "Would you like to skip ahead to the ending?",
        "Just to be sure — jump straight to the ending now?",
    ],
    "summarize": [
        "Would you like me to wrap up and summarize the rest of the story now?",
    ],
    "continue": [
        "It sounds like we've wandered off from the story — would you like to keep going with it?",
    ],
}


def new_consent_state() -> dict:
    """The at-rest consent state: nothing pending."""
    return {"pending": None, "confirm_count": 0, "required_confirms": 2, "asked_at_turn": None}


def apply_confirmation(consent: dict, decision: dict, turn_count: int | None = None) -> dict:
    """Advance the consent state machine by one turn's director decision.

    `decision` is the raw dict returned by the lenient director LLM — must
    contain `decision_type` and `confirmation_response`
    ("affirm"|"decline"|"unrelated"|"none"). The LLM's own decision_type is
    trusted only to *detect a new request* when nothing is pending; once a
    confirmation is pending, only confirmation_response drives the outcome.

    Returns:
        {
          "action": "none" | "ask" | "execute" | "cancelled",
          "kind": "stop" | "jump" | "summarize" | "continue" | None,
          "consent": <new consent dict>,
          "decision_type": <decision_type to actually act on>,
          "prompt_text": <text to surface to the user, only for "ask">,
        }
    """
    pending = consent.get("pending")
    decision_type = decision.get("decision_type", "")
    confirmation_response = decision.get("confirmation_response", "none")

    if pending is None:
        kind = _ASK_TRIGGER_DECISION_TYPES.get(decision_type)
        if not kind:
            return {"action": "none", "kind": None, "consent": dict(consent), "decision_type": decision_type}

        new_consent = {
            "pending": kind,
            "confirm_count": 0,
            "required_confirms": REQUIRED_CONFIRMS[kind],
            "asked_at_turn": turn_count,
        }
        return {
            "action": "ask",
            "kind": kind,
            "consent": new_consent,
            "decision_type": _ASK_DECISION_TYPE[kind],
            "prompt_text": _ASK_TEXT[kind][0],
        }

    kind = pending
    required = consent.get("required_confirms", REQUIRED_CONFIRMS[kind])

    if confirmation_response == "affirm":
        confirm_count = consent.get("confirm_count", 0) + 1
        if confirm_count >= required:
            return {
                "action": "execute",
                "kind": kind,
                "consent": new_consent_state(),
                "decision_type": _EXECUTE_DECISION_TYPE[kind],
            }
        new_consent = dict(consent)
        new_consent["confirm_count"] = confirm_count
        text_options = _ASK_TEXT[kind]
        text = text_options[min(confirm_count, len(text_options) - 1)]
        return {
            "action": "ask",
            "kind": kind,
            "consent": new_consent,
            "decision_type": _ASK_DECISION_TYPE[kind],
            "prompt_text": text,
        }

    # "decline" or "unrelated" (or missing/malformed) — cancel and resume.
    return {
        "action": "cancelled",
        "kind": kind,
        "consent": new_consent_state(),
        "decision_type": "progress_story",
    }
