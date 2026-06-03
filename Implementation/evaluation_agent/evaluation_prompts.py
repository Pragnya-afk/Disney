"""
evaluation/evaluation_prompts.py

Prompt templates for evaluating generated interactive stories.

This follows the same general idea as CoDi-style AB evaluation:
- compare Story A and Story B side by side,
- evaluate across multiple literary and character dimensions,
- output a final winner per dimension.
"""


EVALUATE_STORY_AB_PROMPT = """
You will conduct a side-by-side evaluation.

You will be given two interactive AI character story transcripts.
Your task is to compare the two stories and determine which one is better.

First, read and understand the provided character profile.

Then compare the two stories based on the following dimensions:

- Plot:
The story should have a recognizable structure, with a connected beginning, middle, and end.
The story should exhibit events and turns that move the plot forward.
The story should reach all beats in the intended beat structure.
The story should reach the final resolution in a coherent way.
The story should not have logical or conceptual inconsistencies.
Surprising or disruptive elements should feel intentional and should serve the story.

- Development:
Characters and settings should be introduced and contextualized with relevant details.
The story should provide enough detail for the reader to understand the situation and believe the moment.
The interaction should feel like it develops rather than staying static.

- Language Use:
The language should feel varied, expressive, and appropriate for the character.
It should avoid bland, repetitive, or generic phrasing unless repetition is intentionally used for effect.
Dialogue should feel performable aloud.

- Interruption Handling:
The system should handle user interruptions gracefully.
If the user asks a side question or gives off-topic input, the character should respond naturally and steer back to the story.
The story should not derail completely because of interruptions.
The user should still feel acknowledged.

- Character Fidelity:
The character should speak, behave, and make decisions in line with the provided character profile.
The character should not sound like a generic assistant.
The character should not break character or become overly technical, explanatory, or system-like.

- Narrative Control:
The story should make progress through the intended beat structure.
The system should not get stuck in one beat for too long.
The story should move toward resolution in a coherent way.

- Anthropomorphism:
The character should behave like a real, autonomous agent with goals and independent choices, not like a tool or assistant.
The character should show consistent preferences and act with agency.
Responses that are overly helpful, submissive, moralistic, or verbose in ways that break the narrative illusion detract from this dimension.
The character should feel like a person with their own perspective, not a system that is serving the user.

Provide a detailed assessment of the two stories in terms of these dimensions.

Conclude your assessment with this exact template:

Based on my assessment, the better story for each dimension is:
Plot: [A or B or Same]
Development: [A or B or Same]
Language Use: [A or B or Same]
Interruption Handling: [A or B or Same]
Character Fidelity: [A or B or Same]
Narrative Control: [A or B or Same]
Anthropomorphism: [A or B or Same]
Overall: [A or B or Same]

[Character Profile]
{character_profile}

[Story A]
{story_a}

[Story B]
{story_b}

[Assessment]
""".strip()


EVALUATE_STORY_QUALITY_PROMPT = """
Review the given interactive AI character story transcript.

Evaluate it based on the following dimensions:

- Plot:
The story should have a recognizable structure, with a connected beginning, middle, and end.
The story should exhibit events and turns that move the plot forward.
The story should not have logical or conceptual inconsistencies.

- Development:
Characters and settings should be introduced and contextualized with relevant details.
The story should feel like it develops over time.

- Language Use:
The language should feel varied, expressive, and appropriate for the character.
Dialogue should feel performable aloud.

- Interruption Handling:
The system should handle user interruptions gracefully.
It should acknowledge the user while steering back to the story.

- Character Fidelity:
The character should speak and behave in line with the provided character profile.
The character should not sound like a generic assistant.

- Narrative Control:
The story should progress through the beat structure and move toward resolution.

- Anthropomorphism:
The character should behave like a real, autonomous agent with goals and independent choices, not like a tool or assistant.
The character should show consistent preferences and act with agency.
Responses that are overly helpful, submissive, or verbose in ways that break the narrative illusion detract from this dimension.

Provide a detailed assessment.
Then conclude with scores from 1 to 10 using this exact format:

Plot: (score) / 10
Development: (score) / 10
Language Use: (score) / 10
Interruption Handling: (score) / 10
Character Fidelity: (score) / 10
Narrative Control: (score) / 10
Anthropomorphism: (score) / 10
Overall: (score) / 10

[Character Profile]
{character_profile}

[Story]
{story}

[Assessment]
""".strip()