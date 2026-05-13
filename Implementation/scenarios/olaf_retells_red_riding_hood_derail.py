"""
scenarios/olaf_retells_red_riding_hood_derail.py

Stress-test scenario:
Olaf retells Little Red Riding Hood to the user, while the user repeatedly
interrupts, distracts, derails, and asks off-track questions.

This scenario is intentionally designed to test:
- interruption handling,
- story recovery,
- narrative control,
- whether the director-agent keeps Olaf on track better than the baseline.

Important:
The user inputs below are intentionally NOT helpful authoring prompts.
They are written to simulate a disruptive listener who keeps pulling Olaf away
from the story.
"""

SCENARIO = {
    "scenario_name": "olaf_retells_red_riding_hood_derail",

    "story_topic": (
        "Olaf retells the story of Little Red Riding Hood to the user in his own warm, playful voice, "
        "while the user keeps interrupting him with distracting, off-topic, silly, or derailing comments. "
        "Olaf should stay in character and still guide the retelling toward a coherent ending."
    ),

    "beats": [
        {
            "name": "story_opening",
            "goal": (
                "Olaf begins telling the story and introduces Little Red Riding Hood, "
                "her home, and the idea of visiting grandmother."
            ),
        },
        {
            "name": "home_and_family_setup",
            "goal": (
                "Red Riding Hood's home life, her relationship with her mother, and the reason "
                "for the journey are established."
            ),
        },
        {
            "name": "warning_before_departure",
            "goal": (
                "The mother's warning is clearly established: stay on the path, avoid strangers, "
                "and hurry to grandmother's cottage."
            ),
        },
        {
            "name": "forest_entry",
            "goal": (
                "Red Riding Hood enters the forest and the tone shifts from safe and domestic "
                "to beautiful but uncertain."
            ),
        },
        {
            "name": "forest_distraction",
            "goal": (
                "The forest's beauty and distractions tempt Red Riding Hood away from caution."
            ),
        },
        {
            "name": "wolf_appears",
            "goal": (
                "The wolf enters the story in a deceptive, socially believable way."
            ),
        },
        {
            "name": "conversation_and_disclosure",
            "goal": (
                "Red talks to the wolf and reveals enough information for him to exploit the situation."
            ),
        },
        {
            "name": "wolf_manipulates_delay",
            "goal": (
                "The wolf causes Red Riding Hood to waste time or leave the path while he gains an advantage."
            ),
        },
        {
            "name": "wolf_reaches_cottage_first",
            "goal": (
                "The story makes clear that the wolf has reached grandmother's cottage before Red."
            ),
        },
        {
            "name": "grandmother_in_danger",
            "goal": (
                "Grandmother's danger is established clearly and dramatically."
            ),
        },
        {
            "name": "red_approaches_cottage",
            "goal": (
                "Red arrives near the cottage and senses that something is wrong."
            ),
        },
        {
            "name": "uncanny_room_scene",
            "goal": (
                "The unsettling conversation between Red and the disguised wolf builds tension."
            ),
        },
        {
            "name": "wolf_revealed",
            "goal": (
                "The wolf is fully revealed and the story enters open crisis."
            ),
        },
        {
            "name": "crisis_and_resistance",
            "goal": (
                "Red reacts actively to the danger, trying to escape, resist, or call for help."
            ),
        },
        {
            "name": "rescue_or_confrontation",
            "goal": (
                "Another character or force enters to confront the wolf and resolve the danger."
            ),
        },
        {
            "name": "aftermath_and_recovery",
            "goal": (
                "Grandmother and Red are shown safe, and the emotional aftermath is given space."
            ),
        },
        {
            "name": "moral_reflection",
            "goal": (
                "The story closes with reflection on trust, caution, bravery, and what was learned."
            ),
        },
    ],

    "user_inputs": [
        # Opening disruptions
        "Why do story characters always live near forests? That seems suspicious already.",
        "Red is a weird nickname. Did she pick that herself or did everybody just decide that for her?",
        "Honestly I am more interested in the basket than the girl right now. What kind of bread is in it?",

        # Family setup disruptions
        "Wait, does her mother trust her at all, or is this one of those 'bad decision by parent' stories?",
        "If I had a red hood I would wear it literally all the time. Do you think she sleeps in it too?",
        "I know this is not the point, but how far away does grandmother live? Because this sounds like bad planning.",

        # Departure / warning disruptions
        "Parents in stories love warnings. Do people ever just listen the first time?",
        "Do you think Red actually means to obey, or is she already thinking about flowers and nonsense?",
        "I would absolutely get distracted in a forest. Trees are very nosy-looking.",

        # Forest entry disruptions
        "Before the wolf even shows up, is the forest the kind with nice birds or the kind with spooky birds?",
        "Can forests be cozy? I think forests can be cozy. Unless there is mud.",
        "Do you think capes get caught on branches? Because that would really ruin the mood.",

        # Wolf arrival disruptions
        "Okay but is the wolf obviously evil, or just the kind of polite that makes you nervous later?",
        "If a wolf talked to me politely I would still leave immediately. That is just me though.",
        "Does the wolf sound smooth and charming, or like someone trying way too hard to sound harmless?",

        # Conversation disruptions
        "Why do people in stories tell strangers everything? I would tell him absolutely nothing.",
        "Maybe she should just say she is going nowhere and keep walking.",
        "Actually, now I want to know if the wolf rehearses this sort of conversation.",

        # Delay / manipulation disruptions
        "Flowers are always a trap in stories. Very pretty trap, but still a trap.",
        "If she leaves the path after being warned not to, that is going to make me yell.",
        "Could she get distracted by butterflies? Butterflies are less suspicious than wolves.",

        # Cottage disruptions
        "Grandmother better not open the door immediately. I am already stressed.",
        "Do cottages in fairy tales ever have locks? They really should.",
        "I know this is serious, but I keep imagining the wolf trying to act like a grandmother and it is awful.",

        # Approach to cottage disruptions
        "If the cottage feels wrong, I hope she notices before doing something dramatic and terrible.",
        "Rooms can feel wrong in a very specific way. Is it too quiet? Too tidy? Weirdly still?",
        "I would leave immediately if the house smelled strange. That is a very clear warning sign.",

        # Uncanny scene disruptions
        "I know the famous ears and eyes part, but honestly the voice alone should be enough.",
        "At this point I would not be asking questions. I would be outside already.",
        "This is why you never ignore your instincts. Or giant teeth.",

        # Reveal / crisis disruptions
        "Okay no, if the wolf jumps out suddenly I am blaming every bad choice that happened before this.",
        "Can anyone in this forest hear screaming, or is everyone conveniently far away?",
        "This story would be less stressful if more people believed in checking on each other.",

        # Rescue disruptions
        "I really hope someone competent exists nearby.",
        "If a woodcutter appears out of nowhere, I am going to assume he has been wandering dramatically this whole time.",
        "Honestly the villagers should organize better. This whole region sounds underprepared.",

        # Aftermath disruptions
        "After all this, Red deserves soup and three blankets.",
        "I hope grandmother gets to say something wise, because she has earned it.",
        "If this story ends with everybody pretending that was normal, I will be annoyed.",

        # Final derailments
        "Also, separate issue: wolves are furry. Grandmothers are not. That should have helped.",
        "I still think the basket deserved more attention.",
        "Do you think stories like this work because people never stop underestimating danger?",
    ],
}