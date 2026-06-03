"""
evaluation_agent/evaluation_prompts_time.py

Prompt templates for evaluating time-constrained story outputs.

Dimensions are scored 1–5 (not 1–10) because these outputs may be very short
and granular 10-point distinctions become unreliable under extreme compression.
"""


EVALUATE_TIME_CONSTRAINED_QUALITY_PROMPT = """
Review the following interactive AI character story transcript, which was generated
under a specific time budget. The story may be short, compressed, or incomplete
because of that constraint — factor this into your assessment appropriately.

Evaluate the story across these dimensions on a 1–5 scale:

- Descriptiveness (1-5):
  5 = rich sensory detail, interiority, setting texture; 1 = bare or absent.

- Beat Fidelity (1-5):
  Does each scene honor the *intent* of its story beat — not just surface action?
  5 = every scene realizes the beat goal; 1 = scenes ignore or contradict the beats.

- Transition Quality (1-5):
  Are scene breaks abrupt (just stopping) or motivated (natural narrative shift)?
  5 = smooth and purposeful transitions; 1 = jarring cuts or mid-sentence endings.

- Character Voice (1-5):
  Does the character sound consistently in-voice, or does compression flatten the
  tone into generic narration?
  5 = distinct, consistent, personality-rich; 1 = flat or generic.

- Three-Act Balance (1-5):
  Given the time budget, does the story maintain a beginning, middle, and end?
  5 = clear three-act shape preserved; 1 = one-act fragment with no arc.

- Setup/Payoff Preservation (1-5):
  Are planted story elements still resolved? (N/A → 3 if no setups present.)
  5 = all setups paid off; 1 = setups planted but never resolved.

- Emotional Arc (1-5):
  Does the emotional journey of the story still track? Can we feel a shift in
  mood or stakes across the output?
  5 = clear emotional progression; 1 = flat or emotionally incoherent.

- Overall (1-5):
  Holistic quality given the constraints.

Provide a brief assessment (3–6 sentences), then output scores in this exact format:

Descriptiveness: (score) / 5
Beat Fidelity: (score) / 5
Transition Quality: (score) / 5
Character Voice: (score) / 5
Three-Act Balance: (score) / 5
Setup/Payoff Preservation: (score) / 5
Emotional Arc: (score) / 5
Overall: (score) / 5

[Character and Story Context]
{character_profile}

[Story Transcript]
{story}

[Assessment]
""".strip()


EVALUATE_TIME_CONSTRAINED_AB_PROMPT = """
You will compare two story transcripts generated under different time budgets
by the same AI character system.

Compare them across these dimensions and choose which is better (A, B, or Same):

- Descriptiveness: richness of sensory detail, interiority, and setting
- Beat Fidelity: how faithfully each scene realizes its story beat goal
- Transition Quality: how smoothly scene breaks are handled
- Character Voice: consistency and distinctiveness of the character's tone
- Narrative Completeness: how much of the story arc is covered
- Emotional Arc: whether a clear emotional progression is present
- Overall: holistic quality

Give a concise comparative assessment, then conclude with:

Descriptiveness: [A or B or Same]
Beat Fidelity: [A or B or Same]
Transition Quality: [A or B or Same]
Character Voice: [A or B or Same]
Narrative Completeness: [A or B or Same]
Emotional Arc: [A or B or Same]
Overall: [A or B or Same]

[Character and Story Context]
{character_profile}

[Story A — Time Budget: {label_a}]
{story_a}

[Story B — Time Budget: {label_b}]
{story_b}

[Assessment]
""".strip()


TIME_CONSTRAINED_DIMENSIONS = [
    "Descriptiveness",
    "Beat Fidelity",
    "Transition Quality",
    "Character Voice",
    "Three-Act Balance",
    "Setup/Payoff Preservation",
    "Emotional Arc",
    "Overall",
]

TIME_CONSTRAINED_AB_DIMENSIONS = [
    "Descriptiveness",
    "Beat Fidelity",
    "Transition Quality",
    "Character Voice",
    "Narrative Completeness",
    "Emotional Arc",
    "Overall",
]
