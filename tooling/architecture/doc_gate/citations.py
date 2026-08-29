from __future__ import annotations

import ast
import re
import unittest

import _doc_measures
import js_layer_check
import layer_check

from ._shared import (
    DOC,
    DOC_FLAT,
    DOC_PATH,
    DOC_PATHS,
    NUMBER_WORDS,
    ROOT,
    _rule_table_gates,
)


class TestReferencedArtifacts(unittest.TestCase):
    def test_adrs_exist(self) -> None:
        adr_dir = ROOT / "doc" / "adr"
        numbers = sorted(set(re.findall(r"ADR-(\d{4})", DOC)))
        self.assertTrue(numbers, "the page cites no ADR; the pattern has rotted")
        for number in numbers:
            self.assertTrue(
                list(adr_dir.glob(f"{number}-*.md")),
                f"ARCHITECTURE.md references ADR-{number}, which does not exist",
            )

    def test_adr_range_is_complete(self) -> None:

        match = re.search(r"architecture decisions, (\d{4})–(\d{4})", DOC)
        self.assertIsNotNone(match, "the ADR range is no longer stated")
        on_disk = sorted(
            p.name[:4] for p in (ROOT / "doc" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")
        )
        self.assertEqual((match.group(1), match.group(2)), (on_disk[0], on_disk[-1]))

    def test_documented_commands_exist(self) -> None:
        scripts = re.findall(r"^python (\S+\.py)", DOC, re.MULTILINE)
        self.assertTrue(
            scripts, "the page documents no command; the pattern has rotted"
        )
        for script in scripts:
            self.assertTrue(
                (ROOT / script).is_file(),
                f"ARCHITECTURE.md documents `python {script}`, which is missing",
            )

    def test_referenced_workflows_exist(self) -> None:
        workflows = re.findall(r"`\.github/workflows/([\w.-]+\.yml)`", DOC)
        self.assertTrue(
            workflows, "the page references no workflow; the pattern has rotted"
        )
        for wf in workflows:
            self.assertTrue((ROOT / ".github" / "workflows" / wf).is_file(), wf)

    def test_ci_gate_table_matches_the_workflow(self) -> None:

        run_in_ci = set(_doc_measures.workflow_gates())
        section = DOC.split("## Quality gates beyond the boundaries", 1)[1]
        tabled = set(re.findall(r"^\| `(\w+\.py)` \|", section, re.MULTILINE))
        self.assertEqual(tabled, run_in_ci)

        stated = re.search(r"workflow runs \*\*([\w-]+)\*\* blocking checkers", DOC)
        self.assertIsNotNone(stated, "the gate count is no longer stated")
        self.assertEqual(NUMBER_WORDS[stated.group(1)], len(run_in_ci))

    def test_ci_path_filter_covers_every_scanned_tree(self) -> None:

        workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
            encoding="utf-8"
        )
        pr_block = workflow.split("pull_request:", 1)[1].split("permissions:", 1)[0]
        globs = re.findall(r"^\s*- '([^']+)'", pr_block, re.MULTILINE)
        self.assertTrue(globs, "the pull_request path filter is empty")

        def to_regex(glob: str) -> re.Pattern[str]:
            out, i = [], 0
            while i < len(glob):
                if glob.startswith("**/", i):
                    out.append("(?:.*/)?")
                    i += 3
                elif glob.startswith("**", i):
                    out.append(".*")
                    i += 2
                elif glob[i] == "*":
                    out.append("[^/]*")
                    i += 1
                elif glob[i] == "?":
                    out.append("[^/]")
                    i += 1
                else:
                    out.append(re.escape(glob[i]))
                    i += 1
            return re.compile("^" + "".join(out) + "$")

        patterns = [to_regex(g) for g in globs]

        def covered(path: str) -> bool:
            return any(p.match(path) for p in patterns)

        uncovered: list[str] = []
        for tree in ("odoo", "addons"):
            root = ROOT / tree
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if child.name.startswith((".", "__")):
                    continue
                if child.is_dir():
                    if not any(child.rglob("*.py")):
                        continue
                    probe = f"{tree}/{child.name}/probe.py"
                elif child.suffix == ".py":
                    probe = f"{tree}/{child.name}"
                else:
                    continue
                if not covered(probe):
                    uncovered.append(probe)

        self.assertEqual(
            uncovered,
            [],
            "these scanned paths would not retrigger architecture.yml on a PR: "
            + ", ".join(uncovered),
        )

    def test_cross_repo_checker_is_a_prepush_hook(self) -> None:
        self.assertIn("pre-commit install --hook-type pre-push", DOC_FLAT)
        config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertIn("cross_repo_coherence.py", config)
        self.assertIn("stages: [pre-push]", config)
        workflow = (ROOT / ".github" / "workflows" / "architecture.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "python tooling/architecture/cross_repo_coherence.py",
            workflow,
            "cross_repo_coherence.py now runs in CI; the page says it does not",
        )

    def test_integration_gate_exclusions_are_stated(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "integration_tests.yml").read_text(
            encoding="utf-8"
        )
        tags = re.search(r"TEST_TAGS: (\S+)", workflow)
        self.assertIsNotNone(tags, "integration_tests.yml no longer sets TEST_TAGS")
        excluded = re.findall(r"-:(\w+)", tags.group(1))
        self.assertTrue(excluded, "no exclusions left; simplify the prose")
        for name in excluded:
            self.assertIn(
                name, DOC, f"the base suite excludes {name}; the page does not say so"
            )

    SIBLING_DRIVEN = {
        "py_x2many_count_enterprise": "enterprise",
        "py_x2many_count_agromarin": "agromarin",
        "sql_in_placeholder_enterprise": "enterprise",
        "sql_in_placeholder_agromarin": "agromarin",
        "py_count_as_boolean_enterprise": "enterprise",
        "py_count_as_boolean_agromarin": "agromarin",
        "py_shadowed_member_enterprise": "enterprise",
        "py_shadowed_member_agromarin": "agromarin",
        "py_shadowed_member_design-themes": "design-themes",
        "unresolved_calls_enterprise": "enterprise",
        "unresolved_calls_agromarin": "agromarin",
        "orderlineqty_enterprise": "enterprise",
        "orderlineqty_agromarin": "agromarin",
        "orderlineqty_design-themes": "design-themes",
        "naming_enterprise": "enterprise",
        "naming_agromarin": "agromarin",
        "naming_design-themes": "design-themes",
    }

    SIBLING_PY_LINT_SCOPES = frozenset({"enterprise", "agromarin", "design-themes"})

    @staticmethod
    def _gates_the_workflows_drive() -> set[str]:
        driven: set[str] = set()
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            driven.update(
                re.findall(
                    r"ratchet\.py (\w+)(?: --mode [\w-]+)? --count",
                    workflow.read_text(encoding="utf-8"),
                )
            )
        return driven

    @staticmethod
    def _gates_test_lint_drives(on_disk: set[str]) -> set[str]:
        names: set[str] = set()
        tests = ROOT / "odoo" / "addons" / "test_lint" / "tests"
        for path in tests.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                arguments = list(node.args) + [kw.value for kw in node.keywords]
                names.update(
                    argument.value
                    for argument in arguments
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                )
        return (names | _rule_table_gates(tests)) & on_disk

    def _gates_sibling_py_lint_drives(self, on_disk: set[str]) -> set[str]:
        return {
            name
            for name in on_disk
            if name.startswith("lint_")
            and any(name.endswith(f"_{scope}") for scope in self.SIBLING_PY_LINT_SCOPES)
        }

    def test_a_sibling_driven_baseline_is_driven_by_its_sibling(self) -> None:
        siblings = ROOT.parent
        checked = 0
        for gate, repo in self.SIBLING_DRIVEN.items():
            workflow = siblings / repo / ".github" / "workflows" / "architecture.yml"
            if not workflow.is_file():
                continue
            checked += 1
            self.assertRegex(
                workflow.read_text(encoding="utf-8"),
                rf"ratchet\.py\s*\\?\s*{re.escape(gate)}\s+--mode\s+no-increase\s+--count",
                f"{gate} is exempted here as driven by {repo}, and {repo}'s "
                f"architecture.yml does not drive it as a no-increase ratchet",
            )
        if not checked:
            self.skipTest("no sibling checkout beside this one")

    def test_ratchet_baselines_match_documented_gates(self) -> None:
        match = re.search(
            r"turns ([\w-]+) tool\s+counts into one-way contracts: "
            r"\*\*([^*]+)\*\*",
            DOC,
        )
        self.assertIsNotNone(match, "the ratchet gate list is no longer stated")
        listed = {n.strip() for n in match.group(2).replace(" and ", ", ").split(",")}
        on_disk = {
            p.stem for p in (ROOT / "tooling" / "ratchet" / "baselines").glob("*.json")
        }
        driven = (
            self._gates_the_workflows_drive()
            | set(self.SIBLING_DRIVEN)
            | self._gates_test_lint_drives(on_disk)
            | self._gates_sibling_py_lint_drives(on_disk)
        )
        self.assertTrue(driven, "no workflow drives ratchet.py; the regex has rotted")
        self.assertEqual(
            driven,
            on_disk,
            "a baseline exists that no workflow drives, or a workflow drives a "
            "gate with no baseline",
        )
        self.assertEqual(listed, on_disk, "the page's gate list is stale")
        self.assertEqual(
            NUMBER_WORDS[match.group(1)],
            len(on_disk),
            "the ratchet gate list and the count in front of it disagree",
        )

    def test_named_source_paths_exist(self) -> None:

        pattern = r"`((?:odoo|tooling|doc|addons|libs|orm|db|http|service)/[\w./-]+?)`"
        found = sorted(set(re.findall(pattern, DOC)))
        self.assertTrue(found, "the page names no path; the pattern has rotted")
        for raw in found:
            if "*" in raw or raw.endswith("/"):
                continue
            candidates = [ROOT / raw, ROOT / "odoo" / raw]
            candidates += [c.with_suffix(".py") for c in list(candidates)]
            self.assertTrue(
                any(c.exists() for c in candidates),
                f"ARCHITECTURE.md names `{raw}`, which does not exist "
                f"(tried repo-relative and odoo/-relative)",
            )


