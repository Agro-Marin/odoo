from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

import layer_check

from ._shared import (
    DOC,
    DOC_FLAT,
    ROOT,
    _imported_modules,
)


class TestSubsystemMap(unittest.TestCase):
    def _map_block(self) -> str:
        return DOC.split("## Subsystem map", 1)[1].split("```", 2)[1]

    def _modules_on_disk(self, package: str) -> set[str]:
        pkg = ROOT / "odoo" / package
        return {p.stem for p in pkg.glob("*.py") if p.stem != "__init__"} - {"tests"}

    def _listed_in(self, package: str, next_package: str) -> set[str]:

        block = self._map_block().split(f"── {package}/", 1)[1]
        block = block.split(f"── {next_package}/", 1)[0]
        body = block.split("\n", 1)[1]
        while True:
            stripped = re.sub(r"\([^()]*\)", " ", body)
            if stripped == body:
                break
            body = stripped
        body = re.sub(r"\[[^\]]*\]", " ", body)
        return set(re.findall(r"[A-Za-z_]\w*", body))

    def _assert_inventory(self, package: str, next_package: str) -> None:
        listed = self._listed_in(package, next_package)
        on_disk = self._modules_on_disk(package)
        self.assertEqual(
            set(),
            on_disk - listed,
            f"odoo/{package}/ has modules the subsystem map omits: "
            f"{sorted(on_disk - listed)}",
        )
        self.assertEqual(
            set(),
            listed - on_disk,
            f"the subsystem map lists odoo/{package}/ modules that do not exist: "
            f"{sorted(listed - on_disk)}",
        )

    def test_db_inventory(self) -> None:
        self._assert_inventory("db", "http")

    def test_http_inventory(self) -> None:
        self._assert_inventory("http", "service")

    def test_flat_packages_are_declared_flat(self) -> None:

        self.assertIn("**logical grouping, not a directory**", DOC_FLAT)
        for package in ("db", "http"):
            subpackages = [
                p.name
                for p in (ROOT / "odoo" / package).iterdir()
                if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"
            ]
            self.assertEqual(
                [],
                subpackages,
                f"odoo/{package}/ is no longer flat ({subpackages}); the map's "
                "'[brackets] are not directories' notation is now misleading",
            )


class TestContractTable(unittest.TestCase):
    def _table_rows(self) -> list[str]:
        section = DOC.split("## Enforced dependency rules", 1)[1]
        section = section.split("**The eight original boundaries", 1)[0]
        return re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.MULTILINE)

    def test_names_match_checker(self) -> None:

        rows = self._table_rows()
        self.assertEqual(len(rows), len(set(rows)), "duplicate row in the table")
        self.assertEqual(set(rows), {c.name for c in layer_check.CONTRACTS})

    def test_the_ownership_table_names_real_contracts_too(self) -> None:
        section = DOC.split("### Ownership and legal direction", 1)[1].split(
            "\n### ", 1
        )[0]
        named = set(re.findall(r"`([a-z][a-z0-9-]+)`\s*\|\s*$", section, re.MULTILINE))
        self.assertTrue(named, "the ownership table names no contract; regex rotted")
        unknown = sorted(named - {contract.name for contract in layer_check.CONTRACTS})
        self.assertEqual(
            [],
            unknown,
            f"the ownership table's Contract column promises a rule "
            f"`layer_check` does not define: {unknown}",
        )

    ORIGINAL_EIGHT = frozenset(
        {
            "libs-is-dependency-free",
            "db-is-orm-agnostic",
            "orm-components-are-pure-python",
            "orm-layer0-is-foundational",
            "orm-layer1-below-models-and-runtime",
            "orm-models-below-runtime",
            "orm-seams-stay-below-models-and-runtime",
            "facade-boundary",
        }
    )

    def test_stated_clean_count_matches_the_table(self) -> None:
        rows = self._table_rows()
        self.assertEqual(8, len(self.ORIGINAL_EIGHT))
        missing = self.ORIGINAL_EIGHT - set(rows)
        self.assertFalse(
            missing, f"original boundary dropped from the table: {missing}"
        )
        self.assertIn("**The eight original boundaries are clean at zero**", DOC)

    def test_later_contracts_are_also_in_the_table(self) -> None:

        rows = set(self._table_rows())
        later = {c.name for c in layer_check.CONTRACTS} - self.ORIGINAL_EIGHT
        self.assertTrue(later, "expected contracts beyond the original eight")
        self.assertFalse(later - rows, f"undocumented contract(s): {later - rows}")

    def test_components_row_admits_the_libs_exception(self) -> None:
        contract = next(
            c
            for c in layer_check.CONTRACTS
            if c.name == "orm-components-are-pure-python"
        )
        self.assertIn("odoo.libs", contract.allow)
        row = next(
            line
            for line in DOC.splitlines()
            if line.startswith("| `orm-components-are-pure-python`")
        )
        self.assertIn("except `odoo.libs`", row)

    def test_layer0_row_lists_the_real_source_modules(self) -> None:
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
        row = next(
            line
            for line in DOC.splitlines()
            if line.startswith("| `orm-layer0-is-foundational`")
        )
        for dotted in contract.source:
            self.assertIn(f"`{dotted.rsplit('.', 1)[-1]}`", row)


