from __future__ import annotations

import ast
import re
import unittest

import _doc_measures

from ._shared import (
    DOC,
    DOC_FLAT,
    ROOT,
)


class TestFilestoreLayout(unittest.TestCase):
    @staticmethod
    def _lengths_by_tag() -> dict[str, int]:
        src = (ROOT / "odoo" / "libs" / "hashing.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "CONTENT_DIGEST_LEN_BY_TAG"
                for t in node.targets
            ):
                return {
                    k.value: v.value
                    for k, v in zip(node.value.keys, node.value.values, strict=True)
                }
        raise AssertionError("CONTENT_DIGEST_LEN_BY_TAG is gone from libs/hashing.py")

    def test_each_tag_row_states_its_real_digest_length(self) -> None:
        lengths = self._lengths_by_tag()
        self.assertEqual({"s1", "b3"}, set(lengths), "the tag set changed")
        for tag, length in sorted(lengths.items()):
            with self.subTest(tag=tag):
                row = next(
                    (ln for ln in DOC.splitlines() if ln.startswith(f"| `{tag}` ")),
                    None,
                )
                self.assertIsNotNone(row, f"data.md has no row for tag {tag}")
                self.assertEqual(
                    str(length),
                    row.rsplit("|", 2)[1].strip(),
                    f"the {tag} row's digest length disagrees with "
                    f"CONTENT_DIGEST_LEN_BY_TAG",
                )

    def test_the_tag_is_still_chosen_by_an_optional_dependency(self) -> None:
        src = (ROOT / "odoo" / "libs" / "hashing.py").read_text(encoding="utf-8")
        self.assertIn('ALGO_TAG = "b3" if HAS_BLAKE3 else "s1"', src)
        self.assertIn("depends on an optional dependency", DOC_FLAT)


class TestSignallingTables(unittest.TestCase):
    @staticmethod
    def _cache_keys() -> list[str]:
        source = (ROOT / "odoo" / "tools" / "constants.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == "CACHES_BY_KEY"
                for target in node.targets
            ):
                return [key.value for key in node.value.keys]
        raise AssertionError("CACHES_BY_KEY is gone from odoo/tools/constants.py")

    def test_the_table_count_is_the_keys_plus_the_registry(self) -> None:
        keys = self._cache_keys()
        self.assertTrue(keys, "CACHES_BY_KEY is empty; the walk rotted")
        expected = _doc_measures.number_word(len(keys) + 1).capitalize()
        self.assertIn(
            f"{expected} tables, one for the registry and one for each key",
            DOC_FLAT,
            f"{len(keys)} cache keys plus the registry is {len(keys) + 1} "
            f"signalling tables, and the data view says otherwise",
        )

    def test_every_cache_key_is_named(self) -> None:
        keys = self._cache_keys()
        listed = re.search(r"one for each key in `CACHES_BY_KEY` \(([^)]*)\)", DOC_FLAT)
        self.assertIsNotNone(listed, "the key list is no longer on the page")
        named = re.findall(r"`([\w.]+)`", listed.group(1))
        self.assertEqual(
            keys,
            named,
            "the data view's cache-key list and CACHES_BY_KEY disagree",
        )

    def test_the_runtime_derives_the_tables_rather_than_listing_them(self) -> None:
        registry = (
            ROOT / "odoo" / "orm" / "runtime" / "_registry_signaling.py"
        ).read_text(encoding="utf-8")
        self.assertIn('for cache_name in ["registry", *CACHES_BY_KEY]', registry)


