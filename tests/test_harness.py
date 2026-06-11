"""End-to-end tests for the harness + scorer using scripted free-text policies.

These run with no API key: a ``ScriptedPolicy`` emits free-text actions and the
offline ``KeywordResolver`` maps them onto the incident graph, so we can assert
exactly how the engine and scorer behave on known paths.
"""

from pathlib import Path

import pytest

from irene import load_incident, run_incident, score_run
from irene.resolver import KeywordResolver

INCIDENT = Path(__file__).resolve().parents[1] / "incidents" / "phishing_credential_theft.yaml"

REPORT = "phishing led to Mimikatz dumping svc-backup credential on WS-014"


class ScriptedPolicy:
    """Emits a fixed sequence of free-text actions (by action label)."""

    def __init__(self, incident, plan_ids, report=REPORT):
        labels = {a.id: a.label for s in incident.states for a in s.actions}
        self._plan = [labels[i] for i in plan_ids]
        self._report = report

    def act(self, state, history):
        if self._plan:
            return self._plan.pop(0), "scripted"
        return state.actions[0].label, "fallback"

    def write_report(self, history):
        return self._report


def _optimal_plan(incident):
    return list(incident.scoring.optimal_path)


def test_incident_loads_and_validates():
    incident = load_incident(INCIDENT)
    assert incident.id == "phishing_credential_theft"
    assert incident.state(incident.start_state).id == "s_alert"


def test_optimal_path_scores_perfectly():
    incident = load_incident(INCIDENT)
    policy = ScriptedPolicy(incident, _optimal_plan(incident))
    run = run_incident(incident, policy, resolver=KeywordResolver())
    card = score_run(incident, run)

    assert card.reached_goal
    assert card.false_leads == 0
    assert card.unresolved == 0
    assert card.report_recall == 1.0
    assert card.score == pytest.approx(1.0)


def test_false_lead_is_penalized():
    incident = load_incident(INCIDENT)
    plan = ["a_call_user", "a_user_back_to_edr", "a_isolate_host", "a_reset_creds", "a_write_report"]
    run = run_incident(incident, ScriptedPolicy(incident, plan), resolver=KeywordResolver())
    card = score_run(incident, run)

    assert card.reached_goal
    assert card.false_leads == 1
    assert card.score < 1.0


def test_missing_report_facts_lowers_recall():
    incident = load_incident(INCIDENT)
    policy = ScriptedPolicy(incident, _optimal_plan(incident), report="nothing relevant")
    run = run_incident(incident, policy, resolver=KeywordResolver())
    card = score_run(incident, run)

    assert card.report_recall == 0.0
    assert card.score == 0.0


def test_information_disclosure_only_current_state():
    """The policy must only ever receive the current state's actions."""
    incident = load_incident(INCIDENT)
    seen = []

    class SpyPolicy(ScriptedPolicy):
        def act(self, state, history):
            seen.append({a.id for a in state.actions})
            return super().act(state, history)

    run_incident(incident, SpyPolicy(incident, _optimal_plan(incident)), resolver=KeywordResolver())
    assert seen[0] == {"a_triage_edr", "a_reimage_now", "a_call_user"}


def test_unresolved_actions_are_recorded_and_end_run():
    """A policy that keeps proposing nonsense gets cut off and scores zero."""
    incident = load_incident(INCIDENT)

    class FlailPolicy:
        def act(self, state, history):
            return "contemplate the meaning of the alert", "stuck"

        def write_report(self, history):
            return ""

    run = run_incident(incident, FlailPolicy(), resolver=KeywordResolver(), max_unresolved=3)
    card = score_run(incident, run)

    assert run.truncated
    assert run.unresolved_count == 3
    assert not card.reached_goal
    assert card.score == 0.0
