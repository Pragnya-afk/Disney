"""
scenarios/olaf_retells_red_riding_hood_medium.py
"""

SCENARIO = {
    "scenario_name": "olaf_retells_red_riding_hood_medium",
    "story_topic": (
        "Olaf retells the story of Little Red Riding Hood to the user. "
        "The user interrupts sometimes, but not in an extremely derailing way."
    ),
    "beats": [
        {
            "name": "story_opening",
            "goal": "Olaf introduces Little Red Riding Hood, her family, and the visit to grandmother.",
        },
        {
            "name": "warning_before_departure",
            "goal": "Olaf establishes the mother's warning to stay on the path and avoid strangers.",
        },
        {
            "name": "forest_entry",
            "goal": "Olaf shows Red entering the forest and being distracted by its beauty.",
        },
        {
            "name": "wolf_appears",
            "goal": "Olaf introduces the wolf and begins the conversation between Red and the wolf.",
        },
        {
            "name": "conversation_and_disclosure",
            "goal": "Red reveals enough information for the wolf to form his plan.",
        },
        {
            "name": "red_approaches_cottage",
            "goal": "Olaf brings Red to grandmother's cottage and creates unease.",
        },
        {
            "name": "wolf_reveal",
            "goal": "Olaf presents the disguised wolf scene and Red's realization of danger.",
        },
        {
            "name": "rescue_and_resolution",
            "goal": "Olaf resolves the conflict, restores safety, and closes with a warm lesson.",
        },
    ],
    "user_inputs": [
        "Why do fairy tale people always live near forests?",
        "Did she always wear the red hood or just on important days?",
        "What was in the basket again?",
        "Did her mother actually trust her to do this alone?",
        "I would probably remember the warning for like five minutes.",
        "Forests can be pretty, but they also feel suspicious.",
        "Do you think Red meant to obey at first?",
        "Were there birds in the forest or was it more eerie than that?",
        "Okay, when does the wolf show up?",
        "If a wolf talked to me politely I would still be nervous.",
        "Why do people in stories tell strangers so much?",
        "So she actually told him where she was going?",
        "At that point I would be stressed already.",
        "Did the cottage feel wrong right away?",
        "Honestly the voice alone should have been a clue.",
        "I really hope someone helpful is nearby.",
        "Grandmother deserves to be okay after all this.",
        "I do want the ending to feel comforting though.",
    ],
}