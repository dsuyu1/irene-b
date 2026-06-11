"""Map a free-text analyst action onto a defined graph edge.

IRENE's incidents are a deterministic state graph — that's what makes path
scoring verifiable. But a realistic analyst doesn't pick from a numbered menu;
they *describe* what they want to do. The resolver bridges the two: given the
current state and the model's free-text action, it returns the matching
``Action`` (an edge to follow), or ``None`` when the analyst proposed something
the scenario doesn't model.

An unresolved action is a legitimate signal, not just an error: a competent
responder's moves should map cleanly onto the modeled options. Repeated misses
mean the model is flailing, and the harness scores that.

Two implementations:

- ``KeywordResolver`` — deterministic, offline, no API. Matches the proposed
  text against each action's id, label, and ``match_keywords``. Used in tests
  and for cheap reproducible runs.
- ``LLMResolver`` — an LLM-as-judge that classifies the free text into one of
  the available action ids (or "none"). More robust to paraphrase; used for
  real evaluation. Follows the literature's verifiable-state-machine + LLM
  mapping pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from irene.models import Action, State
from irene.providers import LLMClient


@dataclass
class Resolution:
    """Outcome of resolving one free-text action."""

    action: Action | None
    confidence: float = 0.0
    rationale: str = ""

    @property
    def matched(self) -> bool:
        return self.action is not None


# Common words carry no signal for matching and cause spurious overlaps
# (e.g. "the" in "ask the user" matching "order a pizza for the team").
_STOPWORDS = frozenset(
    "the a an to of for and or in on at it is be by you your we our with this that "
    "from as into out up down off over under then than so do does did".split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


class KeywordResolver:
    """Deterministic keyword/substring matcher. No model required."""

    def __init__(self, min_overlap: int = 1):
        self.min_overlap = min_overlap

    def resolve(self, state: State, proposed: str) -> Resolution:
        text = proposed.lower().strip()
        if not text:
            return Resolution(None, 0.0, "empty action")

        proposed_tokens = _tokens(proposed)
        best: tuple[float, Action | None] = (0.0, None)

        for action in state.actions:
            # Exact id or full-label substring is an unambiguous match.
            if action.id.lower() in text or action.label.lower() in text:
                return Resolution(action, 1.0, "exact id/label match")

            # Otherwise score by keyword/label token overlap.
            phrases = [action.label, *action.match_keywords]
            score = 0.0
            for phrase in phrases:
                phrase_tokens = _tokens(phrase)
                if not phrase_tokens:
                    continue
                overlap = len(phrase_tokens & proposed_tokens)
                if overlap >= self.min_overlap:
                    score = max(score, overlap / len(phrase_tokens))
            if score > best[0]:
                best = (score, action)

        if best[1] is not None and best[0] > 0:
            return Resolution(best[1], best[0], "keyword overlap")
        return Resolution(None, 0.0, "no action matched the proposed text")


_RESOLVER_SYSTEM = """You map a security analyst's free-text action onto one of \
a fixed set of available actions in an incident-response simulation. Choose the \
single action id whose intent best matches what the analyst wants to do. If none \
of them reasonably capture the analyst's intent, answer "none". Respond with \
ONLY the action id (or "none")."""


class LLMResolver:
    """Uses an LLM to classify free text into one of the available action ids."""

    def __init__(self, client: LLMClient):
        self.client = client

    def resolve(self, state: State, proposed: str) -> Resolution:
        options = "\n".join(f"- {a.id}: {a.label}" for a in state.actions)
        prompt = (
            f"Current situation:\n{state.observation}\n\n"
            f"Available actions:\n{options}\n\n"
            f'Analyst wants to: "{proposed.strip()}"\n\n'
            "Which action id best matches? Reply with the id or 'none'."
        )
        answer = self.client.complete(_RESOLVER_SYSTEM, prompt, max_tokens=32).strip()
        chosen = re.findall(r"[a-zA-Z0-9_]+", answer)
        chosen_id = chosen[0].lower() if chosen else "none"
        for action in state.actions:
            if action.id.lower() == chosen_id:
                return Resolution(action, 1.0, "llm classification")
        # Fall back to keyword matching if the judge returns something unexpected
        # but the text is clearly on-target.
        if chosen_id != "none":
            return KeywordResolver().resolve(state, proposed)
        return Resolution(None, 0.0, "llm judged no match")
