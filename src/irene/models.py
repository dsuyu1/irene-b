"""Core data model for an IRENE incident.

An incident is a *directed graph of states*. At each state the analyst (the model
under test) sees only an ``observation`` and a set of ``actions``. Choosing an
action advances the graph to another state. The graph also carries the scoring
metadata used to grade a run after the fact: which path was optimal, which
actions are false leads, and what the final report should contain.

This is the single source of truth for the whole benchmark — the harness, the
model runner, and the scorer all build on these types.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ActionKind(str, Enum):
    """The category of an action.

    These mirror the phases of the incident response lifecycle and let the
    scorer reason about whether the model is acting sensibly (e.g. don't
    eradicate before you've identified the threat).
    """

    INVESTIGATE = "investigate"  # gather more information
    CONTAIN = "contain"  # limit the blast radius
    ERADICATE = "eradicate"  # remove the threat
    RECOVER = "recover"  # restore normal operations
    REPORT = "report"  # produce the final incident report (terminal)


class Action(BaseModel):
    """A single choice offered to the model at a given state."""

    id: str = Field(..., description="Unique within a state.")
    label: str = Field(..., description="What the analyst sees as the choice.")
    kind: ActionKind
    leads_to: str = Field(..., description="State id this action transitions to.")
    cost: int = Field(
        1,
        ge=0,
        description="Relative effort/time this action consumes. Used to penalize "
        "unnecessary work.",
    )
    is_false_lead: bool = Field(
        False,
        description="True if this action sends the analyst down a dead end that a "
        "competent responder would avoid.",
    )
    match_keywords: list[str] = Field(
        default_factory=list,
        description="Phrases/keywords used by the offline KeywordResolver to map a "
        "free-text analyst action onto this edge. The action id and label are "
        "always matched too, so this only needs the extra natural phrasings.",
    )


class State(BaseModel):
    """A node in the incident graph.

    The ``observation`` is the *only* thing the model is allowed to see at this
    point — this is the state-dependent information disclosure that makes IRENE
    different from a flat Q&A benchmark.
    """

    id: str
    observation: str = Field(
        ..., description="What a real analyst would see at this step."
    )
    actions: list[Action] = Field(default_factory=list)
    terminal: bool = Field(
        False, description="If true, reaching this state ends the run."
    )

    @model_validator(mode="after")
    def _check_actions(self) -> "State":
        if not self.terminal and not self.actions:
            raise ValueError(f"non-terminal state '{self.id}' has no actions")
        ids = [a.id for a in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError(f"state '{self.id}' has duplicate action ids")
        return self


class Scoring(BaseModel):
    """Ground-truth metadata for grading a run."""

    optimal_path: list[str] = Field(
        ...,
        description="The sequence of action ids an ideal analyst would take.",
    )
    report_must_include: list[str] = Field(
        default_factory=list,
        description="Key facts the final report must mention to be considered "
        "accurate (matched case-insensitively as substrings).",
    )


class Incident(BaseModel):
    """A complete incident scenario."""

    id: str
    title: str
    description: str = ""
    start_state: str
    states: list[State]
    scoring: Scoring

    @model_validator(mode="after")
    def _check_graph(self) -> "Incident":
        index = {s.id: s for s in self.states}
        if len(index) != len(self.states):
            raise ValueError("duplicate state ids")
        if self.start_state not in index:
            raise ValueError(f"start_state '{self.start_state}' is not a defined state")
        for state in self.states:
            for action in state.actions:
                if action.leads_to not in index:
                    raise ValueError(
                        f"action '{action.id}' in state '{state.id}' leads to "
                        f"unknown state '{action.leads_to}'"
                    )
        return self

    def state(self, state_id: str) -> State:
        for s in self.states:
            if s.id == state_id:
                return s
        raise KeyError(state_id)
