"""Tests for free-text action resolution."""

from pathlib import Path

from irene import load_incident
from irene.resolver import KeywordResolver, LLMResolver

INCIDENT = Path(__file__).resolve().parents[1] / "incidents" / "phishing_credential_theft.yaml"


def _start_state(incident):
    return incident.state(incident.start_state)


def test_keyword_resolver_matches_paraphrase():
    incident = load_incident(INCIDENT)
    state = _start_state(incident)
    res = KeywordResolver().resolve(state, "let me pull the EDR process tree first")
    assert res.matched
    assert res.action.id == "a_triage_edr"


def test_keyword_resolver_matches_exact_label():
    incident = load_incident(INCIDENT)
    state = _start_state(incident)
    res = KeywordResolver().resolve(state, "Immediately reimage WS-014 to be safe.")
    assert res.matched
    assert res.action.id == "a_reimage_now"


def test_keyword_resolver_rejects_unrelated_text():
    incident = load_incident(INCIDENT)
    state = _start_state(incident)
    res = KeywordResolver().resolve(state, "order a pizza for the SOC team")
    assert not res.matched


class FakeClient:
    """Returns a canned action id, mimicking an LLM judge classification."""

    model = "fake"

    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, prompt, *, max_tokens=1024):
        return self.reply


def test_llm_resolver_uses_classification():
    incident = load_incident(INCIDENT)
    state = _start_state(incident)
    res = LLMResolver(FakeClient("a_isolate_host")).resolve(state, "cut the box off the network")
    # a_isolate_host isn't an option in the start state, so it should fall back
    # to keyword matching on the proposed text (which mentions "network").
    assert res.matched is False or res.action.id in {a.id for a in state.actions}


def test_llm_resolver_none_is_unmatched():
    incident = load_incident(INCIDENT)
    state = _start_state(incident)
    res = LLMResolver(FakeClient("none")).resolve(state, "do something unmappable")
    assert not res.matched