class TestTheFrontDoorIndexes(unittest.TestCase):
    def test_the_view_index_lists_every_page(self) -> None:
        section = DOC.split("## The views", 1)[1].split("\n## ", 1)[0]
        linked = set(re.findall(r"\[`([\w.]+\.md)`\]\(([\w.]+\.md)\)", section))
        named = {target for _label, target in linked}
        pages = {path.name for path in DOC_PATHS} - {DOC_PATH.name}
        self.assertEqual(
            pages,
            named,
            f"the front door's view index and doc/architecture/ disagree — "
            f"missing from the index: {sorted(pages - named)}; indexed and "
            f"absent from disk: {sorted(named - pages)}",
        )
        for label, target in linked:
            self.assertEqual(
                label, target, "a view row's link text and target disagree"
            )

    def test_every_row_of_where_to_add_code_names_a_real_gate(self) -> None:
        section = DOC.split("## Where to add code", 1)[1].split("\n# ", 1)[0]
        caught = {
            name
            for row in re.findall(
                r"^\|(?:[^|]*\|){3}([^|]*)\|\s*$", section, re.MULTILINE
            )
            for name in re.findall(r"`([\w.-]+)`", row)
        }
        self.assertTrue(caught, "the placement table names no gate; the regex rotted")
        contracts = {contract.name for contract in layer_check.CONTRACTS}
        scripts = {
            path.name for path in (ROOT / "tooling" / "architecture").glob("*.py")
        }
        unknown = sorted(
            name for name in caught if name not in contracts and name not in scripts
        )
        self.assertEqual(
            [],
            unknown,
            f"the placement table promises a rule is caught by something that "
            f"is neither a layer_check contract nor a checker in "
            f"tooling/architecture/: {unknown}",
        )