class TestLayerProse(unittest.TestCase):
    def _orm_imports(self, package: str) -> set[str]:
        pkg = ROOT / "odoo" / "orm" / package
        names: set[str] = set()
        for path in pkg.rglob("*.py"):
            if "tests" in path.relative_to(pkg).parts:
                continue
            names |= _imported_modules(path)
            names |= {
                f"odoo.orm.{m}"
                for m in re.findall(
                    r"^from \.+(\w+)", path.read_text(encoding="utf-8"), re.MULTILINE
                )
            }
        return names

    def test_the_table_admits_the_non_orm_imports(self) -> None:

        self.assertIn(
            'The invariant at every layer is "nothing from the ORM above it", '
            'not "nothing from `odoo`": all four import `odoo.tools`, '
            "`odoo.libs` and `odoo.exceptions` freely.",
            DOC_FLAT,
        )
        for package in ("fields", "domain", "models", "runtime"):
            with self.subTest(package=package):
                self.assertTrue(
                    any(i.startswith("odoo.tools") for i in self._orm_imports(package)),
                    f"orm/{package} no longer imports odoo.tools; the "
                    f"whole-table claim needs narrowing",
                )

    def test_layer1_really_avoids_components(self) -> None:
        self.assertIn("| Imports `components/` nowhere |", DOC)
        imports = self._orm_imports("fields") | self._orm_imports("domain")
        self.assertEqual(
            set(),
            {i for i in imports if "components" in i},
            "Layer 1 now imports orm/components; the bullet is wrong",
        )

    def test_layer2_components_dependency_is_named(self) -> None:
        self.assertIn("components.recompute.RecomputeScheduler", DOC_FLAT)
        src = (ROOT / "odoo" / "orm" / "models" / "mixins" / "recompute.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from ...components.recompute import RecomputeScheduler", src)

    def test_layer3_owns_the_component_instances(self) -> None:
        src = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        for cls in ("FieldCache", "ComputeEngine", "UnitOfWork", "OrmCore"):
            self.assertIn(f"`{cls}`", DOC, f"{cls} dropped from the Layer-3 bullet")
            self.assertIn(f"{cls}(", src, f"Transaction no longer constructs {cls}")


