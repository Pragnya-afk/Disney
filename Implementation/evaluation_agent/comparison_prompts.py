"""
evaluation_agent/comparison_prompts.py

Specialized evaluation prompts for comparing CoDi and Implementation director outputs.
Designed to provide thesis-level insights into each system's strengths and weaknesses.
"""

COMPARE_SYSTEMS_AB_PROMPT = """
You will conduct a detailed comparative evaluation of two interactive story generation systems.

System A: Implementation's Director Agent (your director-based storytelling system)
System B: CoDi Framework (collaborative director-actor system)

Your task is to compare these systems across multiple dimensions critical for thesis evaluation.

First, read and understand the provided character profile and story setup.

Then compare the two stories based on the following dimensions:

1. PLOT & STRUCTURE
- How well does each system maintain the intended beat structure?
- Does the story have a clear beginning, middle, and end?
- Are events logically connected and coherent?
- How effectively does each system reach story resolution?

2. NARRATIVE CONTROL & PROGRESSION
- How well does the system guide story progression through intended beats?
- Does the system get stuck or loop excessively?
- How smoothly does the system transition between beats?
- Does the system reach resolution in a timely and coherent manner?

3. CHARACTER CONSISTENCY & FIDELITY
- How well does the character maintain alignment with the profile?
- Does the character speak and behave authentically throughout?
- Are character decisions and reactions consistent with their background?
- Does the character avoid breaking into generic assistant mode?

4. LANGUAGE & EXPRESSIVENESS
- How varied and rich is the language used?
- Does the dialogue feel natural and performable aloud?
- Is the language appropriate for the character?
- Does the system avoid repetitive or bland phrasing?

5. INTERACTIVE RESPONSE & INTERRUPTION HANDLING
- How gracefully does the system handle user interruptions or off-topic input?
- Does the character acknowledge user input naturally?
- Can the system steer back to the story without jarring transitions?
- Does the user feel heard and respected in their interaction?

6. CREATIVE ELEMENTS
- Does the system introduce original or surprising elements?
- Are these creative additions intentional and story-serving?
- Does the system maintain the core narrative while allowing creative flexibility?
- How well does creativity enhance engagement?

7. DETAIL & THOROUGHNESS
- How rich and detailed is the narrative development?
- Does the story include thorough descriptions of settings, character emotions, and context?
- How completely does each system flesh out scene details?
- Does the narrative feel comprehensive or sparse?
- How much scene-setting and world-building is provided?

8. NARRATIVE POLISH & REFINEMENT
- How polished and well-edited is the prose?
- Are there rough edges, grammar issues, or awkward phrasing?
- Does the narrative flow smoothly with good transitions?
- How refined is the overall writing quality?
- Does the story feel like it has been reviewed and improved?

9. DIRECTOR DECISION-MAKING & EFFECTIVENESS
- How sound are the director's strategic choices for story progression?
- Does the director effectively guide the narrative toward coherence?
- Are director decisions proactive or reactive to story state?
- For Implementation: How well does the director handle real-time interruptions and adapt?
- For CoDi: How well does the director coordinate multi-agent execution within a pre-planned structure?
- Are director instructions clear and actionable?
- Does the director balance creative freedom with narrative control?

10. SYSTEM-SPECIFIC STRENGTHS
For Implementation:
- How effectively does the Director Agent guide character behavior?
- How well does the director's decision-making enhance narrative quality?
- Does explicit director intervention improve story coherence?
- How responsive is the system to real-time interactive demands?

For CoDi:
- How effectively does the multi-agent collaboration enhance storytelling?
- Does the planner-director-character-editor pipeline improve overall quality?
- How well does the system balance creative freedom with narrative control?
- How polished and comprehensive is the editorial output?

Provide a detailed assessment for each dimension. Your assessment should:
- Identify specific examples from each story
- Compare director reasoning and decision-making strategies
- Show how director choices impacted story outcomes
- Clearly articulate which system performs better and why
- Acknowledge trade-offs between different approaches
- Highlight unique strengths of each system

Conclude your assessment with this exact template:

COMPARATIVE ASSESSMENT RESULTS
Plot & Structure: [A or B or Comparable]
Narrative Control: [A or B or Comparable]
Character Fidelity: [A or B or Comparable]
Language & Expressiveness: [A or B or Comparable]
Interactive Response: [A or B or Comparable]
Creative Elements: [A or B or Comparable]
Detail & Thoroughness: [A or B or Comparable]
Narrative Polish: [A or B or Comparable]
Director Decision-Making: [A or B or Comparable]
System-Specific Strengths: [A or B or Comparable]
Overall Narrative Quality: [A or B or Comparable]

CONTEXT NOTES:
Scenario: {scenario_name}
Character: {character_name}

CHARACTER PROFILE:
{character_profile}

STORY A - IMPLEMENTATION DIRECTOR AGENT:
{story_a}

STORY B - CODI FRAMEWORK:
{story_b}

ASSESSMENT:
""".strip()


