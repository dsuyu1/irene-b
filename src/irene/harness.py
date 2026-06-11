"""The benchmark engine.

The harness walks an analyst (a ``Policy``) through an incident graph while
enforcing the central rule of IRENE: at every step the policy is handed *only*
the current state's observation and available actions — never the rest of the
graph.

Analyst actions are **free text**. The policy describes what it wants to do in
natural language; a ``Resolver`` maps that onto one of the state's defined edges
(or reports no match). This keeps the scenario a deterministic, verifiable state
graph while letting the model behave like a real responder rather than picking
from a numbered menu. The full path — including unresolved attempts — is recorded
for the scorer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from irene.models import Incident, State
from irene.resolver import KeywordResolver, Resolution


@dataclass
class Step:
    """One decision made during a run."""

    state_id: str
    proposed_action: str  # the model's free-text action
    action_id: str | None  # the resolved edge, or None if unmatched
    reasoning: str = ""

    @property
    def resolved(self) -> bool:
        return self.action_id is not None


@dataclass
class Run:
    """The complete record of one analyst's pass through an incident."""

    incident_id: str
    steps: list[Step] = field(default_factory=list)
    final_state_id: str | None = None
    final_report: str = ""
    truncated: bool = False  # hit a limit without terminating

    @property
    def action_path(self) -> list[str]:
        """Ids of the edges actually traversed (unresolved attempts excluded)."""
        return [s.action_id for s in self.steps if s.action_id is not None]

    @property
    def unresolved_count(self) -> int:
        return sum(1 for s in self.steps if not s.resolved)


class Resolver(Protocol):
    def resolve(self, state: State, proposed: str) -> Resolution: ...


class Policy(Protocol):
    """An analyst. Describe the next action in natural language and explain why."""

    def act(self, state: State, history: list[Step]) -> tuple[str, str]:
        """Return ``(free_text_action, reasoning)``."""
        ...

    def write_report(self, history: list[Step]) -> str:
        """Produce the final incident report once a terminal state is reached."""
        ...


def run_incident(
    incident: Incident,
    policy: Policy,
    *,
    resolver: Resolver | None = None,
    max_steps: int = 50,
    max_unresolved: int = 5,
) -> Run:
    """Drive ``policy`` through ``incident`` and return the recorded run.

    ``resolver`` maps free-text actions to edges (defaults to the offline
    ``KeywordResolver``). A run ends when a terminal state is reached, the step
    budget is exhausted, or the policy proposes ``max_unresolved`` actions in a
    row that don't map to anything — a sign it's stuck.
    """
    resolver = resolver or KeywordResolver()
    run = Run(incident_id=incident.id)
    current = incident.state(incident.start_state)
    consecutive_unresolved = 0

    for _ in range(max_steps):
        if current.terminal:
            run.final_state_id = current.id
            run.final_report = policy.write_report(run.steps)
            return run

        proposed, reasoning = policy.act(current, run.steps)
        resolution = resolver.resolve(current, proposed)

        if not resolution.matched:
            run.steps.append(
                Step(current.id, proposed, None, reasoning)
            )
            consecutive_unresolved += 1
            if consecutive_unresolved >= max_unresolved:
                run.final_state_id = current.id
                run.truncated = True
                return run
            continue  # stay in the same state; let the policy try again

        consecutive_unresolved = 0
        action = resolution.action
        run.steps.append(Step(current.id, proposed, action.id, reasoning))
        current = incident.state(action.leads_to)

    run.final_state_id = current.id
    run.truncated = True
    return run