class TestPinnedViolations(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _new, cls.known = layer_check.check()

    def test_rule_count(self) -> None:
        stated = re.search(r"\*\*two pinned `KNOWN_VIOLATIONS`\s*\n?rules\*\*", DOC)
        self.assertIsNotNone(stated, "the pinned-rule count is no longer stated")
        self.assertEqual(2, len(layer_check.KNOWN_VIOLATIONS))

    def test_reported_edge_count(self) -> None:
        match = re.search(r"expands to \*\*(\d+) tolerated edges\*\*", DOC)
        self.assertIsNotNone(match, "the tolerated-edge count is no longer stated")
        self.assertEqual(
            int(match.group(1)),
            len(self.known),
            "ARCHITECTURE.md states a different tolerated-edge count than "
            "layer_check.check() reports",
        )

    def test_no_new_violations(self) -> None:
        new, _known = layer_check.check()
        self.assertEqual([], new, "ARCHITECTURE.md claims 0 new violations")

    def test_pinned_rules_are_scoped_to_service(self) -> None:
        self.assertIn("scoped to `odoo.service`", DOC_FLAT)
        for known in layer_check.KNOWN_VIOLATIONS:
            self.assertEqual("odoo.service", known.module)

    def test_tests_exemption_is_documented(self) -> None:
        self.assertIn("CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT", DOC_FLAT)
        self.assertEqual(
            {"tests"}, set(layer_check.CORE_PACKAGES_EXEMPT_FROM_ADDON_CONTRACT)
        )

    def test_test_files_are_really_skipped(self) -> None:
        self.assertIn("Test files are not scanned", DOC_FLAT)
        self.assertTrue(layer_check._is_test_file(Path("odoo/orm/tests/test_x.py")))
        self.assertTrue(layer_check._is_test_file(Path("odoo/db/conftest.py")))
        self.assertFalse(layer_check._is_test_file(Path("odoo/db/pool.py")))


class TestToolsReachesTheRuntime(unittest.TestCase):
    SOURCE = ROOT / "odoo" / "tools" / "files.py"

    def test_the_reach_count_is_live(self) -> None:
        self.assertIn(
            "reaches `env.transaction.file_open_tmp_paths` — the `file_open()` "
            "sandbox allowlist — at 4 sites",
            DOC_FLAT,
        )
        sites = self.SOURCE.read_text(encoding="utf-8").count(
            "transaction.file_open_tmp_paths"
        )
        self.assertEqual(
            4,
            sites,
            f"risks.md R2 says 4 tools/ reaches into the transaction; "
            f"files.py has {sites}",
        )

    def test_the_import_contract_really_is_clean(self) -> None:

        self.assertIn(
            "that contract is clean, because the reach arrives through `env` "
            "and produces no import edge",
            DOC_FLAT,
        )
        source = self.SOURCE.read_text(encoding="utf-8")
        for banned in ("from odoo.orm", "import odoo.orm"):
            self.assertNotIn(banned, source)


class TestToolsIsTheFacadeForLibs(unittest.TestCase):
    TOOLS = ROOT / "odoo" / "tools"

    @staticmethod
    def _import_sources(tree: ast.Module) -> dict[str, str]:
        sources: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                origin = "." * node.level + (node.module or "")
                for alias in node.names:
                    sources[alias.asname or alias.name] = origin
        return sources

    def _submodule(self, dotted: str) -> Path | None:
        stem = self.TOOLS / dotted.lstrip(".").replace(".", "/")
        for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def setUp(self) -> None:
        tree = ast.parse((self.TOOLS / "__init__.py").read_text(encoding="utf-8"))
        self.exported = [
            elt.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "__all__" for t in node.targets)
            for elt in node.value.elts
        ]
        self.top = self._import_sources(tree)

    def test_the_export_total_is_live(self) -> None:
        self.assertIn(f"of its {len(self.exported)} `__all__` symbols", DOC_FLAT)

    def test_the_direct_reexport_count_is_live(self) -> None:
        direct = {
            n for n in self.exported if self.top.get(n, "").startswith("odoo.libs")
        }
        self.assertIn(
            f"re-exports **{len(direct)} of its {len(self.exported)} `__all__` "
            f"symbols straight from `odoo.libs`**",
            DOC_FLAT,
        )
        for symbol in ("SQL", "float_round", "classproperty", "make_index_name"):
            self.assertIn(symbol, direct)

    def test_the_transitive_count_is_live(self) -> None:
        from_libs = set()
        for name in self.exported:
            origin = self.top.get(name, "")
            if origin.startswith("odoo.libs"):
                from_libs.add(name)
                continue
            if not origin.startswith("."):
                continue
            submodule = self._submodule(origin)
            if submodule is None:
                continue
            supplier = self._import_sources(
                ast.parse(submodule.read_text(encoding="utf-8"))
            )
            if supplier.get(name, "").startswith("odoo.libs"):
                from_libs.add(name)
        rest = len(self.exported) - len(from_libs)
        self.assertIn(
            f"**{len(from_libs)} of the {len(self.exported)} come from "
            f"`odoo.libs`**, the other {rest} arriving",
            DOC_FLAT,
        )
        self.assertGreater(
            len(from_libs),
            len(self.exported) // 2,
            "the section claims more than half the façade; it no longer is",
        )
        self.assertLessEqual({"html_escape", "single_email_re"}, from_libs)


class TestOrmDocstringAgreesWithGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        src = (ROOT / "odoo" / "orm" / "__init__.py").read_text(encoding="utf-8")
        cls.docstring = ast.get_docstring(ast.parse(src)) or ""

    def _section(self, heading: str) -> str:
        body = self.docstring.split(heading, 1)[1]
        return body.split("\n\n", 1)[0]

    def test_layer0_section_matches_the_contract(self) -> None:
        contract = next(
            c for c in layer_check.CONTRACTS if c.name == "orm-layer0-is-foundational"
        )
        expected = {dotted.rsplit(".", 1)[-1] for dotted in contract.source}
        section = self._section("Layer 0 — Zero-dependency foundations:")
        listed = set(re.findall(r"^  (\w+)\.py", section, re.MULTILINE))
        self.assertEqual(
            expected,
            listed,
            "orm/__init__.py's Layer 0 listing and the layer-0 contract disagree",
        )

    @staticmethod
    def _members_on_disk() -> set[str]:
        """Every orm member, spelled as the docstring's listing spells it."""
        orm = ROOT / "odoo" / "orm"
        members = {p.name for p in orm.glob("*.py") if p.stem != "__init__"}
        members |= {
            f"{p.name}/"
            for p in orm.iterdir()
            if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"
        }
        return members

    def _listed_entries(self) -> list[str]:
        return re.findall(r"^  (\w+\.py|\w+/)\s*$", self.docstring, re.MULTILINE)

    def test_every_orm_member_is_documented(self) -> None:
        undocumented = self._members_on_disk() - set(self._listed_entries())
        self.assertEqual(
            set(),
            undocumented,
            f"orm/__init__.py's docstring does not mention: {sorted(undocumented)}",
        )

    def test_no_member_is_listed_that_is_not_on_disk(self) -> None:
        stale = set(self._listed_entries()) - self._members_on_disk()
        self.assertEqual(
            set(),
            stale,
            f"orm/__init__.py lists {sorted(stale)}, which no longer exists; a "
            f"stale entry makes the index describe a tree that is not there",
        )

    def test_no_member_is_listed_twice(self) -> None:
        entries = self._listed_entries()
        duplicated = sorted({e for e in entries if entries.count(e) > 1})
        self.assertEqual(
            [],
            duplicated,
            f"{duplicated} listed more than once in orm/__init__.py; a module "
            f"classified into two layers means one of the two is wrong",
        )

    def test_the_page_names_the_tie_breaker(self) -> None:

        self.assertIn(
            "Where a doc and the gate differ, `layer_check.py`'s `CONTRACTS` "
            "wins — it is the definition that runs.",
            DOC_FLAT,
        )


