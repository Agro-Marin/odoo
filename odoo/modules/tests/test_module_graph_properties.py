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
    def __init__(self, rows):
        self.rows = rows
        self._out = []
        self.rowcount = 0

    def execute(self, query, params=None):
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
        declared[names[i]] = rng.sample(names, count)
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
