"""Load incident scenarios from YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from irene.models import Incident


def load_incident(path: str | Path) -> Incident:
    """Parse and validate a single incident YAML file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Incident.model_validate(raw)


def load_incidents(directory: str | Path) -> list[Incident]:
    """Load every ``*.yaml`` / ``*.yml`` incident in a directory."""
    directory = Path(directory)
    files = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    return [load_incident(f) for f in files]