class TestCitationsResolve(unittest.TestCase):
    TOOLING = ROOT / "tooling" / "architecture"

    def test_every_named_checker_is_where_the_pages_say_it_is(self) -> None:
        here = {path.name for path in self.TOOLING.glob("*.py")}
        gates = set(_doc_measures.workflow_gates()) | {
            f"{gate}.py" for gate in _doc_measures.self_test_only_gates()
        }
        named = {name for name in re.findall(r"`([\w.]+\.py)`", DOC) if name in gates}
        self.assertTrue(named, "the pages name no gate; the regex has rotted")
        elsewhere = sorted(name for name in named if name not in here)
        self.assertEqual(
            [],
            elsewhere,
            f"named as a gate and not in tooling/architecture/, so the "
            f"`python tooling/architecture/<name>` beside it cannot run: "
            f"{elsewhere}",
        )

    ILLUSTRATIONS = {"pre_01.py", "Pre-01.py"}

    @staticmethod
    def _every_source_path() -> tuple[set[str], set[str]]:
        skip = {".git", "node_modules", "__pycache__", "target"}
        paths = {
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*.py")
            if not skip & set(path.parts)
        }
        return paths, {path.rsplit("/", 1)[-1] for path in paths}

    def test_every_backticked_python_file_exists(self) -> None:
        paths, basenames = self._every_source_path()
        named = set(re.findall(r"`([\w./-]+\.py)`", DOC))
        self.assertTrue(named, "the pages name no python file; the regex has rotted")
        missing = sorted(
            name
            for name in named - self.ILLUSTRATIONS
            if not (
                any(path == name or path.endswith("/" + name) for path in paths)
                if "/" in name
                else name in basenames
            )
        )
        self.assertEqual(
            [],
            missing,
            f"backticked on a page and absent from the tree: {missing}",
        )
        stale = sorted(self.ILLUSTRATIONS - named)
        self.assertEqual(
            [],
            stale,
            f"exempted as a hypothetical name and no longer on any page: {stale}",
        )
        for illustration in self.ILLUSTRATIONS:
            self.assertNotIn(
                illustration,
                basenames,
                f"{illustration} exists now, so it is a citation rather than an "
                f"illustration and does not need the exemption",
            )

    def test_line_number_citations_resolve(self) -> None:

        pattern = r"`([\w/]+\.py):(\d+)`"
        self.assertTrue(
            re.findall(pattern, "see `orm/models/base.py:302` for the hook"),
            "the citation regex no longer matches a citation; it has rotted",
        )
        for name, lineno in re.findall(pattern, DOC):
            target = ROOT / "odoo" / name
            self.assertTrue(
                target.is_file(),
                f"`{name}:{lineno}` does not resolve under odoo/; a line "
                f"citation must carry enough path to be unambiguous",
            )
            lines = target.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(
                len(lines),
                int(lineno),
                f"`{name}:{lineno}` is past the end of a {len(lines)}-line file",
            )
            sentence = DOC_FLAT.split(f"`{name}:{lineno}`", 1)[1]
            called = re.match(r" calls `([\w.]+)\(", sentence)
            if called:
                self.assertIn(called.group(1), lines[int(lineno) - 1])


