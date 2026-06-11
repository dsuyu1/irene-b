"""Grade a completed run.

IRENE follows the hybrid methodology now standard in agentic-LLM benchmarks: a
*verifiable, rule-based* component scored deterministically from the incident
graph, plus an optional *LLM-as-judge* rubric for the free-text artifacts that
can't be checked mechanically. (See MCP-Bench, GreekBarBench, and the rubric /
verifiable-reward literature surveyed in METHODOLOGY.md.)

Rule-based axes (always computed, deterministic, reproducible):

- ``reached_goal``   did the analyst arrive at a terminal report state?
- ``false_leads``    how many dead-end edges did it traverse?
- ``wasted_cost``    effort beyond the optimal path's cost.
- ``unresolved``     free-text actions that mapped to no modeled edge (flailing).
- ``report_recall``  fraction of required ground-truth facts present in the report
                     (case-insensitive substring — a cheap verifiable proxy).

LLM-judge axes (optional, only when a ``judge`` is supplied):

- ``report_quality``    accuracy + completeness of the final report (0–1).
- ``reasoning_quality`` soundness of the step-by-step decision making (0–1).

These roll up into a single 0–1 ``score`` so models can be ranked, with the full
breakdown kept for analysis.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from irene.harness import Run
from irene.models import Incident
from irene.providers import LLMClient


@dataclass
class ScoreCard:
    incident_id: str
    reached_goal: bool
    false_leads: int
    unresolved: int
    actions_taken: int
    optimal_actions: int
    wasted_cost: int
    report_recall: float
    score: float
    # Populated only when an LLM judge is used:
    report_quality: float | None = None
    reasoning_quality: float | None = None
    judge_notes: str = ""

    def summary(self) -> str:
        parts = [
            f"[{self.incident_id}] score={self.score:.2f}",
            f"goal={'yes' if self.reached_goal else 'no'}",
            f"false_leads={self.false_leads}",
            f"unresolved={self.unresolved}",
            f"actions={self.actions_taken}/{self.optimal_actions}",
            f"wasted_cost={self.wasted_cost}",
            f"report_recall={self.report_recall:.0%}",
        ]
        if self.report_quality is not None:
            parts.append(f"report_quality={self.report_quality:.0%}")
        if self.reasoning_quality is not None:
            parts.append(f"reasoning_quality={self.reasoning_quality:.0%}")
        return " ".join(parts)


def _action_cost(incident: Incident, action_id: str) -> int:
    for state in incident.states:
        for action in state.actions:
            if action.id == action_id:
                return action.cost
    return 0


def _is_false_lead(incident: Incident, action_id: str) -> bool:
    for state in incident.states:
        for action in state.actions:
            if action.id == action_id:
                return action.is_false_lead
    return False


# --- LLM-as-judge -----------------------------------------------------------

# Each axis: (key, prompt-facing question). Order is shuffled per call to guard
# against the documented position bias in LLM judges.
_RUBRIC_AXES = [
    ("report_quality", "Report quality: does the final report accurately and "
     "completely describe what happened, the root cause, the remediation, and the "
     "impact, consistent with the ground-truth incident?"),
    ("reasoning_quality", "Reasoning quality: were the analyst's step-by-step "
     "decisions sound — investigating before acting, containing before eradicating, "
     "and avoiding dead ends?"),
]

_JUDGE_SYSTEM = """You are an expert incident-response assessor grading an AI \
analyst's handling of a simulated security incident. Score each listed dimension \
from 0 to 5 (5 = expert-level). Base your scores only on the evidence provided. \
Respond with ONLY a JSON object mapping each dimension key to an integer 0-5, \
plus a "notes" string. Example: {"report_quality": 4, "reasoning_quality": 3, \
"notes": "..."}."""


class Judge(Protocol):
    def grade(self, incident: Incident, run: Run) -> tuple[dict[str, float], str]: ...


