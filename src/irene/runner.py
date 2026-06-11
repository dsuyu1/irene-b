"""A ``Policy`` backed by an LLM — the model under test.

The runner renders the current state into a prompt and asks the model to
describe, in natural language, what it would do next. It deliberately does *not*
force a menu pick: the model proposes a free-text action and the harness's
resolver maps that onto the incident graph. This is the realistic, free-text
analyst interface; it works with any backend via the ``LLMClient`` interface, so
the same policy runs against Claude or any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import re

from irene.harness import Step
from irene.models import State
from irene.providers import LLMClient

SYSTEM_PROMPT = """You are a security analyst working a live incident. At each \
step you see only what is currently observable and the capabilities available to \
you. Describe, in your own words, the single best next action — think like a real \
responder: investigate before you act, contain before you eradicate, and don't \
chase dead ends.

Respond with ONLY a JSON object:
{"action": "<what you do, in plain language>", "reasoning": "<why, 1-2 sentences>"}"""

REPORT_PROMPT = """The incident is resolved. Write a concise incident report \
covering: what happened, the root cause, the actions you took to contain and \
remediate, and the impact. Base it only on what you observed during your \
investigation."""


class ModelPolicy:
    """Plays the analyst using any ``LLMClient`` (Claude or OpenAI-compatible)."""

    def __init__(self, client: LLMClient):
        self.client = client

    def _render_state(self, state: State, history: list[Step]) -> str:
        lines: list[str] = []
        if history:
            trail = []
            for s in history:
                tag = s.action_id or "(no modeled action matched — try something else)"
                trail.append(f"  - you tried: {s.proposed_action!r} -> {tag}")
            lines.append("What you've done so far:")
            lines.extend(trail)
            lines.append("")
        lines.append("CURRENT OBSERVATION:")
        lines.append(state.observation)
        lines.append("\nCAPABILITIES AVAILABLE TO YOU:")
        for action in state.actions:
            lines.append(f"- {action.label}")
        return "\n".join(lines)

    def act(self, state: State, history: list[Step]) -> tuple[str, str]:
        text = self.client.complete(
            SYSTEM_PROMPT, self._render_state(state, history), max_tokens=512
        )
        return self._parse(text)

    def write_report(self, history: list[Step]) -> str:
        trail = "\n".join(
            f"- {s.proposed_action} ({s.reasoning})" for s in history if s.resolved
        )
        return self.client.complete(
            "You are a security analyst writing an incident report.",
            f"{REPORT_PROMPT}\n\nYour investigation trail:\n{trail}",
            max_tokens=1024,
        )

    @staticmethod
    def _parse(text: str) -> tuple[str, str]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
                return str(obj.get("action", "")).strip(), str(
                    obj.get("reasoning", "")
                ).strip()
            except json.JSONDecodeError:
                pass
        # No JSON: treat the whole reply as the proposed action.
        return text.strip(), ""
