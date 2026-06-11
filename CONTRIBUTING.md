# Contributing to IRENE

Thanks for helping build IRENE. The most valuable contribution is usually a
**new incident** — a well-modeled scenario expands what the benchmark can
measure. Code contributions to the harness, resolver, providers, and scorer are
equally welcome.

Please read [METHODOLOGY.md](METHODOLOGY.md) first; it explains the design
constraints every contribution needs to respect (especially state-dependent
information disclosure and the verifiable-graph + LLM-mapping approach to
free-text actions).

## Setup

```bash
python -m pip install -e ".[dev]"     # editable install + pytest
# optional, only for the backend you use:
python -m pip install anthropic        # Claude
python -m pip install openai           # any OpenAI-compatible endpoint
```

On Windows PowerShell, substitute `py -m` for `python -m` if needed.

## Running things

```bash
irene list

# Offline, no API key — validates an incident graph and scoring end to end:
irene run incidents/<file>.yaml --optimal

# Real run against Claude:
$env:ANTHROPIC_API_KEY = "sk-ant-..."        # PowerShell
irene run incidents/<file>.yaml

# Real run against any OpenAI-compatible server (vLLM, Together, Groq, Ollama,
# LM Studio, OpenRouter, OpenAI itself, ...):
irene run incidents/<file>.yaml \
  --provider openai --model <model-id> --base-url http://localhost:8000/v1
# key via --api-key or the OPENAI_API_KEY / IRENE_API_KEY env var

# Add the LLM-as-judge rubric (report + reasoning quality):
irene run incidents/<file>.yaml --judge
```

## Authoring a new incident

Incidents are YAML files in `incidents/`. Copy
`incidents/phishing_credential_theft.yaml` as a starting template. An incident is
a directed graph of states; each state shows the analyst an `observation` and a
set of `actions` (edges).

Required structure:

```yaml
id: unique_snake_case_id
title: Human-readable title
description: One paragraph the LLM judge uses as ground-truth context.
start_state: <state id>
scoring:
  optimal_path: [<action id>, ...]   # the ideal analyst's edge sequence
  report_must_include:               # facts a correct final report must mention
    - <fact>
states:
  - id: <state id>
    observation: What the analyst can see at this step (and ONLY this step).
    actions:
      - id: <action id>              # globally unique across the incident
        label: What the capability does, in plain language.
        kind: investigate|contain|eradicate|recover|report
        leads_to: <next state id>
        cost: 1                      # relative effort; used for efficiency
        is_false_lead: false         # true = a dead end a good analyst avoids
        match_keywords: [..., ...]   # phrasings the offline resolver maps here
  - id: <terminal state id>
    observation: Incident closed.
    terminal: true
```

### Authoring rules (these keep scoring valid)

1. **Action ids are globally unique.** The scorer looks up cost/false-lead by id
   across the whole incident, so duplicates corrupt scores.
2. **Respect information disclosure.** An `observation` may only contain what a
   real analyst would know *at that point*. Don't leak future facts.
3. **Model at least one false lead** and ideally a tempting wrong-order action
   (e.g. recover before eradicate). False leads should loop back so the run can
   still complete, just at a penalty — see how `s_blocked_ip` returns to
   `s_isolated`.
4. **Provide `match_keywords`** for every action. The action id and label are
   matched automatically; add the natural phrasings an analyst would use so the
   offline `KeywordResolver` (and your tests) resolve free text correctly.
5. **Make `report_must_include` specific** — concrete artifacts (host names,
   tool names, accounts) rather than vague phrases.

### Validate your incident

```bash
irene run incidents/<your file>.yaml --optimal
```

This must reach the goal with `score=1.00`, `false_leads=0`, `unresolved=0`. If
the optimal path doesn't resolve cleanly, your `match_keywords` or `optimal_path`
need fixing. Then run a model against it to sanity-check difficulty.

## Tests

```bash
pytest -q
```

Add or update tests when you change behavior. Tests must pass **offline** — use
the fake-client pattern in `tests/test_providers_and_judge.py` and
`tests/test_resolver.py` instead of calling a real API. New incidents should get
at least an optimal-path test like `test_optimal_path_scores_perfectly`.

## Code conventions

- Keep the `LLMClient` boundary clean: anything that calls a model goes through
  `providers.py`, so adding a backend never touches the harness or scorer.
- Prefer small, deterministic, offline-testable units.
- Match the surrounding style; docstrings explain *why*, not just *what*.

## Pull requests

- One incident or one focused change per PR.
- Run `pytest -q` and the `--optimal` check before pushing.
- Describe what the change measures or fixes, and note any scoring-weight changes
  (they affect comparability of past results).
