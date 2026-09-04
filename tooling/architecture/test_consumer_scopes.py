from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _consumer_scopes as cs


def test_every_governed_gate_declares_a_row():
    here = Path(__file__).resolve().parent
    printers = {
        p.stem
        for p in here.glob("*.py")
        if not p.stem.startswith(("test_", "_"))
        and "absent_scopes_line" in p.read_text(encoding="utf-8")
    }
    assert printers, "no gate calls absent_scopes_line — the probe found nothing"
    missing = printers - set(cs.VALIDATED_BY)
    assert not missing, (
        f"{sorted(missing)} print the absent-scope line but declare no row in "
        f"VALIDATED_BY. An empty dict is a real answer ('nothing judges this "
        f"gate's sibling scopes'); a missing key is an oversight that reads the "
        f"same way."
    )


def test_no_scope_is_pinned_without_a_judge_today():
    judged = {scope for lanes in cs.VALIDATED_BY.values() for scope in lanes}
    uncovered = {
        name
        for name, _root in cs.CONSUMER_ROOTS
        if name != "odoo" and name not in judged and name not in cs.UNJUDGED_SCOPES
    }
    assert not uncovered, (
        f"{sorted(uncovered)} consume `web` and appear in the pins, but no gate "
        f"declares a check for them and they are not listed as unjudged. Declare "
        f"the hole in UNJUDGED_SCOPES so the gates stop claiming coverage."
    )


def test_the_roots_are_shared_not_copied():
    here = Path(__file__).resolve().parent
    copies = [
        p.name
        for p in sorted(here.glob("*.py"))
        if p.stem != "_consumer_scopes"
        and not p.stem.startswith("test_")
        and re.search(r'CONSUMER_ROOTS\s*=\s*\(\s*\n\s*\("odoo"', p.read_text("utf-8"))
    ]
    assert not copies, (
        f"{copies} still declare CONSUMER_ROOTS inline. Import it from "
        f"_consumer_scopes so the scope list and the judge table cannot disagree."
    )