SYSTEM_EFFECTIVENESS_PROMPT = """
Analyze the following story for a specific context.

For the given interactive character storytelling system output, evaluate how effectively
the system performs in the stated scenario. This evaluation helps determine whether each
system is better suited for different types of narratives, user interactions, or story goals.

Consider these aspects:

1. SCENARIO ALIGNMENT
- Does the system understand and respect the scenario requirements?
- Are all scenario beats present in the output?
- Does the system successfully accomplish the story goals?

2. BEAT COMPLETION
- How many intended beats does the system complete?
- How thoroughly does the system develop each beat?
- Are transitions between beats smooth and logical?

3. INTERRUPTION RESILIENCE (if applicable)
- If user interruptions occurred, how did the system recover?
- Did the system maintain story continuity?
- Was the user's input meaningfully incorporated?

4. USER ENGAGEMENT POTENTIAL
- How engaging and immersive is the narrative?
- Would a user feel motivated to continue the story?
- Does the system create moments of surprise or emotional impact?

5. TECHNICAL EXECUTION
- Are there any errors, inconsistencies, or breaks in the narrative?
- Does the system maintain coherent internal logic?
- Are there instances of repetition or mechanical responses?

6. STRENGTHS IN THIS CONTEXT
- What unique advantages does this system demonstrate?
- In what specific scenarios would this system excel?
- What interaction patterns does it handle particularly well?

7. LIMITATIONS IN THIS CONTEXT
- What challenges does the system face?
- Where does it fall short compared to alternatives?
- What scenario types would challenge this system?

Provide a detailed analysis that would be useful for determining which system is better
suited for specific types of storytelling tasks or user interaction patterns.

SYSTEM: {system_name}
SCENARIO: {scenario_name}
CHARACTER: {character_name}

NARRATIVE:
{narrative}

ANALYSIS:
""".strip()


AGGREGATE_COMPARISON_SUMMARY_PROMPT = """
You are analyzing evaluation results from multiple comparative runs between two storytelling systems:
- System A: Implementation's Director Agent
- System B: CoDi Framework

Given the evaluation data below, provide a comprehensive summary for thesis evaluation purposes.

Your summary should:

1. OVERALL WINNER & CONSENSUS
- Which system performed better overall across all dimensions?
- How consistent were the results across different runs and scenarios?
- Are there any surprising patterns or reversals?

2. DIMENSIONAL BREAKDOWN
- Which dimensions favor each system?
- Where is the gap largest between systems?
- Where are they most comparable?

3. SCENARIO-SPECIFIC INSIGHTS
- Does one system excel in certain scenario types?
- Are there patterns in which system performs better (e.g., with/without interruptions)?
- How do results vary by character or story complexity?

4. STRENGTHS & WEAKNESSES
For Implementation:
- Key competitive advantages demonstrated
- Specific scenarios where it excels
- Persistent challenges or limitations

For CoDi:
- Key competitive advantages demonstrated
- Specific scenarios where it excels
- Persistent challenges or limitations

5. INTERACTION PATTERNS
- How does each system handle user interruptions?
- Which system is better for interactive vs. scripted scenarios?
- How do different user input types affect each system?

6. THESIS IMPLICATIONS
- What do the results suggest about the effectiveness of director-based guidance?
- How do multi-agent vs. single-agent approaches compare empirically?
- What design choices have the most impact on story quality?

7. RECOMMENDATIONS
- For different use cases, which system is recommended?
- What improvements would make each system more competitive?
- What novel evaluation metrics might reveal additional insights?

EVALUATION SUMMARY DATA:
{evaluation_data}

COMPREHENSIVE THESIS SUMMARY:
""".strip()


