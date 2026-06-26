# Auto-Run + Auto-Eval Harness — Design

**Date:** 2026-06-25
**Status:** Approved
**Takehome:** Pretty Good AI voice-bot tester

## Goal

Turn the working call bridge (#6) into a test harness: drive each of the 12
scenarios as an AI "patient" calling the target clinic bot, capture a two-speaker
transcript, judge it against per-scenario pass criteria with an LLM, and emit a
report. This is the graded product, not the call plumbing.

## Non-goals (anti-overengineering boundary)

- No database — flat files only.
- No web dashboard / UI.
- No parallel call orchestration — scenarios run one at a time.
- No retry/flake logic beyond a manual re-run.
- No separate STT step — transcript comes from OpenAI Realtime events.

## Architecture

```
scenarios.py (registry)        main.py (bridge, per-call)         judge.py
  Scenario{id,                   - inject scenario prompt            - read transcript
    patient_prompt,              - bridge audio (existing)          - LLM judge vs
    pass_criteria}               - capture transcript events          pass_criteria
        |                        - write transcript JSON            - return verdict
        v                              |                                  |
  run_suite.py  ── places call ───────-+                                  |
        |                              transcripts/<scenario>_<sid>.json  |
        +─────────────── after call ends ─────────> judge ───────────────+
                                                          |
                                                          v
                                              reports/<run_ts>.md + .json
```

### Components

**1. Scenario registry — `scenarios.py`**
Port `scenarios.md` into structured data. Each entry:
```python
@dataclass
class Scenario:
    id: str            # "01-happy-path"
    title: str
    patient_prompt: str  # full instructions for our PATIENT bot
    pass_criteria: str   # the "Pass:" line, used by the judge
```
`SCENARIOS: list[Scenario]`. `scenarios.md` stays as human-readable source of truth.

**2. Transcript capture — in `main.py`**
- Enable input transcription in `configure_realtime`:
  `audio.input.transcription = {"model": "gpt-4o-mini-transcribe"}`.
- Scenario prompt is selected per call (not hardcoded). Mechanism: runner passes
  the scenario id to Twilio as a query param on the `/voice` URL
  (`?scenario=01-happy-path`); Twilio echoes custom params, and `/voice` injects
  the id into the `<Stream>` URL so `/ws` receives it. `/ws` looks up the
  `Scenario` by id and uses its `patient_prompt`. Stateless, no globals, and works
  even if calls overlap.
- In `openai_to_twilio`, tap transcript events:
  - `response.output_audio_transcript.done` -> `{"role": "patient", "text": ...}`
  - `conversation.item.input_audio_transcription.completed` -> `{"role": "clinic", "text": ...}`
- On teardown, write `transcripts/<scenario_id>_<call_sid>.json`:
  ```json
  {"scenario_id": "...", "call_sid": "...", "turns": [{"role":"clinic","text":"..."}, ...]}
  ```

**3. Judge — `judge.py`**
`judge(scenario, transcript) -> Verdict`. One Chat Completions call (not Realtime).
Prompt: system = rubric instructions; user = pass_criteria + formatted transcript.
Ask for JSON:
```json
{"pass": true, "reasoning": "...", "bugs": ["..."]}
```
`Verdict{scenario_id, pass, reasoning, bugs}`.

**4. Runner — `run_suite.py`**
For each scenario (or a `--only <id>` subset):
1. Set active scenario.
2. Place call via Twilio (reuse `call_me_test.py` logic), block until transcript
   file appears (poll) or timeout.
3. Judge the transcript.
4. Collect verdict.
After all: write `reports/<run_ts>.md` (table: scenario | pass/fail | bugs) and
`reports/<run_ts>.json` (raw verdicts).

## Data flow

scenario → patient_prompt into Realtime session → live call with clinic bot →
Realtime emits both-side transcripts → JSON transcript on hangup → judge reads
transcript + pass_criteria → verdict → aggregated report.

## Error handling

- Call fails to connect / no transcript before timeout → mark scenario `error`
  (distinct from fail), note in report, continue suite.
- Judge JSON parse failure → retry once, else `error`.
- Input transcription lag: judge reads full transcript post-call, so async lag is
  tolerated. Time alignment not required.

## Testing

- Unit: `judge.py` against 2-3 canned transcripts (one clear pass, one clear fail)
  — verifies rubric + JSON parsing without placing calls.
- Integration: run `run_suite.py --only 01-happy-path` end to end on one real call.
- Manual: full suite run, eyeball report against recordings.

## Maps to issues

- #7 Test case framework → scenario registry + runner + per-call prompt injection.
- #8 Transcript capture → Realtime transcript events → JSON files.
- #9 Auto-eval → judge + report.
- #1 Architecture doc → summarize this design.
