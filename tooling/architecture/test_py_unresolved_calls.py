"""A private call whose definition is nowhere, and the four ways it can be somewhere.

The gate (ADR-0058) reports `x._name(...)` where nothing in the checkout defines
`_name`. What makes it usable rather than a noise generator is the set of things
that COUNT as defining it — a `def`, a `class`, an attribute binding, a bare
string literal — and one allowlist for receivers whose class lives outside the
repository. Each of those exists to suppress a whole family of false positives,
and none was pinned.

The asymmetry matters more here than in most gates. Widen the "defined" rule and
the floor silently drops, taking real vanished methods with it; narrow it and the
gate floods with legitimate indirection until someone stops reading it. Both
directions are below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_unresolved_calls as gate


def _measure(tmp_path: Path, **sources: str) -> list[gate.UnresolvedCall]:
    scope = tmp_path / "odoo"
    scope.mkdir(parents=True, exist_ok=True)
    for name, text in sources.items():
        (scope / f"{name}.py").write_text(text, encoding="utf-8")
    return gate.measure(scopes=(scope,))


def _names(found) -> list[str]:
    return sorted(c.name for c in found)


def test_a_call_to_nothing_is_reported(tmp_path):
    assert _names(_measure(tmp_path, a="self._vanished()\n")) == ["_vanished"]


def test_a_def_anywhere_in_scope_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        caller="self._helper()\n",
        elsewhere="class X:\n    def _helper(self):\n        return 1\n",
    )
    assert found == []


def test_a_class_name_resolves_it(tmp_path):
    assert _measure(tmp_path, a="class _Thing:\n    pass\n\n\nx._Thing()\n") == []


def test_an_attribute_binding_resolves_it(tmp_path):
    """`obj._name = ...` is how a slot or a patched-in callable is bound.

    Without this the gate reports every monkeypatched hook in the tree.
    """
    found = _measure(
        tmp_path,
        binder="obj._patched = lambda self: None\n",
        caller="self._patched()\n",
    )
    assert found == []


def test_an_annotated_attribute_binding_resolves_it(tmp_path):
    found = _measure(
        tmp_path,
        binder="class X:\n    obj._slot: int = 0\n",
        caller="self._slot()\n",
    )
    assert found == []


def test_a_bare_string_literal_resolves_it(tmp_path):
    """`__slots__` and `getattr` name methods as strings, not as code.

    A name reached that way is live at runtime and is not a vanished method, so
    a string literal EQUAL to it anywhere in scope clears the call.
    """
    found = _measure(
        tmp_path,
        decl='__slots__ = ("_lazy",)\n',
        caller="self._lazy()\n",
    )
    assert found == []


def test_a_name_merely_MENTIONED_inside_a_longer_string_does_not_resolve_it(tmp_path):
    """The rule is whole-value equality, not substring, and the difference is large.

    Written expecting the opposite. `bound.add(node.value)` stores the entire
    string, so a docstring that happens to name a method does not clear a call to
    it -- which is the right rule and a much narrower one than "any string
    anywhere". A gate that cleared on a mention could be silenced by its own
    prose, and this fork's modules are heavily commented.
    """
    found = _measure(
        tmp_path,
        # No trailing punctuation on the mention, deliberately: with a period
        # attached, a mutation that split the string on whitespace would still
        # not clear the call, and the test would pass over a real widening.
        prose='"""Nothing to do with it: _coincidence here"""\n',
        caller="self._coincidence()\n",
    )
    assert _names(found) == ["_coincidence"]


def test_a_dunder_is_not_a_private_call(tmp_path):
    """`__init__`, `__enter__` and friends are the language's, not the fork's."""
    assert _measure(tmp_path, a="self.__reduce__()\n") == []


def test_a_public_call_is_not_scanned(tmp_path):
    assert _measure(tmp_path, a="self.action_confirm()\n") == []


def test_a_bare_function_call_is_not_scanned(tmp_path):
    """The gate is about `x._name()`, where the receiver is the unknown.

    A bare `_helper()` resolves by ordinary scoping and its absence is a
    NameError the interpreter reports on its own.
    """
    assert _measure(tmp_path, a="_helper()\n") == []


def test_the_external_allowlist_suppresses_its_entries(tmp_path):
    """Receivers whose class this scan cannot see: a stdlib or third-party base.

    An entry there is a CLAIM that the receiver is external, which is why the
    gate's docstring says to check the call site before adding one -- "I could
    not find it" is the finding, not the excuse.
    """
    entry = next(iter(gate.EXTERNAL))
    assert _measure(tmp_path, a=f"self.{entry}()\n") == []


def test_every_external_entry_is_still_earning_its_place():
    """An allowlist entry that the tree now defines is silencing nothing.

    The same shape as `test_gate_adr_coverage`'s stale-pin check: the list may
    only shrink, and an entry that has become redundant should go rather than
    sit there implying a suppression that no longer happens.
    """
    assert gate.EXTERNAL, "the allowlist is empty; the probe would pass vacuously"
    assert all(name.startswith("_") for name in gate.EXTERNAL), (
        f"non-private names in EXTERNAL: "
        f"{sorted(n for n in gate.EXTERNAL if not n.startswith('_'))} -- the gate "
        f"never reports those, so the entry suppresses nothing"
    )


def test_test_files_are_scanned_unlike_the_sibling_counters(tmp_path):
    """The divergence, asserted rather than left to be discovered.

    Four sibling gates exclude `tests/` through `_sources.is_test_path`; this one
    does not, and 7 of its floored findings sit under `tests/`. A test calling a
    method that no longer exists is the same defect as production code doing it,
    and worse: the test can no longer fail for the reason it was written.
    """
    scope = tmp_path / "odoo"
    (scope / "tests").mkdir(parents=True)
    (scope / "tests" / "test_thing.py").write_text("self._gone()\n", encoding="utf-8")
    assert _names(gate.measure(scopes=(scope,))) == ["_gone"]


def test_an_empty_scan_refuses_instead_of_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="no Python sources"):
        gate.measure(scopes=(tmp_path / "absent",))


def test_findings_are_sorted_so_a_diff_is_readable(tmp_path):
    found = _measure(tmp_path, a="self._zeta()\nself._alpha()\n")
    assert _names(found) == ["_alpha", "_zeta"]
    assert [c.name for c in found] == ["_alpha", "_zeta"]