class TestPosture(unittest.TestCase):
    REPLACEMENTS = {
        "models.py": "models",
        "fields.py": "fields",
        "api.py": "api",
        "http.py": "http",
        "sql_db.py": "db",
        "service/server.py": None,
    }

    def test_named_monoliths_are_no_longer_monoliths(self) -> None:
        for name, package in self.REPLACEMENTS.items():
            with self.subTest(monolith=name):
                path = ROOT / "odoo" / name
                if package is None:
                    self.assertTrue(path.is_file(), f"odoo/{name} is gone entirely")
                    lines = len(path.read_text(encoding="utf-8").splitlines())
                    self.assertLess(
                        lines, 400, f"odoo/{name} is {lines} lines — not a facade"
                    )
                    continue
                self.assertFalse(
                    path.exists(), f"odoo/{name} is back as a single module"
                )
                self.assertTrue(
                    (ROOT / "odoo" / package / "__init__.py").is_file(),
                    f"odoo/{name} was split into odoo/{package}/, which is not "
                    f"a package",
                )

    def test_sql_db_is_gone(self) -> None:
        self.assertFalse((ROOT / "odoo" / "sql_db.py").exists())
        self.assertTrue((ROOT / "odoo" / "db" / "__init__.py").is_file())


class TestPatchModuleConvention(unittest.TestCase):
    PKG = ROOT / "odoo" / "_monkeypatches"

    def test_every_registered_patch_exposes_the_hook(self) -> None:
        missing = [
            path.name
            for path in sorted(self.PKG.glob("*.py"))
            if not path.name.startswith("_")
            and "def patch_module(" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [])

    def test_the_underscore_exemption_is_real_and_stated(self) -> None:
        init = (self.PKG / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('if submodule.name.startswith("_"):', init)
        exempt = [
            path.name
            for path in sorted(self.PKG.glob("_*.py"))
            if path.name != "__init__.py"
            and "def patch_module(" not in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(exempt, "no underscore helper left; simplify the page")
        self.assertIn("non-underscore submodule exposes `patch_module()`", DOC_FLAT)


class TestContractNamesResolveEverywhere(unittest.TestCase):
    def test_every_kebab_case_citation_is_a_real_contract(self) -> None:
        known = {c.name for c in layer_check.CONTRACTS} | {
            c.name for c in js_layer_check.CONTRACTS
        }
        cited = set(re.findall(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+){2,})`", DOC))
        self.assertTrue(cited, "the page cites no contract; the pattern has rotted")
        self.assertEqual(
            cited - known,
            set(),
            f"backticked kebab-case names that are not contracts: "
            f"{sorted(cited - known)}",
        )
