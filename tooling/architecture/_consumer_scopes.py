from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="_consumer_scopes")

CONSUMER_ROOTS: tuple[tuple[str, Path], ...] = (
    ("odoo", ROOT),
    ("enterprise", sibling_repos_root(ROOT) / "enterprise"),
    ("agromarin", sibling_repos_root(ROOT) / "agromarin"),
    ("design-themes", sibling_repos_root(ROOT) / "design-themes"),
)

VALIDATED_BY: dict[str, dict[str, str]] = {
    "js_public_surface": {
        "enterprise": "enterprise/.github/workflows/architecture.yml",
        "agromarin": "agromarin/.github/workflows/architecture.yml",
        "design-themes": "design-themes/.github/workflows/architecture.yml",
    },
    "js_extension_surface": {
        "enterprise": "enterprise/.github/workflows/architecture.yml",
        "agromarin": "agromarin/.github/workflows/architecture.yml",
        "design-themes": "design-themes/.github/workflows/architecture.yml",
    },
}

UNJUDGED_SCOPES: frozenset[str] = frozenset()


def absent_scopes_line(gate: str, absent: list[str]) -> str:
    judged = VALIDATED_BY.get(gate, {})
    covered = [s for s in absent if s in judged]
    unjudged = [s for s in absent if s not in judged]
    parts = []
    if covered:
        lanes = sorted({judged[s] for s in covered})
        parts.append(f"  absent, re-run by {', '.join(lanes)}: {', '.join(covered)}")
    if unjudged:
        parts.append(
            f"  absent and judged by NO lane: {', '.join(unjudged)}"
            f"  <- pinned here, checked nowhere"
        )
    return "\n".join(parts)
