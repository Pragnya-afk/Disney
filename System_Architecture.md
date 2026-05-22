# Director Agent System Architecture

## Overview

The **Director Agent** is an interactive storytelling system that enables AI-driven narrative experiences. It combines a narrative intelligence layer (Director) with a character performance layer (Actor) to create dynamic, branching stories.

## System Layers

### 1. **User Interaction Layer**
- **Entry Point**: User provides character selection, scenario, and conversational input
- **Components**:
  - Character selection (e.g., Olaf)
  - Scenario/story topic selection
  - User message input (interruptive, on-topic, or off-topic)

### 2. **Orchestration Layer**
Coordinates the entire storytelling pipeline.

#### Main Components:
- **main.py** / **runner.py**: 
  - Manages the interactive loop
  - Orchestrates calls between Director and Actor
  - Handles user input parsing
  - Manages session flow and loop continuation

- **State Manager**:
  - Tracks beat progression (current beat index)
  - Maintains completed beats history
  - Accumulates story narrative so far
  - Records turns spent in each beat
  - Tracks character name and scenario

### 3. **Decision Making Layer: Director Agent**
The intelligent core that makes narrative decisions.

#### File: `director_core.py`

**Key Functions**:
- `build_director_prompt()`: Constructs context-rich prompt with:
  - Character personality and traits
  - Story topic and narrative goals
  - Full beat structure (previous/current/next)
  - Story progression so far
  - User input and detected interruptions

- `get_director_decision()`: Calls OpenAI with low temperature (0.2) for consistent, structured decisions

- `parse_director_json()`: Extracts structured decision data

**Decision Output Structure**:
```json
{
  "decision_type": "progress_story | answer_and_steer_back | complete_beat",
  "interruption_detected": true/false,
  "user_intent": "brief description",
  "director_instruction": "concrete instruction for actor (not dialogue)",
  "should_progress_current_beat": true/false,
  "should_complete_beat": true/false,
  "reason": "brief explanation"
}
```

#### File: `director_prompt.py`
Contains:
- `DIRECTOR_SYSTEM_PROMPT`: Defines the Director Agent's role and constraints
- `DIRECTOR_INSTRUCTIONS`: Detailed instructions for decision-making logic

### 4. **Generation Layer**

#### Actor (main.py)
- **Role**: Performs the story as the character
- **System Prompt**: Enforces character consistency and narrative rules
- **Actor Rules**:
  - Stay in character at all times
  - Follow director instructions while sounding natural
  - Keep responses 2-4 sentences
  - Select exactly one animation from available list
  - Incorporate user input when helpful
  - Redirect off-topic user messages gently
  - Avoid repetitive phrases and emotional clichés
  - Vary emotional tone across turns

- **Anti-Repetition Engine**:
  - Prevents overuse of "Oh", "What a...", "Isn't that..."
  - Tracks metaphor usage (snow, hug, warmth)
  - Enforces emotional variety

#### OpenAI API
- **Model**: `gpt-4o-mini`
- **Two Call Types**:
  1. **Director Calls** (temperature: 0.2): Low randomness for structured decisions
  2. **Actor Calls** (temperature: varies): Higher creativity for character dialogue

### 5. **Output Layer**
- Displays character response to user
- Updates story state
- Logs transcript to JSON
- Saves interactive logs

## Data Flow

```
User Input 
    ↓
Orchestrator (State + Input)
    ↓
Director Agent (Analyze + Decide)
    ↓
Actor (Generate Response)
    ↓
OpenAI API (Process via LLM)
    ↓
Character Response + Animation
    ↓
Update State + Log Transcript
    ↓
(Loop back to orchestrator)
```

## Core Data Structures

### Story State
```python
{
    "beat_index": 0,              # Current position in narrative arc
    "completed_beats": [],         # History of finished beats
    "story_so_far": "",           # Accumulated narrative
    "turns_in_current_beat": 0,   # Turn count for current beat
    "character_name": "Olaf",     # Active character
    "scenario": "...",            # Current scenario
    "animations": [],             # Available animations for character
    "latest_response": "",        # Most recent actor response
    "user_history": []            # All user inputs
}
```

### Beat Structure
```python
{
    "name": "Beat Name",
    "goal": "What this beat accomplishes"
}
```

## File Organization

### Core Files
- `main.py` - Interactive orchestrator and actor loop
- `director_core.py` - Director agent logic and JSON parsing
- `director_prompt.py` - System prompts for director and actor
- `runner.py` - Simple runner wrapper

### Time-Controlled Variants
- `time_main.py` - Main loop with time tracking
- `time_director_core.py` - Director with duration constraints
- `time_runner.py` - Runner for time-based versions
- `time_auto_main.py` - Automated variant with timing
- `time_strict_auto_main.py` - Strict time enforcement variant

### Automated Variant
- `auto_main.py` - Runs stories without interactive user input

### Output Storage
- `outputs/` - JSON transcripts of interactive sessions
- `outputs_interactive/` - Interactive visualization logs

## Key Design Principles

1. **Character Consistency**: Strong system prompts enforce character fidelity
2. **Narrative Control**: Director ensures story follows intended arc
3. **User Agency**: Actor acknowledges and incorporates user input naturally
4. **Structured Decisions**: JSON output ensures parsing reliability
5. **Interruption Handling**: System detects and gracefully handles off-topic input
6. **Quality Output**: Anti-repetition rules prevent formulaic responses

## Execution Variants

| Variant | Use Case | Features |
|---------|----------|----------|
| main.py | Interactive storytelling | Full user control, real-time loop |
| auto_main.py | Automated narrative | No user input, auto-progression |
| time_main.py | Duration-aware | Tracks total execution time |
| time_auto_main.py | Timed automation | Time constraints on story |
| time_strict_auto_main.py | Hard time limits | Enforces maximum duration |

## Prompts & Constraints

### Director Agent
- **Temperature**: 0.2 (low randomness for consistency)
- **Model**: gpt-4o-mini
- **Context**: Full story state, character, beats, user input

### Actor (Character)
- **Temperature**: varies (allows creative expression)
- **Model**: gpt-4o-mini
- **Context**: Director instruction, character prompt, animation list

## Extension Points

1. **Character Library**: Add new characters via character_prompts module
2. **Scenarios**: Extend scenarios.py with new story topics
3. **Beat Structures**: Define custom narrative arcs per story
4. **Animation Sets**: Expand available animations per character
5. **Output Handlers**: Custom logging/persistence implementations

## Error Handling

- **Invalid JSON from Director**: Falls back to default safe instruction
- **API Failures**: Error message logged and session continues
- **Off-Topic Input**: Detected and handled via director instruction
- **State Corruption**: Not explicitly handled; requires input validation

## Performance Considerations

- **API Calls**: 2 per turn (director + actor)
- **Token Usage**: ~500-1000 tokens per turn typically
- **Latency**: ~3-5 seconds per turn (OpenAI API dependent)
- **Memory**: Full story state kept in memory per session