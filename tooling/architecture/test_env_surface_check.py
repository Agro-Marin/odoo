#!/usr/bin/env python3
"""Self-test for ``env_surface_check.py``.

A gate that cannot fail is decoration. The cases below pin the ways this one
could lie:

* **Silence on a real reach** — the whole point is that ``env.<private>`` from a
  lower layer must trip it. If the collector's ``<x>.env`` heuristic missed
  ``self.env`` or bare ``env``, the checker would report a permanent green.
* **Silence on a renamed member** — the reason the gate exists. Four call sites
  read the cache memo through ``env.__dict__["_field_cache_memo"]``; renaming
  ``Environment._field_cache_memo`` breaks them *silently*, because the
  ``except KeyError`` fallback swallows it and the fast path just stops firing.
  ``TestCatchesRename`` is the regression test for the hole nothing else covers.
* **Double-counting ``__dict__``** — the subscript form must be recorded once,
  as the member it names, not twice (once as ``__dict__``, once opaque).
* **A stale pin** — a ``KNOWN_VIOLATIONS`` entry whose file or attribute no
  longer exists would silently widen the tolerated set.
* **Miscounting ``Environment``'s members** — ``env.get`` comes from ``Mapping``,
  not from the class body. Resolving members without the base would flag every
  ``env.get`` as nonexistent.

Run directly (``python tooling/architecture/test_env_surface_check.py``) or
under pytest.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env_surface_check as esc


def _check_source(src: str, layer: str = "Layer 1", name: str = "probe.py"):
    """Run the checker over in-memory source, bypassing the filesystem walk."""
    tmp = Path(esc.REPO_ROOT) / "odoo" / "orm" / "fields" / f"_{name}"
    tmp.write_text(src, encoding="utf-8")
    try:
        return esc.check(files=[(tmp, layer)])
    finally:
        tmp.unlink()


class TestCollectorFindsReaches(unittest.TestCase):
    def test_self_env_private_is_a_new_violation(self):
        report = _check_source("def f(self):\n    return self.env._secret_thing\n")
        self.assertEqual([r.attr for r in report.new], ["_secret_thing"])

    def test_bare_env_private_is_a_new_violation(self):
        report = _check_source("def f(env):\n    return env._secret_thing\n")
        self.assertEqual([r.attr for r in report.new], ["_secret_thing"])

    def test_public_member_is_not_a_violation(self):
        report = _check_source("def f(self):\n    return self.env.context\n")
        self.assertEqual(report.new, [])
        self.assertTrue(report.ok)

    def test_sanctioned_private_members_pass(self):
        for attr in sorted(esc.SANCTIONED_PRIVATE):
            with self.subTest(attr=attr):
                report = _check_source(f"def f(self):\n    return self.env.{attr}\n")
                self.assertEqual(report.new, [], f"env.{attr} should be sanctioned")

    def test_components_may_reach_env_for_nothing(self):
        report = _check_source(
            "def f(self):\n    return self.env.context\n", layer="components"
        )
        self.assertEqual([r.attr for r in report.new], ["context"])


class TestCatchesRename(unittest.TestCase):
    """The hole this gate exists to close."""

    def test_dict_key_is_resolved_to_the_member_it_names(self):
        report = _check_source(
            'def f(env):\n    return env.__dict__["_field_cache_memo"]\n'
        )
        attrs = [r.attr for r in report.reaches]
        self.assertIn("_field_cache_memo", attrs)
        self.assertNotIn("__dict__", attrs, "must not double-count the bare __dict__")
        self.assertTrue(any(r.via_dict for r in report.reaches))

    def test_nonexistent_member_via_dict_key_is_flagged(self):
        # Simulates renaming Environment._field_cache_memo without updating the
        # four string-key call sites. Nothing else in the repo catches this.
        report = _check_source('def f(env):\n    return env.__dict__["_renamed_away"]\n')
        self.assertEqual([r.attr for r in report.unknown_members], ["_renamed_away"])
        self.assertFalse(report.ok)

    def test_nonexistent_plain_attribute_is_flagged(self):
        report = _check_source("def f(self):\n    return self.env.no_such_member\n")
        self.assertEqual([r.attr for r in report.unknown_members], ["no_such_member"])
        self.assertFalse(report.ok)


class TestEnvironmentMembers(unittest.TestCase):
    def test_inherited_mapping_methods_are_resolved(self):
        # env.get is used by Layers 1 and 2 and is defined by Mapping, not by
        # Environment. Omitting the base would false-positive on every use.
        self.assertIn("get", esc.environment_members())

    def test_class_body_members_are_resolved(self):
        members = esc.environment_members()
        for name in ("cr", "uid", "context", "su", "registry", "_core"):
            with self.subTest(name=name):
                self.assertIn(name, members)

    def test_agrees_with_the_runtime_class(self):
        """Cross-check the AST parse against the real imported Environment."""
        if str(esc.REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(esc.REPO_ROOT))
        try:
            from odoo.orm.runtime.environment import Environment
        except Exception as exc:  # pragma: no cover - env-dependent
            raise unittest.SkipTest(f"odoo not importable: {exc}") from exc
        parsed = esc.environment_members()
        runtime = set(dir(Environment))
        missed = {
            n for n in runtime if not n.startswith("__") and n not in parsed
        }
        self.assertEqual(
            missed, set(), f"AST parse missed real Environment members: {sorted(missed)}"
        )


class TestPinsAreLive(unittest.TestCase):
    def test_every_known_violation_still_exists(self):
        """A pin for a file or attribute that is gone silently widens tolerance."""
        report = esc.check()
        pinned = {(k.path, k.attr) for k in esc.KNOWN_VIOLATIONS}
        seen = {(r.path, r.attr) for r in report.known}
        self.assertEqual(
            pinned - seen,
            set(),
            "KNOWN_VIOLATIONS entries that no longer match any source line — "
            "remove them (the debt was paid) rather than leaving them to rot",
        )

    def test_known_violation_files_exist(self):
        for k in esc.KNOWN_VIOLATIONS:
            with self.subTest(path=k.path):
                self.assertTrue((esc.REPO_ROOT / k.path).is_file(), k.path)

    def test_every_pin_states_a_reason(self):
        for k in esc.KNOWN_VIOLATIONS:
            with self.subTest(path=k.path, attr=k.attr):
                self.assertGreater(len(k.reason.strip()), 40)


class TestRealTree(unittest.TestCase):
    def test_the_tree_is_currently_clean(self):
        report = esc.check()
        self.assertEqual(
            [(r.path, r.lineno, r.attr) for r in report.new],
            [],
            "new unsanctioned env reach — pin it or route it through a public accessor",
        )
        self.assertEqual(
            [(r.path, r.lineno, r.attr) for r in report.unknown_members],
            [],
            "a reached Environment member does not exist",
        )

    def test_components_reaches_env_for_nothing(self):
        """The runtime half of the orm-components-are-pure-python claim."""
        report = esc.check()
        self.assertEqual(
            [r for r in report.reaches if r.layer == "components"],
            [],
            "orm/components must be usable without an Environment",
        )

    def test_scope_paths_all_exist(self):
        for rel in esc.SCOPE:
            with self.subTest(rel=rel):
                self.assertTrue((esc.CORE / rel).exists(), f"SCOPE names a missing path: {rel}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