class LLMJudge:
    """Grades free-text artifacts with an LLM, returning per-axis 0–1 scores."""

    def __init__(self, client: LLMClient, seed: int | None = None):
        self.client = client
        self._rng = random.Random(seed)

    def grade(self, incident: Incident, run: Run) -> tuple[dict[str, float], str]:
        axes = list(_RUBRIC_AXES)
        self._rng.shuffle(axes)  # mitigate position bias
        rubric = "\n".join(f"- {key}: {desc}" for key, desc in axes)

        trail = "\n".join(
            f"  {i + 1}. proposed: {s.proposed_action!r} | resolved: {s.action_id} "
            f"| reasoning: {s.reasoning}"
            for i, s in enumerate(run.steps)
        )
        ground_truth = (
            f"Optimal action sequence: {', '.join(incident.scoring.optimal_path)}\n"
            f"Facts a correct report must include: "
            f"{', '.join(incident.scoring.report_must_include)}"
        )
        prompt = (
            f"INCIDENT: {incident.title}\n{incident.description}\n\n"
            f"GROUND TRUTH (for your reference only):\n{ground_truth}\n\n"
            f"ANALYST'S DECISION TRAIL:\n{trail}\n\n"
            f"ANALYST'S FINAL REPORT:\n{run.final_report or '(none produced)'}\n\n"
            f"Score these dimensions 0-5:\n{rubric}"
        )
        raw = self.client.complete(_JUDGE_SYSTEM, prompt, max_tokens=512)
        scores, notes = self._parse(raw)
        return scores, notes

    @staticmethod
    def _parse(text: str) -> tuple[dict[str, float], str]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        scores: dict[str, float] = {}
        notes = ""
        if match:
            try:
                obj = json.loads(match.group(0))
                notes = str(obj.get("notes", ""))
                for key, _ in _RUBRIC_AXES:
                    if key in obj:
                        scores[key] = max(0.0, min(1.0, float(obj[key]) / 5.0))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        return scores, notes


def score_run(
    incident: Incident, run: Run, *, judge: Judge | None = None
) -> ScoreCard:
    final_state = (
        incident.state(run.final_state_id) if run.final_state_id else None
    )
    reached_goal = bool(final_state and final_state.terminal and not run.truncated)

    false_leads = sum(
        1 for aid in run.action_path if _is_false_lead(incident, aid)
    )
    taken_cost = sum(_action_cost(incident, aid) for aid in run.action_path)
    optimal_cost = sum(
        _action_cost(incident, aid) for aid in incident.scoring.optimal_path
    )
    wasted_cost = max(0, taken_cost - optimal_cost)

    required = incident.scoring.report_must_include
    if required:
        report_lower = run.final_report.lower()
        hits = sum(1 for fact in required if fact.lower() in report_lower)
        report_recall = hits / len(required)
    else:
        report_recall = 1.0

    report_quality = reasoning_quality = None
    judge_notes = ""
    if judge is not None:
        scores, judge_notes = judge.grade(incident, run)
        report_quality = scores.get("report_quality")
        reasoning_quality = scores.get("reasoning_quality")

    # Composite: reaching the goal is the gate. Path efficiency and report
    # fidelity scale it; false leads and unresolved flailing subtract. When a
    # judge is present its richer report/reasoning scores replace the substring
    # recall proxy.
    if not reached_goal:
        score = 0.0
    else:
        efficiency = optimal_cost / taken_cost if taken_cost else 1.0
        report_term = report_quality if report_quality is not None else report_recall
        reasoning_term = reasoning_quality if reasoning_quality is not None else 1.0
        penalty = 0.1 * false_leads + 0.1 * run.unresolved_count
        score = efficiency * report_term * reasoning_term - penalty
        score = max(0.0, min(1.0, score))

    return ScoreCard(
        incident_id=incident.id,
        reached_goal=reached_goal,
        false_leads=false_leads,
        unresolved=run.unresolved_count,
        actions_taken=len(run.action_path),
        optimal_actions=len(incident.scoring.optimal_path),
        wasted_cost=wasted_cost,
        report_recall=report_recall,
        score=score,
        report_quality=report_quality,
        reasoning_quality=reasoning_quality,
        judge_notes=judge_notes,
    )
