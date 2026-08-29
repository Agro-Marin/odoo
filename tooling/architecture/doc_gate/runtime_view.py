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


class TestRuntimeFloors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        src = (ROOT / "odoo" / "release.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls.consts: dict[str, object] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                with __import__("contextlib").suppress(ValueError):
                    cls.consts[node.target.id] = ast.literal_eval(node.value)

    def test_python_floor(self) -> None:

        self.assertEqual(self.consts["MIN_PY_VERSION"], self.consts["MAX_PY_VERSION"])
        self.assertIn("`MIN_PY_VERSION`", DOC)
        init = (ROOT / "odoo" / "init.py").read_text(encoding="utf-8")
        self.assertIn("if sys.version_info[:2] < MIN_PY_VERSION:", init)

    def test_postgres_floor(self) -> None:
        self.assertIsInstance(self.consts["MIN_PG_VERSION"], int)
        self.assertIn("`MIN_PG_VERSION`", DOC)
        self.assertIn("`PoolError`", DOC)
        pool = (ROOT / "odoo" / "db" / "pool.py").read_text(encoding="utf-8")
        self.assertIn("from odoo.release import MIN_PG_VERSION", pool)
        self.assertIn("raise PoolError(", pool.split("sv < MIN_PG_VERSION")[1])


class TestHttpLifecycle(unittest.TestCase):
    def test_retrying_lives_in_service_transaction(self) -> None:
        self.assertIn("`retrying()` lives in `odoo/service/transaction.py`", DOC_FLAT)
        self.assertNotIn("Model.retrying", DOC)
        src = (ROOT / "odoo" / "service" / "transaction.py").read_text(encoding="utf-8")
        self.assertRegex(
            src,
            re.compile(r"^def retrying\b", re.MULTILINE),
            msg="retrying() moved again",
        )

    def test_named_hooks_exist_on_ir_http(self) -> None:
        src = (ROOT / "odoo" / "addons" / "base" / "models" / "ir_http.py").read_text(
            encoding="utf-8"
        )
        for hook in ("_match", "_authenticate", "_pre_dispatch", "_post_dispatch"):
            self.assertIn(f"ir.http.{hook}", DOC, f"{hook} dropped from the sketch")
            self.assertRegex(
                src,
                re.compile(rf"^    def {hook}\b", re.MULTILINE),
                f"ir.http.{hook} no longer exists",
            )

    def test_dispatcher_subclasses(self) -> None:
        src = (ROOT / "odoo" / "http" / "dispatcher.py").read_text(encoding="utf-8")
        named = re.search(r"three subclasses \(`(\w+)`, `(\w+)`,\s*\n?`(\w+)`\)", DOC)
        self.assertIsNotNone(named, "the Dispatcher subclass list is no longer stated")
        on_disk = set(re.findall(r"^class (\w+)\(Dispatcher\):", src, re.MULTILINE))
        self.assertEqual(set(named.groups()), on_disk)

    def test_serve_entry_points_exist(self) -> None:
        src = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        for fn in ("_serve_static", "_serve_nodb", "_serve_db"):
            self.assertIn(fn, DOC)
            self.assertRegex(src, re.compile(rf"^    def {fn}\b", re.MULTILINE))

    def test_commit_is_inside_retrying(self) -> None:

        self.assertIn("is the last thing `retrying()` does", DOC_FLAT)
        transaction = (ROOT / "odoo" / "service" / "transaction.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("env.cr.commit()", transaction)
        serve = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "cr.commit()",
            serve,
            "_serve_db commits now; the lifecycle note says retrying() does",
        )

    def test_session_is_saved_in_post_dispatch(self) -> None:
        self.assertIn("`Request._save_session()`", DOC_FLAT)
        dispatcher = (ROOT / "odoo" / "http" / "dispatcher.py").read_text(
            encoding="utf-8"
        )
        body = dispatcher.split("def post_dispatch", 1)[1].split("\n    def ", 1)[0]
        self.assertIn(
            "_save_session()",
            body,
            "the session is no longer saved from Dispatcher.post_dispatch",
        )

    def test_ro_rw_promotion_is_real(self) -> None:
        self.assertIn("the handler runs a second time", DOC_FLAT)
        src = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        self.assertIn("psycopg.errors.ReadOnlySqlTransaction", src)

    BEHAVIOURAL_COVER = {
        "addons/test_http/tests/test_lifecycle_order.py": (
            "test_session_is_saved_before_the_commit",
            "test_commit_is_the_last_thing_on_the_serving_thread",
            "test_promotion_reruns_the_handler_and_still_saves_before_committing",
        ),
        "addons/test_http/tests/test_models.py": (
            "test_promotion_replay_does_not_inherit_the_aborted_env",
        ),
    }

    def test_ordering_claims_have_a_runtime_test(self) -> None:
        for rel, names in self.BEHAVIOURAL_COVER.items():
            path = ROOT / "odoo" / rel
            self.assertTrue(
                path.is_file(),
                f"{rel} is gone; the ordering claims are back to being grep-only",
            )
            src = path.read_text(encoding="utf-8")
            for name in names:
                self.assertRegex(
                    src,
                    rf"\n    def {name}\(",
                    f"{rel} no longer defines {name}",
                )

    def test_the_runtime_test_is_registered(self) -> None:
        init = ROOT / "odoo" / "addons" / "test_http" / "tests" / "__init__.py"
        self.assertIn("from . import test_lifecycle_order", init.read_text())

    def test_the_page_names_where_the_proof_is(self) -> None:
        self.assertIn("test_lifecycle_order.py", DOC_FLAT)


class TestCronExceptionRationale(unittest.TestCase):
    JOB_ENTRY_POINTS = (
        ("ir_cron.py", "IrCron"),
        ("ir_job.py", "IrJob"),
    )

    def test_entry_points_are_staticmethods(self) -> None:
        self.assertIn("`@staticmethod` entry points", DOC_FLAT)
        for filename, _cls in self.JOB_ENTRY_POINTS:
            src = (ROOT / "odoo" / "addons" / "base" / "models" / filename).read_text(
                encoding="utf-8"
            )
            self.assertRegex(
                src,
                r"@staticmethod\n    def _process_jobs\(",
                f"{filename}: _process_jobs is no longer a @staticmethod",
            )

    def test_imports_are_deferred_to_call_time(self) -> None:
        self.assertIn("Both imports are deferred to call time", DOC_FLAT)
        for filename in ("_threaded.py", "_worker.py"):
            src = (ROOT / "odoo" / "service" / filename).read_text(encoding="utf-8")
            for line in src.splitlines():
                if "from odoo.addons.base.models.ir_" in line:
                    self.assertTrue(
                        line.startswith("        "),
                        f"{filename}: the cron import is no longer function-local, "
                        "which breaks the documented rationale for pinning it",
                    )

    def test_no_override_exists_in_this_repo(self) -> None:
        self.assertIn("no override of either exists anywhere", DOC_FLAT)
        definitions = [
            p.relative_to(ROOT)
            for p in (ROOT / "odoo" / "addons").rglob("*.py")
            if re.search(
                r"^    def _process_jobs\(", p.read_text(encoding="utf-8"), re.MULTILINE
            )
        ]
        self.assertEqual(
            sorted(str(p) for p in definitions),
            [
                "odoo/addons/base/models/ir_cron.py",
                "odoo/addons/base/models/ir_job.py",
            ],
        )


class TestHttpCallGraphIsRecoverable(unittest.TestCase):
    README = ROOT / "odoo" / "http" / "README.md"

    def test_the_pointer_resolves(self) -> None:
        self.assertIn("`odoo/http/README.md`", DOC)
        self.assertTrue(self.README.is_file())
        self.assertNotIn("call graph is the module docstring", DOC_FLAT)

    def test_the_graph_is_actually_in_it(self) -> None:
        text = self.README.read_text(encoding="utf-8")
        for stage in (
            "Application.__call__",
            "Request._serve_static",
            "Request._serve_nodb",
            "Request._serve_db",
            "transaction.retrying(Request._serve_ir_http)",
            "transaction.retrying(Request._serve_ir_http_fallback)",
            "env['ir.http']._authenticate",
            "env['ir.http']._post_dispatch",
        ):
            self.assertIn(stage, text, f"the recovered call graph lost {stage}")

    def test_every_named_ir_http_hook_exists(self) -> None:
        ir_http = (
            ROOT / "odoo" / "addons" / "base" / "models" / "ir_http.py"
        ).read_text(encoding="utf-8")
        hooks = set(re.findall(r"env\['ir\.http'\]\.(\w+)", self.README.read_text()))
        self.assertTrue(hooks)
        for hook in hooks:
            self.assertRegex(ir_http, rf"\n    def {hook}\(")

    def test_every_named_request_method_exists(self) -> None:
        serve = (ROOT / "odoo" / "http" / "_serve.py").read_text(encoding="utf-8")
        methods = set(re.findall(r"Request\.(_serve_\w+)", self.README.read_text()))
        self.assertTrue(methods)
        for method in methods:
            self.assertRegex(serve, rf"\n    def {method}\(")


class TestLifecycleSketches(unittest.TestCase):
    @staticmethod
    def _block(heading: str) -> str:
        return DOC.split(heading, 1)[1].split("```", 2)[1]

    BOOT_CHAIN = (
        ("odoo.cli.main()", "cli/command.py", r"^def main\("),
        (
            "load_server_wide_modules()",
            "service/lifecycle.py",
            r"^def load_server_wide_modules\(",
        ),
        ("service.lifecycle.start()", "service/lifecycle.py", r"^def start\("),
        (
            "preload_registries(dbnames)",
            "service/lifecycle.py",
            r"^def preload_registries\(",
        ),
        ("Registry.new(", "orm/runtime/registry.py", r"^    def new\("),
    )

    def test_boot_chain_resolves(self) -> None:
        block = self._block("### Process boot")
        for written, rel, pattern in self.BOOT_CHAIN:
            self.assertIn(written, block, f"the boot sketch no longer names {written}")
            src = (ROOT / "odoo" / rel).read_text(encoding="utf-8")
            self.assertRegex(
                src, re.compile(pattern, re.MULTILINE), f"{rel}: {pattern}"
            )

    def test_the_three_server_classes_are_the_ones_start_chooses(self) -> None:
        src = (ROOT / "odoo" / "service" / "lifecycle.py").read_text(encoding="utf-8")
        body = src.split("\ndef start(", 1)[1]
        chosen = {
            name
            for name in ("EventServer", "PreforkServer", "ThreadedServer")
            if f"{name}(" in body
        }
        self.assertEqual(
            chosen,
            {"EventServer", "PreforkServer", "ThreadedServer"},
            "service.lifecycle.start() no longer constructs all three servers",
        )
        block = self._block("### Process boot")
        for name in chosen:
            self.assertIn(name, block, f"the boot sketch dropped {name}")

    def test_bootstrap_order_matches_odoo_init(self) -> None:
        src = (ROOT / "odoo" / "init.py").read_text(encoding="utf-8")
        marks = [
            "MIN_PY_VERSION",
            "import odoo_rust",
            "assert_fresh(odoo_rust",
            "gc.set_threshold",
            "patch_init",
        ]
        positions = []
        for mark in marks:
            index = src.find(mark)
            self.assertNotEqual(-1, index, f"odoo/init.py no longer does {mark}")
            positions.append(index)
        self.assertEqual(
            positions, sorted(positions), f"odoo/init.py reordered: {marks}"
        )

        section = DOC.split("### Process boot", 1)[1].split("\n### ", 1)[0]
        shown = [
            token
            for token in (
                "MIN_PY_VERSION",
                "odoo_rust",
                "__source_crc__",
                "GC threshold",
                "patch_init",
            )
            if token in section
        ]
        block = section
        self.assertEqual(
            shown,
            [
                "MIN_PY_VERSION",
                "odoo_rust",
                "__source_crc__",
                "GC threshold",
                "patch_init",
            ],
            "the boot sketch dropped a step or lists them out of order",
        )
        at = [block.index(token) for token in shown]
        self.assertEqual(at, sorted(at), "the boot sketch is out of init.py's order")

    @staticmethod
    def _loader_call_order() -> list[str]:
        src = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        body = src.split("\ndef load_modules(", 1)[1]
        return re.findall(r"loader\.(\w+)\(", body)

    def test_registry_build_phases_are_real_and_ordered(self) -> None:
        loading = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        methods = set(
            re.findall(
                r"^    def (\w+)\(",
                loading.split("\nclass _ModuleLoader", 1)[1],
                re.MULTILINE,
            )
        )
        self.assertTrue(methods, "_ModuleLoader has no methods; the split changed")

        block = self._block("### Registry build")
        named = [n for n in re.findall(r"\b(\w+)\(\)", block) if n in methods]
        self.assertTrue(
            named, "the registry-build sketch names no _ModuleLoader phase at all"
        )
        unknown = [
            n
            for n in re.findall(r"^\s*[├└]─ (\w+)\(", block, re.MULTILINE)
            if n not in methods and n not in {"setup_signaling", "load_modules"}
        ]
        self.assertEqual(unknown, [], f"phases that are not loader methods: {unknown}")

        order = self._loader_call_order()
        positions = [order.index(n) for n in named if n in order]
        self.assertEqual(len(positions), len(named), "a named phase is never called")
        self.assertEqual(
            positions,
            sorted(positions),
            "the registry-build sketch lists phases in an order load_modules "
            f"does not run them in: {named}",
        )

    def test_scenario_a_phase_table_is_ordered_and_says_it_is_partial(self) -> None:

        order = self._loader_call_order()
        self.assertGreater(len(order), 15, "load_modules no longer calls phases")

        table = DOC.split("## Scenario A — installing a module", 1)[1].split(
            "\n\n##", 1
        )[0]
        named = re.findall(r"\| `(\w+)\(\)`", table)
        self.assertGreater(len(named), 5, "the scenario table names no phases")
        unknown = sorted(set(named) - set(order))
        self.assertEqual(
            [],
            unknown,
            f"the Scenario A table names phase(s) load_modules does not call: "
            f"{unknown}",
        )
        positions = [order.index(n) for n in named]
        self.assertEqual(
            positions,
            sorted(positions),
            f"the Scenario A table is out of call order: {named}",
        )
        self.assertIn(f"{len(order)} calls", DOC_FLAT, "the full phase count is stated")

    def test_the_scenario_a_selection_and_its_leftovers_are_the_whole_loader(
        self,
    ) -> None:
        order = self._loader_call_order()
        page = DOC.split("## Scenario A — installing a module", 1)[1].split("\n## ", 1)[
            0
        ]
        selected = re.findall(r"\| `(\w+)\(\)`", page)
        left_out = [
            name
            for name in re.findall(r"`(\w+)`", page.split("| Left out | Why |", 1)[1])
            if name in order
        ]
        self.assertEqual(
            sorted(set(order)),
            sorted(set(selected) | set(left_out)),
            f"a load_modules call is in neither of Scenario A's tables — "
            f"selected {len(set(selected))}, left out {len(set(left_out))}, "
            f"loader calls {len(set(order))}",
        )
        self.assertEqual(
            [],
            sorted(set(selected) & set(left_out)),
            "a phase is both selected and listed as left out",
        )
        self.assertIn(
            f"{_doc_measures.number_word(len(set(selected))).capitalize()} of "
            f"`load_modules`' {len(set(order))} calls",
            DOC_FLAT,
            f"the page states a selection size other than {len(set(selected))}",
        )
        self.assertIn(
            f"The {_doc_measures.number_word(len(set(left_out)))} left out",
            DOC_FLAT,
            f"the page states a leftover count other than {len(set(left_out))}",
        )

    def test_scenario_b_stages_and_markers_are_the_loaders(self) -> None:
        source = (ROOT / "odoo" / "modules" / "migration.py").read_text(
            encoding="utf-8"
        )
        stages = re.search(
            r"MIGRATION_STAGES: tuple\[str, \.\.\.\] = \(([^)]*)\)", source
        )
        self.assertIsNotNone(stages, "MIGRATION_STAGES is gone from migration.py")
        names = re.findall(r'"(\w+)"', stages.group(1))
        self.assertEqual(["pre", "post", "end"], names, "the stage set changed")

        table = DOC.split("## Scenario B", 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"^\| `(\w+)` \| `([^`]+)` \|", table, re.MULTILINE)
        self.assertEqual(
            names,
            [stage for stage, _marker in rows],
            "Scenario B's stage table and MIGRATION_STAGES disagree",
        )
        markers = dict(re.findall(r'"(pre|post|end)": "(\[[^"]+\])"', source))
        self.assertEqual(
            {
                stage: marker.replace("%s", "version")
                for stage, marker in markers.items()
            },
            dict(rows),
            "the version markers the table quotes are not the ones the loader writes",
        )
        self.assertIn('startswith(f"{stage}-")', source)
        for stage in names:
            self.assertIn(
                f"`{stage}-`",
                DOC,
                f"the page names no `{stage}-` filename prefix, which is what "
                f"selects a script",
            )

    def test_the_reload_reentry_is_real(self) -> None:
        self.assertIn("may force one full reload", DOC)
        src = (ROOT / "odoo" / "modules" / "loading.py").read_text(encoding="utf-8")
        handler = src.split("except _UninstallRequiresReload:", 1)
        self.assertEqual(
            len(handler), 2, "_UninstallRequiresReload is no longer caught"
        )
        self.assertIn("Registry.new(", handler[1].split("\n\n", 1)[0])

    def test_transaction_owns_what_the_sketch_draws(self) -> None:
        block = self._block("### Transaction, cache and flush")
        drawn = re.findall(r"^\s*[├└]─ (\w+)\s", block, re.MULTILINE)
        self.assertTrue(drawn, "the transaction sketch draws no members")
        src = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        slots = set(re.findall(r'"(\w+)"', src.split("__slots__ = (", 1)[1]))
        missing = [name for name in drawn if name not in slots]
        self.assertEqual(missing, [], f"not Transaction slots: {missing}")

    def test_environment_interning_claim(self) -> None:
        self.assertIn("is **interned** per `(cr, uid, su, context)`", DOC_FLAT)
        src = (ROOT / "odoo" / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("envs.lookup(envs.key(uid, su, frozen_context))", src)

    def test_flush_loop_names_and_cap(self) -> None:
        match = re.search(r"MAX_FIXPOINT_ITERATIONS`? \((\d+)\)", DOC_FLAT)
        self.assertIsNotNone(match, "the fixpoint cap is no longer stated")
        transaction = (ROOT / "odoo" / "orm" / "runtime" / "transaction.py").read_text(
            encoding="utf-8"
        )
        declared = re.search(
            r"^MAX_FIXPOINT_ITERATIONS = (\d+)", transaction, re.MULTILINE
        )
        self.assertIsNotNone(declared, "MAX_FIXPOINT_ITERATIONS moved")
        self.assertEqual(int(match.group(1)), int(declared.group(1)))

    def test_flush_entry_points_exist(self) -> None:
        env = (ROOT / "odoo" / "orm" / "runtime" / "environment.py").read_text(
            encoding="utf-8"
        )
        uow = (ROOT / "odoo" / "orm" / "components" / "unit_of_work.py").read_text(
            encoding="utf-8"
        )
        recompute = (
            ROOT / "odoo" / "orm" / "models" / "mixins" / "recompute.py"
        ).read_text(encoding="utf-8")
        for name, src in (
            ("run_flush_loop", uow),
            ("flush_model", recompute),
            ("_flush", recompute),
        ):
            self.assertIn(name, DOC, f"the flush sketch dropped {name}")
            self.assertRegex(src, re.compile(rf"^    def {name}\b", re.MULTILINE))
        self.assertIn("flush_all()", DOC)
        self.assertRegex(env, re.compile(r"^    def flush_all\b", re.MULTILINE))
        self.assertIn("`tolerant_recompute`", DOC)
        self.assertIn('context.get("tolerant_recompute")', env)
        self.assertIn("cr.pipeline()", DOC)
        self.assertIn("with self.cr.pipeline():", env)
