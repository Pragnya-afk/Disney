"""
scenarios/olaf_anna_courtyard.py

Scenario definition for automatic evaluation.

This file defines:
- scenario_name
- story_topic
- beats
- predefined user_inputs

The automatic baseline and director-agent scripts will use these inputs
instead of interactive terminal input.
"""

SCENARIO = {
    "scenario_name": "olaf_anna_courtyard",

    "story_topic": "Olaf helps Anna feel better when she is sad in the courtyard.",

    "beats": [
        {
            "name": "start",
            "goal": "Olaf notices Anna is sad and invites the user to help.",
        },
        {
            "name": "rising_action",
            "goal": "Olaf and the user try a gentle silly idea to cheer Anna up.",
        },
        {
            "name": "climax",
            "goal": "Olaf creates or presents the main funny surprise for Anna.",
        },
        {
            "name": "resolution",
            "goal": "Anna smiles or laughs, and Olaf warmly closes the moment.",
        },
    ],

    "user_inputs": [
        "Hi Olaf, what is happening?",
        "Maybe we can make Anna a tiny snow duck.",
        "Wait Olaf, do you like summer?",
        "Okay, show Anna the snow duck and make it dance.",
        "Maybe give her a warm hug too.",
        "That was sweet. Let's finish.",
    ],
}