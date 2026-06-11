"""Command-line entry point for running the benchmark.

    irene list
    irene run <incident.yaml> --optimal           # offline dry-run, no API key
    irene run <incident.yaml>                      # Claude (ANTHROPIC_API_KEY)
    irene run <incident.yaml> \
        --provider openai --model llama-3.1-70b \
        --base-url http://localhost:8000/v1       # any OpenAI-compatible server
    irene run <incident.yaml> --judge             # add LLM-as-judge rubric scoring

``--optimal`` replays the ground-truth path with the offline keyword resolver and
needs no API key — handy for validating an incident's graph and scoring. Real
runs use the LLM resolver and (optionally) the LLM judge.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from irene.harness import Step, run_incident
from irene.incident import load_incident, load_incidents
from irene.models import Incident, State
from irene.scorer import LLMJudge, score_run

INCIDENTS_DIR = Path(__file__).resolve().parents[2] / "incidents"


class OptimalPolicy:
    """Replays an incident's ground-truth optimal path as free text. No model."""

    def __init__(self, incident: Incident):
        self._remaining = list(incident.scoring.optimal_path)
        self._labels = {
            a.id: a.label for s in incident.states for a in s.actions
        }

    def act(self, state: State, history: list[Step]) -> tuple[str, str]:
        available = {a.id for a in state.actions}
        for action_id in self._remaining:
            if action_id in available:
                self._remaining.remove(action_id)
                # Emit the action's label as free text; the resolver maps it back.
                return self._labels[action_id], "optimal path"
        return state.actions[0].label, "optimal path exhausted; defaulting"

    def write_report(self, history: list[Step]) -> str:
        return (
            "Phishing email led to a PowerShell payload on WS-014. The attacker "
            "ran Mimikatz to steal jdoe and svc-backup credentials. We isolated "
            "the host, rotated the stolen credentials, and removed persistence."
        )


def _cmd_list(_: argparse.Namespace) -> int:
    incidents = load_incidents(INCIDENTS_DIR)
    if not incidents:
        print(f"No incidents found in {INCIDENTS_DIR}")
        return 1
    for inc in incidents:
        print(f"{inc.id:32} {inc.title}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    incident = load_incident(args.incident)
    resolver = None  # default: offline KeywordResolver
    judge = None

    if args.optimal:
        policy: object = OptimalPolicy(incident)
    else:
        from irene.providers import make_client
        from irene.resolver import LLMResolver
        from irene.runner import ModelPolicy

        client = make_client(
            args.provider,
            model=args.model,
            api_key=args.api_key or os.environ.get("IRENE_API_KEY"),
            base_url=args.base_url,
        )
        policy = ModelPolicy(client)
        resolver = LLMResolver(client)
        if args.judge:
            judge = LLMJudge(client, seed=args.seed)

    run = run_incident(incident, policy, resolver=resolver)
    card = score_run(incident, run, judge=judge)

    print(f"\nIncident: {incident.title}")
    print("Path taken:", " -> ".join(run.action_path) or "(none)")
    if run.unresolved_count:
        print(f"Unresolved free-text attempts: {run.unresolved_count}")
    if run.truncated:
        print("WARNING: run truncated (stuck or hit step limit)")
    print("\n" + card.summary())
    if card.judge_notes:
        print("\nJudge notes:", card.judge_notes)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Incident titles may contain non-ASCII (e.g. "→"); Windows consoles default
    # to cp1252 and would crash on them.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(prog="irene", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list available incidents")
    p_list.set_defaults(func=_cmd_list)

    p_run = sub.add_parser("run", help="run an incident")
    p_run.add_argument("incident", help="path to an incident YAML file")
    p_run.add_argument(
        "--optimal",
        action="store_true",
        help="replay the ground-truth optimal path offline (no API key needed)",
    )
    p_run.add_argument(
        "--provider",
        default="anthropic",
        help="model backend: 'anthropic' or 'openai' (OpenAI-compatible)",
    )
    p_run.add_argument("--model", default=None, help="model id (required for openai)")
    p_run.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint, e.g. http://localhost:8000/v1 "
        "(or set OPENAI_BASE_URL)",
    )
    p_run.add_argument(
        "--api-key",
        default=None,
        help="API key (or use ANTHROPIC_API_KEY / OPENAI_API_KEY / IRENE_API_KEY)",
    )
    p_run.add_argument(
        "--judge",
        action="store_true",
        help="grade report & reasoning quality with an LLM-as-judge rubric",
    )
    p_run.add_argument("--seed", type=int, default=None, help="judge shuffle seed")
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