class TestDeploymentLimits(unittest.TestCase):
    CONFIG = ROOT / "odoo" / "tools" / "config.py"
    SERVICE = ROOT / "odoo" / "service"

    @staticmethod
    def _literal(node: ast.AST) -> object:
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Mult, ast.Add, ast.Pow)
        ):
            left = TestDeploymentLimits._literal(node.left)
            right = TestDeploymentLimits._literal(node.right)
            if isinstance(left, int) and isinstance(right, int):
                if isinstance(node.op, ast.Mult):
                    return left * right
                return left + right if isinstance(node.op, ast.Add) else left**right
            return None
        try:
            return ast.literal_eval(node)
        except ValueError, SyntaxError:
            return None

    def _defaults(self) -> dict[str, object]:
        tree = ast.parse(self.CONFIG.read_text(encoding="utf-8"))
        found: dict[str, object] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            dest = kwargs.get("dest")
            if isinstance(dest, ast.Constant) and "my_default" in kwargs:
                found[dest.value] = self._literal(kwargs["my_default"])
        return found

    def _table(self) -> dict[str, str]:
        section = DOC.split("## The limits that end a request or a worker", 1)[1]
        section = re.split(r"^## ", section, maxsplit=1, flags=re.MULTILINE)[0]
        rows = re.findall(r"^\| `(\w+)` \| `?([^|`]+?)`? \|", section, re.MULTILINE)
        return {name: value.strip() for name, value in rows}

    def test_the_soft_hard_gap_is_derived(self) -> None:

        defaults = self._defaults()
        soft = defaults["limit_memory_soft"]
        hard = defaults["limit_memory_hard"]
        self.assertIsInstance(soft, int)
        self.assertIsInstance(hard, int)
        gap = (hard - soft) // 1024 // 1024
        self.assertIn(
            f"sized on the {gap} MB between the two",
            DOC_FLAT,
            f"the stated soft/hard gap disagrees with config.py ({gap} MB)",
        )

    KNOB_FAMILY = ("workers", "max_cron_threads", "db_maxconn")

    def test_the_resilience_table_is_the_whole_tier(self) -> None:
        import layer_check

        contract = next(
            c
            for c in layer_check.CONTRACTS
            if c.name == "db-resilience-below-connectivity"
        )
        tier = {module.rsplit(".", 1)[-1] + ".py" for module in contract.source}
        section = DOC.split("## Degradation", 1)[1].split("\n## ", 1)[0]
        listed = set(re.findall(r"^\| `([\w.]+\.py)` \|", section, re.MULTILINE))
        self.assertEqual(
            tier,
            listed,
            f"the deployment view's resilience table and the contract that "
            f"defines the tier disagree — missing from the page: "
            f"{sorted(tier - listed)}; on the page and not in the tier: "
            f"{sorted(listed - tier)}",
        )

    def test_the_table_lists_every_knob_in_the_family(self) -> None:
        family = {
            knob
            for knob in self._defaults()
            if knob.startswith("limit_") or knob in self.KNOB_FAMILY
        }
        self.assertTrue(family, "config.py declares no such knob; the walk rotted")
        missing = sorted(family - set(self._table()))
        self.assertEqual(
            [],
            missing,
            f"config.py declares knob(s) the deployment view does not list, so a "
            f"reader sizing on that table is sizing on a subset: {missing}",
        )

    def test_every_stated_default_matches_config(self) -> None:
        defaults = self._defaults()
        table = self._table()
        self.assertGreaterEqual(len(table), 8, "the knob table lost its rows")
        for knob, stated in table.items():
            self.assertIn(knob, defaults, f"{knob} is not a config option")
            actual = defaults[knob]
            if stated.endswith("MB"):
                actual //= 1024 * 1024
                stated = stated.removesuffix(" MB")
            stated = stated.removesuffix(" s")
            self.assertEqual(
                str(actual), stated, f"{knob}: page says {stated}, config says {actual}"
            )

    def test_only_the_soft_memory_limit_is_enforced(self) -> None:
        gevent_twins = ("limit_memory_soft_gevent", "limit_memory_hard_gevent")
        read_by = {
            option: sorted(
                p.name
                for p in self.SERVICE.rglob("*.py")
                if f'config["{option}"]' in p.read_text(encoding="utf-8")
            )
            for option in ("limit_memory_soft", "limit_memory_hard", *gevent_twins)
        }
        for twin in gevent_twins:
            self.assertIn(f"`{twin}`", DOC, f"{twin} is a knob no page lists")
        self.assertTrue(
            read_by["limit_memory_soft"], "nothing enforces the soft limit either"
        )
        for unenforced in ("limit_memory_hard", *gevent_twins):
            if unenforced == "limit_memory_soft_gevent":
                continue
            self.assertEqual(
                [],
                read_by[unenforced],
                f"odoo/service/ enforces {unenforced} again; the deployment view "
                f"says nothing does",
            )
        self.assertIn("enforced by nothing in-process", DOC_FLAT)
        self.assertIn(
            f"There is one memory limit, not one of {_doc_measures.number_word(len(gevent_twins) + 2)}",
            DOC_FLAT,
        )
        self.assertIn(
            "not enforced in-process", self.CONFIG.read_text(encoding="utf-8")
        )