class TestPinnedCyclesAndRemovals(unittest.TestCase):
    def test_pinned_cycles_are_the_ones_named(self) -> None:

        import py_cycle_check

        report = py_cycle_check.check()
        known = getattr(report, "known", None) or report.cycles
        measured = {" <-> ".join(cycle) for cycle in known}

        count = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}[len(measured)]
        anchor = f"{count} are pinned, all the benign"
        self.assertIn(anchor, DOC, "module.md does not state the measured count")
        block = DOC.split(anchor, 1)[1]
        block = block.split("```", 2)[1]
        listed = {
            " <-> ".join(part.strip() for part in line.split("<->"))
            for line in block.strip().splitlines()
            if line.strip()
        }
        self.assertEqual(
            measured,
            listed,
            "the pinned cycles in module.md and py_cycle_check disagree",
        )
        self.assertIn(anchor, DOC_FLAT)

    def test_the_orm_really_has_no_cycle(self) -> None:
        import py_cycle_check

        report = py_cycle_check.check()
        orm = [c for c in report.cycles if any(m.startswith("odoo.orm") for m in c)]
        self.assertEqual(orm, [], "the ORM has a cycle; the page says it has none")
        self.assertIn("**The ORM has none.**", DOC_FLAT)

    def test_the_removed_table_is_why_scoping_is_needed(self) -> None:
        readme = ROOT / "odoo" / "_monkeypatches" / "README.md"
        section = readme.read_text(encoding="utf-8").split("## Recently Removed", 1)[1]
        section = section.split("\n## ", 1)[0]
        rows = re.findall(r"^\| `([\w.]+\.py)`", section, re.MULTILINE)
        self.assertTrue(rows, "the Recently Removed table is gone or reshaped")

        gone = [
            name
            for name in rows
            if not (ROOT / "odoo" / "_monkeypatches" / name).exists()
        ]
        still_there = [name for name in rows if name not in gone]

        self.assertTrue(
            gone,
            "no row names a file that is actually gone, so an unscoped scan "
            "would not misreport anything and the page's reason for scoping to "
            "a section no longer holds — rewrite it or retire the gate",
        )
        self.assertTrue(
            still_there,
            "no row retires a patch from a file that survives, so the page's "
            "'others retire a patch from a file that is still there' is stale",
        )
        self.assertIn("Recently Removed", DOC)

    def test_the_backtick_note_is_not_reinstated(self) -> None:
        readme = (ROOT / "odoo" / "_monkeypatches" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("| `urllib3.py` |", readme)
        self.assertNotIn("Those names are quoted rather than backticked", DOC_FLAT)


class TestEdgeCountConventions(unittest.TestCase):
    TIERS = {
        "db": {
            "connectivity": [
                "pool",
                "cursor",
                "ddl",
                "schema",
                "savepoint",
                "schema_cache",
                "bulk",
                "lifecycle",
                "errors",
                "dsn",
                "utils",
            ],
            "resilience": [
                "breaker",
                "lag",
                "budget",
                "leaks",
                "reaper",
                "metrics",
                "stats",
            ],
        },
        "http": {
            "serving": [
                "application",
                "dispatcher",
                "routing",
                "session",
                "request_class",
                "_serve",
                "_response",
                "wrappers",
                "stream",
                "_csrf",
                "controller",
                "core",
            ],
            "features": [
                "openapi",
                "_params",
                "geoip",
                "constants",
                "exceptions",
                "_protocols",
                "helpers",
            ],
        },
    }

    def _edges(self, package: str, per_symbol: bool) -> dict[tuple[str, str], int]:
        groups = self.TIERS[package]
        of = {mod: tier for tier, mods in groups.items() for mod in mods}
        counted: dict[tuple[str, str], int] = {}
        for path in sorted((ROOT / "odoo" / package).glob("*.py")):
            here = of.get(path.stem)
            if here is None:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            deferred: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(
                    node.test
                ):
                    deferred |= {id(inner) for inner in ast.walk(node)}
            for node in ast.walk(tree):
                if id(node) in deferred or not isinstance(node, ast.ImportFrom):
                    continue
                if node.level == 1 and node.module:
                    targets = [node.module.split(".")[0]]
                elif node.level == 1:
                    targets = [alias.name for alias in node.names]
                elif node.module and node.module.startswith(f"odoo.{package}."):
                    targets = [node.module.split(".")[2]]
                else:
                    continue
                for target in targets:
                    there = of.get(target)
                    if there is None or there == here:
                        continue
                    key = (here, there)
                    counted[key] = counted.get(key, 0) + (
                        len(node.names) if per_symbol else 1
                    )
        return counted

    def test_db_figures_are_per_symbol(self) -> None:
        edges = self._edges("db", per_symbol=True)
        self.assertEqual(edges[("connectivity", "resilience")], 6)
        self.assertEqual(edges[("resilience", "connectivity")], 1)
        self.assertIn("had 6 connectivity", DOC_FLAT)
        self.assertIn("counting imported *symbols*", DOC_FLAT)

    def test_http_figures_are_per_statement_and_the_symbol_count_is_given(self) -> None:
        per_statement = self._edges("http", per_symbol=False)
        per_symbol = self._edges("http", per_symbol=True)
        self.assertEqual(per_statement[("serving", "features")], 22)
        self.assertEqual(per_statement[("features", "serving")], 1)
        self.assertIn("22 serving", DOC_FLAT)
        self.assertIn(
            f"by symbol it is {per_symbol[('serving', 'features')]} against "
            f"{per_symbol[('features', 'serving')]}",
            DOC_FLAT,
        )
