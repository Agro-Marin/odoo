from __future__ import annotations

import ast
import collections
import json
import re
import unittest

import _doc_measures
import doc_restated_counts

from ._shared import (
    DOC,
    DOC_FLAT,
    NUMBER_WORD_BY_VALUE,
    ROOT,
    _ordinal_word,
)

_ADDON_ROOTS = (ROOT / "addons", ROOT / "odoo" / "addons")


def _depends(module: str) -> list[str]:
    for root in _ADDON_ROOTS:
        manifest = root / module / "__manifest__.py"
        if manifest.exists():
            return list(
                ast.literal_eval(manifest.read_text(encoding="utf-8")).get(
                    "depends", []
                )
            )
    return []


def _closure(module: str) -> set[str]:
    seen: set[str] = set()
    pending = list(_depends(module))
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(_depends(name))
    return seen


class TestGateInventoryIsWiredShut(unittest.TestCase):
    WORKFLOW = ROOT / ".github" / "workflows" / "architecture.yml"

    @classmethod
    def setUpClass(cls) -> None:
        cls.yaml = cls.WORKFLOW.read_text(encoding="utf-8")

    def _table_gates(self) -> list[str]:
        section = DOC.split("## Quality gates beyond the boundaries", 1)[1]
        return re.findall(r"^\| `([\w.]+\.py)` \|", section, re.MULTILINE)

    def _workflow_gates(self) -> list[str]:
        return _doc_measures.workflow_gates()

    def test_table_matches_the_workflow(self) -> None:
        self.assertEqual(set(self._table_gates()), set(self._workflow_gates()))

    def test_the_reproduce_loop_is_exactly_the_contract_gates(self) -> None:

        ratchets = set(
            re.findall(r"python tooling/architecture/([\w.]+\.py) --count", self.yaml)
        )
        contract = {
            gate.removesuffix(".py") for gate in set(self._workflow_gates()) - ratchets
        }
        loop = re.search(r"for gate in (.*?); do", DOC, re.DOTALL)
        self.assertIsNotNone(loop, "the reproduce loop is no longer on the page")
        listed = set(loop.group(1).replace("\\", "").split())
        self.assertEqual(
            listed,
            contract,
            "the reproduce loop and the workflow's contract gates disagree — "
            f"missing from the loop: {sorted(contract - listed)}; "
            f"in the loop but not a contract gate: {sorted(listed - contract)}",
        )

        ratchet_block = DOC.split("while read -r gate floor; do", 1)[1].split(
            "EOF\n```", 1
        )[0]
        piped = set(re.findall(r"^(\w+)\s+\w+$", ratchet_block, re.MULTILINE))
        self.assertEqual(piped, {r.removesuffix(".py") for r in ratchets})

    def test_the_recipe_reproduces_every_scoped_step(self) -> None:
        rows = _doc_measures.scoped_reproduce_rows()
        self.assertTrue(rows, "the workflow scopes nothing; the parser has rotted")
        block = DOC.split("while IFS='|' read -r gate floor; do", 1)
        self.assertEqual(len(block), 2, "the scoped block is no longer on the page")
        listed = {
            line.strip()
            for line in block[1].split("<<'EOF'", 1)[1].split("EOF", 1)[0].splitlines()
            if line.strip()
        }
        expected = {f"{gate}|{ratchet}" for gate, ratchet in rows}
        self.assertEqual(
            listed,
            expected,
            "the scoped block and the workflow disagree — "
            f"missing from the page: {sorted(expected - listed)}; "
            f"on the page and not in CI: {sorted(listed - expected)}",
        )

    def test_the_page_says_how_many_steps_the_default_loops_cover(self) -> None:
        gates, steps = len(self._workflow_gates()), len(_doc_measures.workflow_steps())
        scoped = len(_doc_measures.scoped_reproduce_rows())
        self.assertEqual(
            gates + scoped,
            steps,
            "a step neither runs a gate at its default scope nor names one",
        )
        self.assertIn(f"at its default scope: {gates} of the", DOC_FLAT)
        self.assertIn(f"workflow's {steps} steps", DOC_FLAT)
        self.assertIn(f"these are the other {scoped}.", DOC_FLAT)

    def test_stated_count_matches_both(self) -> None:
        words = NUMBER_WORD_BY_VALUE
        count = len(self._workflow_gates())
        self.assertIn(
            f"runs **{words[count]}** blocking checkers", DOC_FLAT, f"{count} gates run"
        )

    def _gates_without_a_check_flag(self) -> list[str]:

        out = []
        for gate in self._workflow_gates():
            source = ROOT / "tooling" / "architecture" / gate
            self.assertTrue(
                source.is_file(),
                f"architecture.yml runs {gate} as a blocking step and no such "
                f"file exists — the boundary job cannot pass",
            )
            tree = ast.parse(source.read_text(encoding="utf-8"))
            declared = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_argument"
                and any(
                    isinstance(a, ast.Constant) and a.value == "--check" for a in n.args
                )
                for n in ast.walk(tree)
            )
            if not declared:
                out.append(gate)
        return out

    def test_the_cli_split_adds_up_to_the_total(self) -> None:

        words = NUMBER_WORD_BY_VALUE
        total = len(self._workflow_gates())
        ratchets = set(
            re.findall(r"python tooling/architecture/([\w.]+\.py) --count", self.yaml)
        )
        contract = total - len(ratchets)
        self.assertEqual(
            contract + len(ratchets), total, "the two groups must partition the gates"
        )
        self.assertIn(
            f"**{words[contract].capitalize()} are contract gates.**", DOC_FLAT
        )
        self.assertIn(
            f"**{words[len(ratchets)].capitalize()} are count ratchets.**", DOC_FLAT
        )
        self.assertIn(
            f"a loop that assumes they do fails on "
            f"{words[len(self._gates_without_a_check_flag())]} of them",
            DOC_FLAT,
        )
        self.assertIn(
            f"{words[contract].capitalize()} plus {words[len(ratchets)]} is "
            f"{words[total]}",
            DOC_FLAT,
        )

    def test_the_gates_named_as_check_less_are_exactly_those(self) -> None:
        named = set(self._gates_without_a_check_flag())
        for gate in named:
            self.assertIn(
                f"`{gate.removesuffix('.py')}`",
                DOC,
                f"{gate} implements no --check and the page does not say so",
            )
        sentence = DOC_FLAT.split("are count ratchets", 1)[1].split(
            "implement no `--check` at all", 1
        )[0]
        claimed = {f"{m}.py" for m in re.findall(r"`(\w+)`", sentence)}
        self.assertEqual(claimed, named)

    def test_every_gate_step_is_blocking(self) -> None:
        reraised = self.yaml.count('exit "${GATE_EXIT}"') + self.yaml.count("exit $rc")
        steps = len(re.findall(r"^\s+id: \w+$", self.yaml, re.MULTILINE))
        self.assertEqual(reraised, steps)

    def test_the_step_count_tracks_the_workflow(self) -> None:
        words = NUMBER_WORD_BY_VALUE
        per_step = [
            set(re.findall(r"tooling/architecture/([\w.]+)\.py", body))
            for body in re.split(r"^\s+id: \w+$", self.yaml, flags=re.MULTILINE)[1:]
        ]
        self.assertTrue(per_step, "the workflow declares no gate step")
        self.assertEqual(
            [len(checkers) for checkers in per_step],
            [1] * len(per_step),
            "a step no longer invokes exactly one checker, which is the whole "
            "claim the step count rests on",
        )
        self.assertIn(
            f"**{words[len(per_step)].capitalize()}** is how many steps CI runs "
            f"the {words[len(self._workflow_gates())]} in",
            DOC_FLAT,
        )
        widest = collections.Counter(
            checker for (checker,) in map(tuple, per_step)
        ).most_common(1)[0]
        self.assertIn(
            f"`{widest[0]}` alone accounts for {words[widest[1]]}",
            DOC_FLAT,
            f"the example of a multi-scope gate is stale; widest is {widest}",
        )

    def test_the_tokenizer_consumer_count_is_derived(self) -> None:
        words = NUMBER_WORD_BY_VALUE
        tooling = ROOT / "tooling" / "architecture"
        consumers = {
            source.stem
            for source in tooling.glob("*.py")
            if not source.name.startswith("test_")
            and source.name != "js_imports.py"
            and re.search(
                r"^(?:import js_imports|from js_imports)",
                source.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        }
        self.assertTrue(consumers, "nothing imports js_imports; the regex rotted")
        stepped = consumers & {g.removesuffix(".py") for g in self._workflow_gates()}
        self.assertIn(
            f"the JS tokenizer **{words[len(consumers)]}** of the checkers parse with",
            DOC_FLAT,
        )
        self.assertIn(
            f"{words[len(consumers)].capitalize()} and not {words[len(stepped)]}, "
            f"which is what counting only the table above would give",
            DOC_FLAT,
        )

    def test_the_annotation_does_not_enumerate_the_steps(self) -> None:
        condition = self.yaml.split("Annotate PR on failure", 1)[1].split("uses:", 1)[0]
        self.assertIn("failure()", condition)
        self.assertNotIn(
            "steps.",
            condition,
            "the annotation is naming individual steps again; `failure()` is "
            "true exactly when any step in this job has failed, so the list is "
            "a hand-maintained copy that can only ever fall behind",
        )

    def test_the_premises_that_make_failure_equivalent_still_hold(self) -> None:
        jobs = re.findall(r"^  ([a-z_]+):$", self.yaml, re.MULTILINE)
        self.assertEqual(
            [j for j in jobs if j not in ("push", "pull_request")],
            ["layers"],
            "`failure()` is job-scoped; with a second job the annotation would "
            "fire for a failure in a job it does not describe",
        )
        for line in self.yaml.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotIn(
                "continue-on-error",
                stripped,
                "a step that swallows its failure keeps the job green, and "
                "`failure()` would not fire for it",
            )

    def test_no_step_writes_an_output_nothing_reads(self) -> None:
        written = set(re.findall(r'echo "(\w+)=', self.yaml))
        for name in written:
            self.assertIn(
                f"outputs.{name}",
                self.yaml,
                f"every gate step writes `{name}` to $GITHUB_OUTPUT and nothing "
                f"reads it. 69 steps wrote `exit_code` for one condition that no "
                f"longer enumerates them.",
            )

    def test_no_gate_is_described_as_unwired(self) -> None:
        self.assertNotIn("Not yet wired", DOC)

    def test_the_outside_checker_is_counted_from_the_inside_ones(self) -> None:
        expected = _ordinal_word(
            len(self._workflow_gates()) + len(_doc_measures.self_test_only_gates()) + 1
        )
        self.assertIn(f"is a {expected} checker and the only one outside CI", DOC_FLAT)


class TestAddonSuiteFigures(unittest.TestCase):
    @staticmethod
    def _suite(module: str) -> tuple[int, int]:
        for tree in ("addons", "odoo/addons"):
            base = ROOT / tree / module / "tests"
            if base.is_dir():
                break
        else:
            raise AssertionError(f"{module}/tests not found in either addon tree")
        lines = sum(
            len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
            for path in sorted(base.rglob("*.py"))
        )
        return _doc_measures.suite_methods(module), lines

    def test_no_page_states_a_suite_size_the_tree_does_not_hold(self) -> None:
        wrong = []
        for module, phrasings in {
            "test_orm": (
                rf"`test_orm`[^.]*?\*\*({_doc_measures.ANY_NUMBER}) test methods\*\*",
                rf"`test_orm`[^.]*?its ({_doc_measures.ANY_NUMBER}) methods",
            ),
            "stock": (rf"stock's own ({_doc_measures.ANY_NUMBER}) tests",),
            "mail": (rf"its own \*\*({_doc_measures.ANY_NUMBER})\*\*-test suite",),
        }.items():
            measured = _doc_measures.suite_methods(module)
            for phrasing in phrasings:
                for page, match in _doc_measures.stated(phrasing):
                    if _doc_measures.number_value(match.group(1)) != measured:
                        wrong.append(
                            f"{page}: {module} stated as {match.group(1)}, "
                            f"tree holds {measured}"
                        )
        self.assertEqual([], wrong, "\n  " + "\n  ".join(wrong))

    def test_the_test_orm_figure_is_measured(self) -> None:
        methods, _lines = self._suite("test_orm")
        self.assertIn(f"**{methods:,} test methods**", DOC_FLAT)

    def test_the_two_suites_this_page_named_as_next_are_in_the_lane(self) -> None:
        read_group, _ = self._suite("test_read_group")
        access_rights, _ = self._suite("test_access_rights")
        self.assertIn(f"`test_read_group` ({read_group} test", DOC_FLAT)
        self.assertIn(f"`test_access_rights` ({access_rights},", DOC_FLAT)
        workflow = (ROOT / ".github" / "workflows" / "integration_tests.yml").read_text(
            encoding="utf-8"
        )
        for suite in ("test_read_group", "test_access_rights"):
            self.assertIn(
                f"-d ci_{suite.removeprefix('test_')}",
                workflow,
                f"the page says {suite} was added to the lane and it is not there",
            )
        self.assertNotIn("Still outside the lane", DOC)

    def test_line_counts_are_not_quoted_for_these_suites(self) -> None:

        self.assertIn("Method counts, not line counts.", DOC_FLAT)
        for module in ("test_orm", "test_read_group"):
            _methods, lines = self._suite(module)
            self.assertNotIn(f"{lines:,} lines", DOC_FLAT)

    def test_every_prose_figure_is_fresh(self) -> None:
        figures = doc_restated_counts.figures_for(ROOT / "doc" / "architecture")
        self.assertTrue(figures, "no figure measures doc/architecture any more")
        problems = doc_restated_counts.check(figures)
        self.assertFalse(
            problems,
            "prose figures have drifted from what the tree measures; run "
            "`python tooling/architecture/doc_restated_counts.py --update`:\n  "
            + "\n  ".join(problems),
        )


class TestTheEnforcedClaimIsBounded(unittest.TestCase):
    BOUNDARY = ROOT / ".github" / "workflows" / "architecture.yml"
    INTEGRATION = ROOT / ".github" / "workflows" / "integration_tests.yml"

    def test_the_boundary_job_really_has_no_database(self) -> None:
        yaml = self.BOUNDARY.read_text(encoding="utf-8")
        for marker in ("services:", "postgres", "POSTGRES_"):
            self.assertNotIn(
                marker,
                yaml,
                f"architecture.yml now provisions a database ({marker!r}); the "
                f"page's DB-free claim about the boundary gates is stale",
            )

    def test_the_integration_lane_is_the_one_with_a_database(self) -> None:
        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        self.assertIn("postgres:18", yaml)
        self.assertIn("only lane that runs addon tests", DOC_FLAT)

    JS = ROOT / ".github" / "workflows" / "js_tests.yml"

    def test_the_js_lane_exists_and_runs_both_presets(self) -> None:
        # The page said "No lane runs the JS suites" for as long as it was
        # true. Now that one does, pin what the page claims about it: the
        # runner, both presets, and a count gate per pass -- each of which
        # is a thing the page says this lane does, and each of which a
        # later edit could drop while the page kept saying so.
        yaml = self.JS.read_text(encoding="utf-8")
        self.assertIn("hoot-shard", yaml)
        for preset in ("desktop", "mobile"):
            self.assertIn(f"--preset {preset}", yaml, f"the {preset} pass is gone")
            self.assertRegex(
                yaml,
                rf"{preset.upper()}_COUNT_FLOOR",
                f"the {preset} pass no longer gates on its count",
            )
        self.assertIn("js_tests.yml", DOC)
        self.assertIn("under both presets", DOC_FLAT)

    def test_every_installed_module_is_named_by_the_page(self) -> None:
        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        installs = re.findall(r"^  (?:\w+_)?INSTALL: (.+)$", yaml, re.MULTILINE)
        self.assertTrue(installs, "the integration lane installs nothing")
        for spec in installs:
            for module in spec.split(","):
                self.assertIn(
                    f"`{module.strip()}`",
                    DOC,
                    f"the integration lane installs {module.strip()}, unmentioned",
                )

    def test_each_suite_gets_its_own_database(self) -> None:

        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        databases = re.findall(r"^\s+-d (\w+) \\$", yaml, re.MULTILINE)
        self.assertGreater(len(databases), 1, "only one suite runs")
        self.assertEqual(
            len(databases),
            len(set(databases)),
            f"two suites share a database, so they can interfere: {databases}",
        )
        installs = re.findall(r"^  (?:\w+_)?INSTALL: (.+)$", yaml, re.MULTILINE)
        self.assertEqual(
            len(databases),
            len(installs),
            "every suite must declare its own module set",
        )
        for spec in installs:
            modules = [m.strip() for m in spec.split(",")]
            if len(modules) == 1:
                continue
            # A module cannot be installed without its dependencies, so a spec
            # naming one module's own closure is one suite, not several sharing
            # a database.  Independent suites are what interfere -- the
            # base/test_http view-inheritance clash -- and only they are banned.
            self.assertTrue(
                [m for m in modules if set(modules) - {m} <= _closure(m)],
                f"independent suites are combined into one database ({spec!r}); "
                f"no listed module's dependencies cover the rest, so the "
                f"base/test_http view-inheritance clash comes back",
            )

    def test_the_stated_suite_count_matches_the_lane(self) -> None:

        yaml = self.INTEGRATION.read_text(encoding="utf-8")
        words = NUMBER_WORD_BY_VALUE
        n = len(re.findall(r"^  (?:\w+_)?INSTALL: (.+)$", yaml, re.MULTILINE))
        self.assertIn(
            f"runs {words[n]} suites, **each against its own database**",
            DOC_FLAT,
            f"the lane runs {n} suites",
        )
        self.assertIn(f"it runs {words[n]} suites", DOC_FLAT, "risks.md R4 count")

    def test_the_ormcache_style_gap_is_named(self) -> None:
        self.assertIn("OrmCore", DOC)
        self.assertIn('never as "the framework works"', DOC_FLAT)
        core = (ROOT / "odoo" / "orm" / "components" / "core.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(core, r"_cache\b")
        self.assertRegex(core, r"_engine\b")


class TestFloorMethodologyExample(unittest.TestCase):
    def test_the_example_does_not_claim_to_be_the_current_floor(self) -> None:

        floor = json.loads(
            (ROOT / "tooling" / "ratchet" / "baselines" / "pyfunclen.json").read_text(
                encoding="utf-8"
            )
        )["count"]
        self.assertIn("`pyfunclen` that day", DOC, "the example lost its dating")
        self.assertIn(
            "this table is an illustration of the method and is not maintained",
            DOC_FLAT,
        )
        self.assertNotIn(
            "= the committed floor",
            DOC,
            "the worked example claims equality with the committed floor again; "
            f"it is {floor} today and the claim will rot the next time a "
            f"function is shortened",
        )

    def test_the_quoted_budget_is_the_gates_own(self) -> None:
        src = (ROOT / "tooling" / "architecture" / "py_function_length.py").read_text(
            encoding="utf-8"
        )
        match = re.search(r"^MAX_LINES = (\d+)$", src, re.MULTILINE)
        self.assertIsNotNone(match, "py_function_length.MAX_LINES is gone")
        self.assertIn(f"*excess lines* over {match.group(1)}", DOC_FLAT)