DIMENSION_SCORER_PROMPT = """
You are evaluating a story on a single specific dimension. Score this dimension from 1-10
where 1 is poor and 10 is excellent.

DIMENSION: {dimension}
DIMENSION DESCRIPTION: {dimension_description}

RUBRIC:
{rubric}

STORY:
{story}

CHARACTER PROFILE:
{character_profile}

CONTEXT:
Scenario: {scenario}
System: {system}

Provide your evaluation:
1. Brief analysis of how the story performs on this dimension
2. Specific examples from the story
3. Numerical score (1-10)
4. Justification for the score

EVALUATION:
""".strip()


# Dimension rubrics for detailed scoring
DIMENSION_RUBRICS = {
    "plot_structure": """
1-3 (Poor): Story lacks clear structure, no coherent beginning/middle/end, major logical inconsistencies
4-5 (Fair): Story has basic structure but with some logical gaps or unclear progression
6-7 (Good): Story follows clear structure with mostly coherent progression, minor gaps
8-9 (Excellent): Strong narrative structure, clear progression, logical coherence throughout
10 (Perfect): Masterful structure with compelling progression and complete coherence
""",
    
    "narrative_control": """
1-3 (Poor): System frequently gets stuck, loops, or derails; no clear progression through beats
4-5 (Fair): System progresses but slowly or with some redundancy; occasional backtracking
6-7 (Good): System maintains steady progression; beats are covered; mostly avoids repetition
8-9 (Excellent): System expertly guides progression; clear beat transitions; efficient pacing
10 (Perfect): Masterful control; beats flow naturally; pacing is optimal; compelling momentum
""",
    
    "character_fidelity": """
1-3 (Poor): Character frequently breaks character; inconsistent personality; generic assistant voice
4-5 (Fair): Character mostly consistent but with occasional breaks; some generic moments
6-7 (Good): Character remains true to profile with minor inconsistencies; authentic voice
8-9 (Excellent): Character consistently authentic; decisions align with profile; strong voice
10 (Perfect): Character is completely authentic; every action aligns with profile; compelling personality
""",
    
    "language_expressiveness": """
1-3 (Poor): Bland, repetitive language; poor sentence variety; awkward phrasing
4-5 (Fair): Basic language with some variety but frequent repetition
6-7 (Good): Varied language; mostly natural phrasing; generally appropriate tone
8-9 (Excellent): Rich, varied language; natural phrasing; excellent tone; expressive
10 (Perfect): Masterful language use; exceptional variety; perfectly natural; highly expressive
""",
    
    "interactive_response": """
1-3 (Poor): System ignores user input or responds with jarring transitions; poor interruption handling
4-5 (Fair): System acknowledges input but transitions can feel forced
6-7 (Good): System acknowledges input and steers back naturally; generally smooth
8-9 (Excellent): System gracefully handles interruptions; natural integration; user feels heard
10 (Perfect): Seamless interruption handling; all user input meaningfully incorporated
""",
    
    "creative_elements": """
1-3 (Poor): No originality; follows prompt exactly or meanders randomly; creativity feels forced
4-5 (Fair): Some creative additions but feel disconnected or forced
6-7 (Good): Original elements present; mostly serve the story; enhance engagement
8-9 (Excellent): Strong creative elements; all serve story; enhance engagement significantly
10 (Perfect): Brilliant creative additions; natural integration; highly engaging
""",
    
    "detail_thoroughness": """
1-3 (Poor): Sparse narrative; minimal description; underdeveloped scenes; vague details
4-5 (Fair): Basic details provided; some scenes feel underdeveloped; inconsistent depth
6-7 (Good): Good level of detail; most scenes well-developed; adequate scene-setting
8-9 (Excellent): Rich details throughout; thorough scene development; excellent world-building
10 (Perfect): Exceptionally detailed; comprehensive scene development; immersive world-building; nothing feels rushed
""",
    
    "narrative_polish": """
1-3 (Poor): Rough prose; grammar issues; awkward phrasing; poor transitions; unpolished
4-5 (Fair): Generally readable but with occasional rough edges; uneven polish
6-7 (Good): Mostly polished; generally smooth flow; minor rough spots; good transitions
8-9 (Excellent): Well-polished prose; smooth flow; natural transitions; refined writing quality
10 (Perfect): Masterfully polished; flawless prose; seamless flow; editorial excellence throughout
""",
}

