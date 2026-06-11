"""Tests for the provider factory and the LLM-as-judge, using fake clients."""

from pathlib import Path

import pytest

from irene import load_incident, run_incident, score_run
from irene.providers import AnthropicClient, OpenAIClient, make_client
from irene.resolver import KeywordResolver
from irene.scorer import LLMJudge

INCIDENT = Path(__file__).resolve().parents[1] / "incidents" / "phishing_credential_theft.yaml"


def test_make_client_returns_right_backend():
    a = make_client("anthropic", model="claude-opus-4-8", api_key="x")
    assert isinstance(a, AnthropicClient)
    o = make_client("openai", model="some-model", api_key="x", base_url="http://localhost:8000/v1")
    assert isinstance(o, OpenAIClient)
    assert o.model == "some-model"


def test_openai_provider_requires_model():
    with pytest.raises(ValueError):
        make_client("openai")


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        make_client("acme-llm", model="x")


class FakeJudgeClient:
    model = "fake-judge"

    def complete(self, system, prompt, *, max_tokens=1024):
        return '{"report_quality": 5, "reasoning_quality": 4, "notes": "solid"}'


class OptimalScripted:
    def __init__(self, incident):
        self._labels = {a.id: a.label for s in incident.states for a in s.actions}
        self._plan = list(incident.scoring.optimal_path)

    def act(self, state, history):
        avail = {a.id for a in state.actions}
        for aid in self._plan:
            if aid in avail:
                self._plan.remove(aid)
                return self._labels[aid], "scripted"
        return state.actions[0].label, "fallback"

    def write_report(self, history):
        return "phishing Mimikatz svc-backup credential WS-014 isolated rotated"


def test_judge_scores_feed_into_scorecard():
    incident = load_incident(INCIDENT)
    run = run_incident(incident, OptimalScripted(incident), resolver=KeywordResolver())
    card = score_run(incident, run, judge=LLMJudge(FakeJudgeClient(), seed=0))

    assert card.report_quality == pytest.approx(1.0)  # 5/5
    assert card.reasoning_quality == pytest.approx(0.8)  # 4/5
    assert card.judge_notes == "solid"
    assert card.score == pytest.approx(0.8)  # efficiency 1.0 * 1.0 * 0.8
