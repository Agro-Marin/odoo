"""The graph's contract, re-derived on random graphs rather than sampled.

`test_module_graph.py` pins hand-written examples. What it cannot state is the
property those examples are examples *of*: whatever the manifests say, whatever
the database says, and in whatever order `extend` is fed, a module must be
iterated after every module it depends on, and nothing unloadable may survive.
That contract is what `load_module_graph` walks, and the ordering behind it is
subtle enough to deserve more than samples -- `test_` modules deliberately take
their deepest dependency's `depth` instead of one more than it, so their place
is decided by a space-prefixed `order_name` and not by depth at all.

The generator drives the real `_update_from_database` and the real
`_imported_modules` through a fake cursor, in both graph modes, over manifests
that may be uninstallable, dependency sets that may contain cycles or a
self-reference, and three-way incremental `extend` calls.

The harness was mutation-checked against four injected faults before being
committed, because a property test that cannot fail asserts nothing. Over 8000
seeds: making `_update_from_database` keep DB-uninstallable modules fails 1049
seeds, making load mode keep not-installed modules fails 1008, stopping
`_remove` from cascading to dependents fails 2893, and dropping `depth` from the
sort key fails 174. Each is caught by the invariant it breaks.

That third mutant also shows what defends `ModuleNode.order_name`, `depth` and
`phase`, whose `max()` calls have no empty-sequence guard: it is the removal
cascade, not the manifest loader. With the cascade disabled the fuzz reaches
`ValueError: max() iterable argument is empty` at `module_graph.py`'s `depth`.
"""

import logging
import random
import unittest
from unittest.mock import patch

from odoo.modules.module import _DEFAULT_MANIFEST, Manifest
from odoo.modules.module_graph import ModuleGraph

BaseCase = unittest.TestCase

SEEDS = 600
"""Enough to exercise the shapes; the whole file runs in about a second.

Not a target -- the mutation figures above were taken at 8000. Raise it locally
when changing `ModuleNode`'s ordering or `_remove`'s cascade.
"""

DB_STATES = (
    "installed",
    "to install",
    "to upgrade",
    "to remove",
    "uninstalled",
    "uninstallable",
)


class _FakeCursor:
    """Answers `column_exists`, the imported-modules query and the state query."""

    def __init__(self, rows):
        self.rows = rows
        self._out = []
        self.rowcount = 0

    def execute(self, query, params=None):
        # `column_exists` passes an `SQL` object, whose `in` support is
        # deprecated; read its `code` the way a real cursor does.
        text = query.code if hasattr(query, "code") else query
        if "information_schema" in text or "pg_attribute" in text:
            self._out = [("imported",)]
        elif "imported" in text:
            self._out = [(name,) for name, row in self.rows.items() if row["imported"]]
        else:
            wanted = set(params[0]) if params else set()
            self._out = [
                (name, row["id"], row["state"], row["demo"], row["db_version"])
                for name, row in self.rows.items()
                if name in wanted
            ]
        self.rowcount = len(self._out)

    def fetchall(self):
        return self._out

    def fetchone(self):
        return self._out[0] if self._out else None


def _random_graph(seed):
    rng = random.Random(seed)
    size = rng.randint(3, 14)
    names = ["base"] + [
        ("test_" if rng.random() < 0.3 else "mod_") + f"{i:03d}" for i in range(1, size)
    ]
    declared: dict[str, list[str]] = {"base": []}
    for i in range(1, size):
        count = rng.randint(1, min(3, len(names)))
        declared[names[i]] = rng.sample(names, count)  # may self-reference or cycle
    installable = {name: rng.random() > 0.12 for name in names}
    installable["base"] = True
    rows = {
        name: {
            "id": index + 1,
            "state": rng.choice(DB_STATES),
            "demo": rng.random() < 0.5,
            "db_version": "19.0.1.0",
            "imported": rng.random() < 0.1,
        }
        for index, name in enumerate(names)
    }
    rows["base"] = {
        "id": 1,
        "state": "installed",
        "demo": False,
        "db_version": "19.0.1.0",
        "imported": False,
    }
    order = list(names)
    rng.shuffle(order)
    mode = rng.choice(["load", "update"])
    return names, declared, installable, rows, order, mode


def _effective_depends(name, declared):
    """What `_load_manifest` will make of a declared `depends` list."""
    depends = [dep for dep in declared[name] if dep != name]
    if name == "base":
        return []
    return depends or ["base"]


def _build(declared, installable, rows, order, mode):
    def make_manifest(name, **_kwargs):
        if name not in declared:
            return None
        return Manifest(
            path="/dummy/" + name,
            manifest_content=dict(
                _DEFAULT_MANIFEST,
                author="t",
                license="LGPL-3",
                depends=_effective_depends(name, declared),
                installable=installable.get(name, True),
            ),
        )

    with patch("odoo.modules.module_graph.Manifest.for_addon", make_manifest):
        graph = ModuleGraph(_FakeCursor(rows), mode=mode)
        graph.extend(["base"])
        graph.extend(order[: len(order) // 2])
        graph.extend(order[len(order) // 2 :])
        return [package.name for package in graph]


class TestGraphProperties(BaseCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def _check(self, seed):
        _names, declared, installable, rows, order, mode = _random_graph(seed)
        sequence = _build(declared, installable, rows, order, mode)
        position = {name: index for index, name in enumerate(sequence)}
        context = f"seed {seed}, mode {mode}: {declared}"

        for name in sequence:
            for dep in _effective_depends(name, declared):
                self.assertIn(dep, position, f"survivor without dependency; {context}")
                self.assertLess(
                    position[dep],
                    position[name],
                    f"{name} iterated before its dependency {dep}; {context}",
                )
            self.assertTrue(
                installable.get(name, True),
                f"manifest-uninstallable {name} survived; {context}",
            )
            self.assertNotEqual(
                rows[name]["state"],
                "uninstallable",
                f"database-uninstallable {name} survived; {context}",
            )
            if mode == "load":
                self.assertNotIn(
                    rows[name]["state"],
                    ("to install", "uninstalled"),
                    f"not-installed {name} survived a load-mode graph; {context}",
                )

    def test_the_iteration_order_and_removals_hold_over_random_graphs(self):
        for seed in range(SEEDS):
            self._check(seed)

    def test_the_generator_actually_produces_the_shapes_it_claims(self):
        # A property run over degenerate inputs proves nothing; assert the
        # corpus contains what the invariants are meant to be tested against.
        saw = {"cycle": 0, "self_dep": 0, "uninstallable": 0, "test_module": 0}
        modes = set()
        for seed in range(SEEDS):
            names, declared, installable, _rows, _order, mode = _random_graph(seed)
            modes.add(mode)
            if any(name in declared[name] for name in names):
                saw["self_dep"] += 1
            if any(not value for value in installable.values()):
                saw["uninstallable"] += 1
            if any(name.startswith("test_") for name in names):
                saw["test_module"] += 1
            if any(
                any(name in declared[dep] for dep in declared[name] if dep in declared)
                for name in names
            ):
                saw["cycle"] += 1
        self.assertEqual(modes, {"load", "update"})
        for shape, count in saw.items():
            self.assertGreater(count, 10, f"the corpus barely contains {shape}: {saw}")
