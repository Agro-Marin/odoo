from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_unresolved_calls as gate
from _repo_root import SIBLING_REPOS


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
    found = _measure(
        tmp_path,
        decl='__slots__ = ("_lazy",)\n',
        caller="self._lazy()\n",
    )
    assert found == []


def test_a_name_merely_MENTIONED_inside_a_longer_string_does_not_resolve_it(tmp_path):
    found = _measure(
        tmp_path,
        prose='"""Nothing to do with it: _coincidence here"""\n',
        caller="self._coincidence()\n",
    )
    assert _names(found) == ["_coincidence"]


def test_a_dunder_is_not_a_private_call(tmp_path):
    assert _measure(tmp_path, a="self.__reduce__()\n") == []


def test_a_public_call_is_not_scanned(tmp_path):
    assert _measure(tmp_path, a="self.action_confirm()\n") == []


def test_a_bare_function_call_is_not_scanned(tmp_path):
    assert _measure(tmp_path, a="_helper()\n") == []


def test_the_external_allowlist_suppresses_its_entries(tmp_path):
    entry = next(iter(gate.EXTERNAL))
    assert _measure(tmp_path, a=f"self.{entry}()\n") == []


def test_every_external_entry_is_still_earning_its_place():
    assert gate.EXTERNAL, "the allowlist is empty; the probe would pass vacuously"
    assert all(name.startswith("_") for name in gate.EXTERNAL), (
        f"non-private names in EXTERNAL: "
        f"{sorted(n for n in gate.EXTERNAL if not n.startswith('_'))} -- the gate "
        f"never reports those, so the entry suppresses nothing"
    )


def test_test_files_are_scanned_unlike_the_sibling_counters(tmp_path):
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


def test_an_unrelated_string_no_longer_silences_a_real_call(tmp_path):
    # A list of names anywhere in the tree used to bind every one of them, so a
    # test naming the methods a rename abolished switched this gate off for
    # exactly the calls it exists to find.
    found = _measure(
        tmp_path,
        caller="self._vanished()\n",
        roster='ABOLISHED = ("_vanished", "_gone")\n',
    )
    assert _names(found) == ["_vanished"]


def test_the_getattr_family_still_binds_its_name(tmp_path):
    for call in (
        'getattr(obj, "_dynamic", None)',
        'hasattr(obj, "_dynamic")',
        'setattr(obj, "_dynamic", 1)',
        'object.__setattr__(self, "_dynamic", 1)',
    ):
        found = _measure(tmp_path, a=f"self._dynamic()\n{call}\n")
        assert found == [], call


def test_a_slots_declaration_binds_its_names(tmp_path):
    source = 'class X:\n    __slots__ = ["_slotted"]\n\n\nself._slotted()\n'
    assert _measure(tmp_path, a=source) == []


def test_roots_report_only_the_sibling_but_resolve_against_the_framework(tmp_path):
    core = tmp_path / "odoo"
    core.mkdir(parents=True, exist_ok=True)
    (core / "framework.py").write_text(
        "class X:\n    def _provided(self):\n        return 1\n", encoding="utf-8"
    )
    sibling = tmp_path / "sibling"
    sibling.mkdir(parents=True, exist_ok=True)
    (sibling / "addon.py").write_text(
        "self._provided()\nself._missing()\n", encoding="utf-8"
    )
    (core / "core_caller.py").write_text("self._also_missing()\n", encoding="utf-8")

    found = gate.measure(scopes=(core, sibling), report_scopes=(sibling,))
    assert _names(found) == ["_missing"], (
        "a name the framework defines must resolve, and the framework's own "
        "unresolved calls belong to the framework's own run"
    )


def test_a_scoped_external_entry_does_not_leak_to_the_default_scope(tmp_path):
    core = tmp_path / "odoo"
    core.mkdir(parents=True, exist_ok=True)
    (core / "caller.py").write_text("lib.thing._third_party()\n", encoding="utf-8")
    sibling = tmp_path / "sibling"
    sibling.mkdir(parents=True, exist_ok=True)
    (sibling / "caller.py").write_text("lib.thing._third_party()\n", encoding="utf-8")

    scoped = frozenset({"_third_party"})
    assert _names(gate.measure(scopes=(core, sibling), report_scopes=(sibling,))) == [
        "_third_party"
    ]
    assert (
        gate.measure(scopes=(core, sibling), report_scopes=(sibling,), external=scoped)
        == []
    )
    assert _names(gate.measure(scopes=(core,))) == ["_third_party"], (
        "the sibling's allowlist must not silence the name in the default scope"
    )


def test_every_scoped_external_entry_names_a_real_root():
    """A key must be a repository this workspace HAS, not one it has CHECKED OUT.

    This read the filesystem — `ROOT.parent.iterdir()` — which made the verdict
    depend on the developer's directory layout. It passed on a workstation with
    the siblings cloned beside the fork and failed everywhere else: in a
    `git worktree`, and in CI, which checks this repository out alone and is the
    one place the gate had to work. The key is matched against `scope.name`, and
    the names a scope can have are a vocabulary, so that is what to check
    against.
    """
    for name in gate.EXTERNAL_BY_ROOT:
        assert name in SIBLING_REPOS, (
            f"EXTERNAL_BY_ROOT names {name!r}, which is not one of the workspace "
            f"repositories {list(SIBLING_REPOS)} — it can never match a scope, so "
            f"its entries can never apply"
        )


def test_no_scoped_entry_duplicates_the_global_list():
    for name, entries in gate.EXTERNAL_BY_ROOT.items():
        overlap = entries & gate.EXTERNAL
        assert not overlap, (
            f"{name} re-states {sorted(overlap)}, which EXTERNAL already allows "
            f"everywhere"
        )


def test_also_define_resolves_without_reporting(tmp_path):
    core = tmp_path / "odoo"
    core.mkdir(parents=True, exist_ok=True)
    (core / "core.py").write_text("self._core_gap()\n", encoding="utf-8")
    dependency = tmp_path / "dependency"
    dependency.mkdir(parents=True, exist_ok=True)
    (dependency / "lib.py").write_text(
        "class X:\n    def _provided(self):\n        return 1\n\n\nself._dep_gap()\n",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer"
    consumer.mkdir(parents=True, exist_ok=True)
    (consumer / "addon.py").write_text(
        "self._provided()\nself._real_gap()\n", encoding="utf-8"
    )

    blind = gate.measure(scopes=(core, consumer), report_scopes=(consumer,))
    assert _names(blind) == ["_provided", "_real_gap"], (
        "without the dependency, a name it defines counts as unresolved"
    )

    seeing = gate.measure(
        scopes=(core, consumer, dependency), report_scopes=(consumer,)
    )
    assert _names(seeing) == ["_real_gap"], (
        "the dependency resolves its own name, and its own gaps stay its own"
    )


def test_a_root_that_does_not_exist_refuses_instead_of_reporting_zero(tmp_path):
    # Nothing measured passes a no-increase ratchet, so a mistyped or
    # not-checked-out root would turn the gate green.
    assert gate.main(["--roots", str(tmp_path / "absent"), "--count"]) == 2
    assert gate.main(["--also-define", str(tmp_path / "absent"), "--count"]) == 2


def test_a_root_with_no_python_refuses_too(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "README.md").write_text("not python\n", encoding="utf-8")
    assert gate.main(["--roots", str(empty), "--count"]) == 2
