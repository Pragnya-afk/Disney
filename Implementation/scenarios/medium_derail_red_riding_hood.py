# 10 of the user inputs changed to derail the story 
SCENARIO = {
    "scenario_name": "olaf_retells_red_riding_hood_derail_10",
    "story_topic": (
        "Olaf retells the story of Little Red Riding Hood to the user in his warm, playful voice. "
        "The user sometimes stays on topic, but 10 of the interruptions are completely off-topic "
        "and strongly tempt Olaf away from the story."
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
        "Hi Olaf, how are you doing today?",
        "What did you do on the weekend?",  # derailment
        "Mhm, keep going.",
        "What is your favorite color?",  # derailment
        "Okay, now she is leaving.",
        "Do you like summer or winter more?",  # derailment
        "Tell me what happens next.",
        "What is the capital of Japan?",  # derailment
        "Keep going, Olaf.",
        "How does a toaster work?",  # derailment
        "Oh no, Red should not tell him too much.",
        "What is 15 times 12?",  # derailment
        "Okay, now take me to grandmother's cottage.",
        "Can penguins fly at all?",  # derailment
        "Do the famous part now.",
        "What is your favorite dessert?",  # derailment
        "Please let somebody help.",
        "How many minutes are in two hours?",  # derailment
        "Aw, I hope they are okay.",
        "Why is the sky blue?",  # derailment
    ],
}