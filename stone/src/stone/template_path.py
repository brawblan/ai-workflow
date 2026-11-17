"""Find the file of a template: in the adapter folder first, then in the shared folder (D120)."""

from __future__ import annotations

from pathlib import Path

SHARED = "shared"


def template_file(harness: Path, name: str) -> Path:
    """Return the template file of an adapter component.

    A template that names no harness is in `adapters/shared/templates/`. Each adapter that needs it
    lists it in its own `components.yaml`. If the adapter folder has the same name, that file wins.
    """
    own = harness / "templates" / name
    shared = harness.parent / SHARED / "templates" / name
    return shared if not own.exists() and shared.exists() else own
