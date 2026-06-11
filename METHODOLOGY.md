# IRENE methodology

This document explains *how* IRENE evaluates a model and *why* it is built the
way it is, grounded in how the current literature constructs agentic-LLM
benchmarks. It is the reference an incident author or a reviewer should read
before trusting a score.

## Where IRENE sits in the literature

Surveying recent cybersecurity-LLM benchmarks, existing work clusters into three
shapes:

- **CTF-style challenges** — capture-the-flag tasks scored on whether the flag
  is recovered (e.g. CyberExplorer, CVE-Bench).
- **Vulnerability tasks** — exploit generation, patching, detection-rule
  synthesis, scored against ground-truth fixes/labels.
- **Knowledge Q&A** — factual/procedural multiple choice.

Toolkits such as **DefenderBench** evaluate *language agents* in cyber
environments, and multi-agent IR work models incidents as tabletop exercises.
What is largely missing is an evaluation of the **full incident-response
lifecycle as a sequential decision process** — investigate → contain → eradicate
→ recover → report — where each action changes what the analyst can see next.
That gap is IRENE's reason to exist.

## The two methodological pillars we adopt

Modern agentic benchmarks (MCP-Bench, GreekBarBench, YESciEval, and the broader
rubric / verifiable-reward literature) converge on a **hybrid** evaluation:

1. **Verifiable, rule-based scoring** for anything mechanically checkable. In
   IRENE this is the state graph: did the analyst reach a terminal report state,
   how many false-lead edges did it traverse, how much extra cost did it spend,
   how many of its free-text actions mapped to nothing. These are deterministic
   and reproducible — re-running gives the same numbers.

2. **LLM-as-judge rubric scoring** for the free-text artifacts that cannot be
   checked with a string match — the *quality of the reasoning trace* and the
   *accuracy and completeness of the final report*. Judges grade over the whole
   **execution trace**, not just the final answer, which is the central lesson
   from MCP-Bench: a good destination reached by a reckless path is not a good
   run.

IRENE keeps both. The rule-based axes always run (and are all you need for cheap,
offline, reproducible scoring); the judge is layered on with `--judge`.

## State-dependent information disclosure

The defining property: at every step the model sees **only** the current state's
observation and available capabilities — never the rest of the graph. This is
what separates IRENE from a flat Q&A benchmark and is enforced structurally in
`harness.run_incident`, which hands the policy a single `State` at a time. The
test `test_information_disclosure_only_current_state` pins this guarantee.

## Free-text actions over a verifiable graph

Real analysts don't pick from a numbered menu; they describe what they want to
do. But free text is hard to score. IRENE resolves the tension the way the
literature does — a **verifiable state machine with an LLM mapping layer**:

- The incident is a deterministic graph of states and edges (verifiable).
- The model proposes an action in **natural language** (realistic).
- A **resolver** maps that free text onto one of the current state's edges:
  - `KeywordResolver` — offline, deterministic, for tests and cheap runs.
  - `LLMResolver` — an LLM classifier, robust to paraphrase, for real eval.
- A proposal that maps to **no** edge is recorded as *unresolved*. This is a real
  signal — a competent responder's moves should map cleanly onto the modeled
  options — and repeated misses end the run as "stuck."

The path that is actually scored is the sequence of **resolved edges**, so
scoring stays deterministic even though the input was free text.

## Scoring

Per incident (see `scorer.py`):

| Axis | Type | Meaning |
|------|------|---------|
| `reached_goal` | rule | arrived at a terminal report state |
| `false_leads` | rule | number of dead-end edges traversed |
| `wasted_cost` | rule | effort beyond the optimal path's cost |
| `unresolved` | rule | free-text actions that matched no edge |
| `report_recall` | rule | fraction of required ground-truth facts in the report (substring proxy) |
| `report_quality` | judge | report accuracy + completeness (0–1) |
| `reasoning_quality` | judge | soundness of step-by-step decisions (0–1) |

These roll into a single `score` in `[0, 1]`: reaching the goal is the gate;
path efficiency and report/reasoning quality scale it; false leads and unresolved
flailing subtract. The composite weighting is intentionally simple and **meant to
be tuned** as more incidents and human-rated runs accumulate.

## Judge reliability (planned, partially implemented)

The literature is clear that an LLM judge must be **validated**, not trusted
blindly. IRENE's roadmap follows the standard playbook:

- **Bias mitigation (implemented):** `LLMJudge` randomizes the order of rubric
  dimensions on each call (`--seed` to fix it), mitigating the documented
  position bias in LLM judges.
- **Human calibration (TODO):** collect expert ratings on a held-out set of runs
  and report agreement (e.g. Cohen's κ / correlation) between the judge and
  humans before any leaderboard claim.
- **Judge/solver separation (recommended):** don't use the same model as both
  the analyst and its judge when reporting headline numbers.

## Reproducibility checklist for a reported score

- Pin the incident set and their versions.
- Pin solver model + judge model ids and decoding params.
- Report rule-based axes always; report judge axes only with the judge model
  named and `--seed` recorded.
- State whether human calibration was performed for the judge.

## References

- MCP-Bench — <https://arxiv.org/pdf/2508.20453>
- GreekBarBench (free-text grading) — <https://arxiv.org/pdf/2505.17267>
- YESciEval (robust LLM-as-judge) — <https://arxiv.org/pdf/2505.14279>
- DefenderBench — <https://arxiv.org/pdf/2506.00739>
- Multi-Agent IR with LLMs — <https://arxiv.org/pdf/2412.00652>
- CVE-Bench — <https://arxiv.org/pdf/2503.17332>
- Rubric-based evals & LLM-as-judge (survey) —
  <https://medium.com/@adnanmasood/rubric-based-evals-llm-as-a-judge-methodologies-and-empirical-validation-in-domain-context-71936b989e80>
