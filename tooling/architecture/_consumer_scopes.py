"""Which checkouts consume `web`, and which lane actually judges each one.

Six gates carried a byte-identical `CONSUMER_ROOTS` tuple. That much is plain
duplication. The reason this module exists rather than a shared constant is the
second table.

WHAT WENT WRONG. `js_public_surface` and `js_extension_surface` both printed,
over whatever scopes were missing from the checkout::

    absent, validated in their own CI: enterprise, agromarin, design-themes

unconditionally, for any absent scope. It is true of `enterprise` and
`agromarin`, which each carry an `architecture.yml` that checks this repo out
beside them and re-runs the boundary gates. It is FALSE of `design-themes`,
which has no `.github/` and no CI configuration of any kind — so its rows in
both pins are written from a developer's workspace and judged by nothing.

Measured 2026-08-25 at `598cf211cc2`: the `design-themes` scope of
`public_surface_web.txt` had drifted by five entries — two `@web/legacy/*`
specifiers deleted with `theme_common`'s dead snippets, `@web/core/registry` no
longer reached, and `@web/core/l10n/translation` still pinned after the module
became `@web/core/translation`. None of that could fail anywhere.

AND IT IS PER GATE, NOT PER SCOPE. `agromarin` has a lane, but that lane runs
`js_public_surface` and not `js_extension_surface` — so `MultiRecordController.
setup` sat in `extension_surface_web.txt` claiming an agromarin override that no
longer existed, and the only run that could see it (odoo alone) reported
"unchanged across 1 scope(s) ✓" and exited 0.

A gate that prints "checked elsewhere" about a scope nothing checks is a
fail-open with a reassuring message, which is the failure mode every gate in
this directory exists to end. :func:`absent_scopes_line` prints what is true.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="_consumer_scopes")

#: Every checkout that imports `web`, `odoo` first. A gate measures the scopes
#: that are present and pins each one's provenance separately, so a repo-alone
#: CI run validates `odoo` and leaves the rest of the pin untouched.
CONSUMER_ROOTS: tuple[tuple[str, Path], ...] = (
    ("odoo", ROOT),
    ("enterprise", sibling_repos_root(ROOT) / "enterprise"),
    ("agromarin", sibling_repos_root(ROOT) / "agromarin"),
    ("design-themes", sibling_repos_root(ROOT) / "design-themes"),
)

#: gate stem -> {consumer scope: the workflow that judges it}.
#:
#: DECLARED, not discovered, because CI checks this repository out alone and
#: cannot read a sibling's workflow. `test_consumer_scopes` re-derives it from
#: the sibling checkouts whenever they ARE present, so the workspace keeps the
#: declaration honest and CI still runs. `odoo` is omitted throughout: it is
#: judged by this repo's own `architecture.yml`, which is where these gates run.
VALIDATED_BY: dict[str, dict[str, str]] = {
    "js_public_surface": {
        "enterprise": "enterprise/.github/workflows/architecture.yml",
        "agromarin": "agromarin/.github/workflows/architecture.yml",
        "design-themes": "design-themes/.github/workflows/architecture.yml",
    },
    "js_extension_surface": {
        # Added to both lanes on 2026-08-25. Until then this gate ran only in
        # the community fork's own `architecture.yml`, which checks that repo
        # out alone — so every sibling scope of `extension_surface_web.txt` was
        # pinned and judged by nothing, and the odoo-alone run reported
        # "unchanged across 1 scope(s). ✓".
        "enterprise": "enterprise/.github/workflows/architecture.yml",
        "agromarin": "agromarin/.github/workflows/architecture.yml",
        "design-themes": "design-themes/.github/workflows/architecture.yml",
    },
}

#: Scopes no lane judges, for any gate. Empty since 2026-08-25, when
#: `design-themes` got the `architecture.yml` the other two consumers already
#: had — it had none, and both surface gates were telling every reader it was
#: "validated in their own CI". Kept as a named, tested set rather than deleted:
#: a fifth consumer will arrive unjudged, and this is where it must be declared
#: before the gates will stop claiming coverage for it.
UNJUDGED_SCOPES: frozenset[str] = frozenset()


def absent_scopes_line(gate: str, absent: list[str]) -> str:
    """One honest line about the scopes this run could not measure.

    Splits them: the ones a named lane re-runs this gate for, and the ones
    nothing does. A scope in the second group is pinned but unjudged, and the
    line says so rather than implying coverage.
    """
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
