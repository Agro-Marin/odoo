"""The core vocabulary gate, and the four ways a zero-floor gate goes vacuous.

A gate whose floor is zero passes by finding nothing, which is also what it does
when it has stopped looking. Every assertion here is aimed at that: the scan
reaches files, the predicate still recognises what it is named for, the allowlist
holds only names the scan would otherwise report, and the tree really is clean.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import naming_core_vocabulary as ncv
import naming_vocabulary as nv


class TestTheScanReachesSomething(unittest.TestCase):
    def test_it_refuses_an_empty_tree_rather_than_reporting_zero(self):
        with self.assertRaises(RuntimeError) as caught:
            ncv.measure(Path(__file__).with_name("__pycache__"))
        self.assertIn("refusing", str(caught.exception))

    def test_the_scan_reaches_the_core_package(self):
        files = ncv.scan_files()
        self.assertGreater(
            len(files),
            400,
            "the core scan yielded almost nothing; every assertion below would "
            "then pass by looking at an empty list",
        )

    def test_the_framework_tree_is_in_scope(self):
        # odoo/tests is the test framework, not a suite. It is the one tree
        # `_sources.is_test_path` gets wrong, and the reason this gate has its
        # own file-selection rule instead of borrowing that one.
        files = {p.name for p in ncv.scan_files() if p.is_relative_to(ncv.FRAMEWORK)}
        self.assertIn("http.py", files)
        self.assertIn(
            "cursor.py",
            files,
            "cursor.py defines TestCursor, a cursor -- excluding odoo/tests by its "
            "directory name is the mistake this gate exists not to repeat",
        )

    def test_a_real_suite_tree_is_out_of_scope(self):
        files = ncv.scan_files()
        self.assertFalse(
            [p for p in files if "orm" in p.parts and "tests" in p.parts],
            "odoo/orm/tests is a suite and is governed by nothing here",
        )


class TestThePredicateStillRecognisesWhatItIsNamedFor(unittest.TestCase):
    def parse(self, source: str):
        import ast

        return ast.parse(source).body[0]

    def test_a_leading_abolished_verb_is_reported(self):
        hit = ncv.classify_name("_validate_thing")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "leading")

    def test_an_assemble_verb_is_reported_without_a_payload_suffix(self):
        # The sibling reaches a TAILED assemble verb now -- its payload suffix
        # chooses the canonical instead of deciding whether the verb is seen at
        # all -- so this arrives as "leading" rather than through ncv's own
        # ASSEMBLE branch. What still needs this gate is the population, not the
        # word: nv.measure() reads model classes and _build_server is module
        # level. The branch below survives for the bare form, which is the half
        # the sibling still declines.
        self.assertEqual(nv.classify("_build_server"), ("build", "_get_"))
        hit = ncv.classify_name("_build_server")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "leading")

    def test_a_bare_assemble_verb_is_reported(self):
        self.assertIsNone(nv.classify("make"))
        hit = ncv.classify_name("make")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "bare")

    def test_an_unlisted_synonym_of_an_abolished_row_is_reported(self):
        # §2.4.20: the table is families, not a word list. `naming_vocabulary`
        # matches the literal token, so the sibling sees nothing here.
        self.assertIsNone(nv.classify("_prune_counters"))
        hit = ncv.classify_name("_prune_counters")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "synonym")

    def test_a_synonym_behind_a_noun_is_reported(self):
        hit = ncv.classify_name("_setup_refresh_field_depends")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "infix-synonym")

    def test_a_synonym_behind_a_predicate_prefix_is_not_reported(self):
        # A predicate answers a question ABOUT the operation its tail names; it
        # does not perform it, so the tail is the subject and not §2.4.4's
        # hiding place. Four of core's live on one module.
        self.assertIsNone(ncv.classify_name("can_scan_identity"))
        self.assertIsNone(ncv.classify_name("is_refresh_due"))

    def test_an_assemble_synonym_is_reported_without_a_payload_suffix(self):
        self.assertIsNone(nv.classify("_assemble_registry"))
        hit = ncv.classify_name("_assemble_registry")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "assemble")

    def test_the_verbs_the_table_declines_to_add_stay_out(self):
        # Argued in the SYNONYMS comment, and asserted here so that adding one
        # is a decision rather than a diff nobody reads. `emit` is
        # logging.Handler's contract, `reap` and `probe` are terms of art from a
        # layer below, `determine` is a §2.4.9 dispatch question.
        for name in (
            "emit_record",
            "_reap_dead_jobs",
            "probe_connectable",
            "apply_inverse",
        ):
            self.assertIsNone(ncv.classify_name(name), name)

    def test_a_collector_that_returns_what_it_made_is_reported(self):
        node = self.parse(
            "def _collect_stats(rows):\n"
            "    stats = {}\n"
            "    for row in rows:\n"
            "        stats[row] = 1\n"
            "    return stats\n"
        )
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "accumulate")

    def test_a_collector_that_fills_a_parameter_is_not_reported(self):
        # The product is the caller's container and the return is bookkeeping.
        # Four of core's eleven value-returning collectors are this shape.
        node = self.parse(
            "def _collect_batch(rows, batch):\n"
            "    info = None\n"
            "    for row in rows:\n"
            "        info = row\n"
            "        batch.append(row)\n"
            "    return info\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_collector_that_fills_its_receiver_is_not_reported(self):
        node = self.parse(
            "def collect_field(self, name):\n    self.seen.add(name)\n    return name\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_collector_that_fills_a_closure_variable_is_not_reported(self):
        # `seen` is free here: the enclosing function made it, so the product is
        # out there and not in the return.
        node = self.parse(
            "def collect(field):\n    seen.add(field)\n    return field\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_collector_that_returns_nothing_is_not_reported(self):
        node = self.parse("def _collect_files(self):\n    self.files = []\n")
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_check_that_returns_and_never_raises_is_reported(self):
        node = self.parse("def _check_svg(data):\n    return b'<svg' in data\n")
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "check-returns")

    def test_a_check_that_raises_is_not_reported(self):
        # The Validation row IS this: raises on failure. A pass-through return
        # beside a raise is still a check.
        node = self.parse(
            "def _check_name(self, name):\n"
            "    if not name:\n"
            "        raise ValueError(name)\n"
            "    return name\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_check_that_returns_nothing_is_not_reported(self):
        node = self.parse("def _check_date(self):\n    self._assert_ok()\n")
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_producer_that_returns_nothing_is_reported(self):
        for source in (
            "def _get_thing(self):\n    self.thing = 1\n",
            "def _prepare_thing_vals(self, state):\n    state.thing = 1\n",
        ):
            hit = ncv.classify_definition(self.parse(source))
            self.assertIsNotNone(hit, source)
            self.assertEqual(hit[0], "empty-return")

    def test_a_producer_that_always_raises_is_not_reported(self):
        # `ir.qweb`'s restricted rendering mode declines _get_field, _get_widget
        # and _get_asset_nodes. The name is the parent's; renaming the override
        # unhooks it.
        node = self.parse(
            "def _get_field(self, *args):\n"
            "    msg = 'not allowed here'\n"
            "    raise NotImplementedError(msg)\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_protocol_member_is_not_reported(self):
        for source in (
            "def _get_thing(self) -> int: ...\n",
            "def _prepare_thing(self):\n    pass\n",
        ):
            self.assertIsNone(ncv.classify_definition(self.parse(source)), source)

    def test_a_producer_that_creates_records_is_reported(self):
        node = self.parse(
            "def _get_definition_id(self, name):\n"
            "    return self.sudo().create({'name': name}).id\n"
        )
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "producer-writes")

    def test_a_get_or_create_is_already_the_answer(self):
        node = self.parse(
            "def _get_or_create_definition_id(self, name):\n"
            "    return self.sudo().create({'name': name}).id\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_payload_builder_may_call_Command_create(self):
        # `Command.create([...])` IS a one2many payload; matching the attribute
        # name alone would flag the canonical use of the canonical prefix.
        node = self.parse(
            "def _prepare_line_vals(self, lines):\n"
            "    return {'line_ids': [Command.create(v) for v in lines]}\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_file_write_is_not_an_orm_write(self):
        # §2.4.3 reserves read/write for a method whose object is a FILE, so a
        # call spelled `write` is not evidence -- ir.attachment's
        # _prepare_content_vals ends in backend.write(data, checksum).
        node = self.parse(
            "def _prepare_content_vals(self, data, backend):\n"
            "    return {'size': len(data), **backend.write(data)}\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_bare_non_assemble_verb_is_not_reported(self):
        # `delete` alone is a Protocol member in orm/runtime/backend.py and the
        # contract in libs/password.py's neighbourhood. §2.4.6 [review], and the
        # line this gate deliberately does not cross.
        self.assertIsNone(ncv.classify_name("delete"))

    def test_a_dunder_is_not_a_naming_choice(self):
        self.assertIsNone(ncv.classify_name("__init__"))

    def test_a_canonical_name_is_not_reported(self):
        self.assertIsNone(ncv.classify_name("_prepare_invoice_vals"))
        self.assertIsNone(ncv.classify_name("_get_candidate"))


class TestTheAllowlistIsArgued(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(ncv.ALLOWLIST.read_text(encoding="utf-8"))

    def test_every_entry_carries_a_reason(self):
        for name, why in self.raw["names"].items():
            self.assertGreater(
                len(why), 20, f"{name} is allowed with no argument, only a string"
            )

    def test_no_entry_is_dead_weight(self):
        # An allowlist entry that no definition answers to is a name nobody can
        # find and nobody will delete. Every one must be a name the scan would
        # otherwise report.
        allowed = set(self.raw["names"])
        seen = set()
        for path in ncv.scan_files():
            src = path.read_text(encoding="utf-8", errors="ignore")
            seen |= {name for name in allowed if f"def {name}(" in src}
        self.assertEqual(
            allowed - seen,
            set(),
            "these names are allowed and nothing in core defines them -- either "
            "the definition moved or the entry outlived its rename",
        )

    def test_every_entry_would_otherwise_be_reported(self):
        # The allowlist serves both readers. An entry earns its place if the
        # gate would flag the name, or if the candidate finder would raise it as
        # a question -- `fetch` is the second kind, and the entry is what makes
        # it a reservation rather than an open question.
        # Two of the rules read a body, so the name alone cannot answer this any
        # more: the tree is rescanned with the allowlist off and an entry earns
        # its place if a real definition under that name comes back.
        reported = {v.name for v in ncv.measure(apply_allowlist=False)}
        unreachable = {
            name
            for name in self.raw["names"]
            if name not in reported
            and ncv.classify_name(name) is None
            and not ncv.is_bare_abolished(name)
        }
        self.assertEqual(
            unreachable,
            set(),
            "these names are allowed and neither the gate nor the candidate "
            "finder would have raised them, so the entry hides nothing and "
            "reads as a rule that does not exist",
        )


class TestItCatchesAPlantedRegression(unittest.TestCase):
    """Zero on the real tree is also what a broken scan reports.

    Every other assertion here is about the predicate or the file list. These
    two run the gate end to end over a tree that does contain the thing it is
    looking for, which is the only way "0" is evidence of anything.
    """

    def plant(self, source: str) -> list[ncv.Violation]:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "planted.py").write_text(source, encoding="utf-8")
            return ncv.measure(Path(tmp))

    def test_an_assemble_verb_with_no_payload_suffix_fails_the_gate(self):
        found = self.plant("def _build_server(app):\n    return app\n")
        self.assertEqual([v.name for v in found], ["_build_server"])
        self.assertEqual(found[0].kind, "leading")

    def test_a_bare_verb_and_a_nested_closure_both_fail_the_gate(self):
        found = self.plant(
            "class Speedscope:\n"
            "    def make(self):\n"
            "        def make_node_info(node):\n"
            "            return node\n"
            "        return make_node_info\n"
        )
        self.assertEqual(sorted(v.name for v in found), ["make", "make_node_info"])

    def test_an_override_of_a_third_party_name_does_not_fail_the_gate(self):
        # WSGIRequestHandler.make_environ is werkzeug's; renaming it is not a
        # rename, it is a silent unhooking.
        found = self.plant(
            "class Handler:\n"
            "    def make_environ(self):\n"
            "        return super().make_environ()\n"
        )
        self.assertEqual(found, [])

    def test_a_synonym_fails_the_gate_end_to_end(self):
        found = self.plant("def _sweep_stale_rows(cr):\n    return cr\n")
        self.assertEqual([v.name for v in found], ["_sweep_stale_rows"])
        self.assertEqual(found[0].kind, "synonym")

    def test_a_body_aware_rule_fails_the_gate_end_to_end(self):
        # classify_name cannot see either of these; measure() must be calling
        # classify_definition, and this is what says so.
        found = self.plant(
            "def _check_webp(data):\n"
            "    return data[:4] == b'RIFF'\n"
            "\n"
            "def _collect_stats(rows):\n"
            "    stats = {}\n"
            "    for row in rows:\n"
            "        stats[row] = 1\n"
            "    return stats\n"
        )
        self.assertEqual(
            sorted((v.name, v.kind) for v in found),
            [("_check_webp", "check-returns"), ("_collect_stats", "accumulate")],
        )

    def test_an_allowlisted_name_does_not_fail_the_gate(self):
        found = self.plant("def append_paths(self, paths):\n    return paths\n")
        self.assertEqual(found, [])


class TestRealTree(unittest.TestCase):
    def test_nothing_outside_the_framework_tree_is_left(self):
        # The assemble-verb sweep took the whole core package but odoo/tests to zero
        # on this vocabulary, and left that tree to the sweep already running
        # inside it. The COUNT of what remains there is the naming_core floor's
        # job -- it is six at the time of writing and goes to zero the moment
        # that sweep lands, so asserting it here would break on their commit and
        # again on the re-bank. What does not move is the boundary: a finding
        # anywhere else is a regression whatever the floor says.
        outside = [v for v in ncv.measure() if "/tests/" not in v.path]
        self.assertEqual(
            [str(v) for v in outside],
            [],
            "a finding outside odoo/tests. Rename it, or argue it into "
            "naming_core_allowlist.json with the reason it survives — the "
            "floor is for the framework sweep's remainder and covers nothing "
            "else.",
        )

    def test_a_base_extension_point_is_a_declaration_and_not_a_finding(self):
        # Three spellings of "declares a shape, supplies no behaviour": `...`,
        # `pass`, and a lone `return`/`return None`. The third is the ORM's
        # dialect -- a base hook a dependent overrides -- and it was three live
        # findings in addons/base before the rule learned it:
        # _get_zip_detached_reader (cloud_storage overrides), _get_mfa_type and
        # _get_mfa_url (auth_totp, auth_totp_mail, l10n_au_hr_payroll_api).
        import ast

        for body in ("...", "pass", "return", "return None"):
            with self.subTest(body):
                node = ast.parse(f"def _get_mfa_type(self):\n    {body}\n").body[0]
                self.assertTrue(ncv.is_declaration_only(node))
                self.assertIsNone(ncv.classify_definition(node))

    def test_a_producer_that_returns_nothing_after_doing_work_is_still_a_finding(self):
        # The exclusion is for a body that is ONLY the declaration. One that
        # does work and then produces nothing is what `empty-return` is for, and
        # widening the stub rule must not swallow it.
        import ast

        node = ast.parse(
            "def _get_rows(self):\n    self.env['x'].search([])\n    return None\n"
        ).body[0]
        self.assertFalse(ncv.is_declaration_only(node))
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "empty-return")

    def test_the_candidate_population_is_reported_and_not_gated(self):
        # It is allowed to shrink to nothing -- that would mean somebody read
        # them all -- but it must not be silently empty because the finder broke.
        found = ncv.candidates()
        # Two groups now, not one: bare abolished verbs, and the kinds this
        # scope declines to gate because nobody has read the population --
        # `resolve-total` in core. Both are printed for the same reason, so the
        # assertion is that every kind is a KNOWN candidate kind rather than
        # that there is only one.
        expected = {"bare-review"} | {
            f"{kind}-review" for kind in ncv.UNSWEPT_IN_CORE_KINDS
        }
        for item in found:
            self.assertIn(item.kind, expected)
        self.assertNotIn(
            "fetch",
            {item.name for item in found},
            "fetch is settled by the allowlist and is not a candidate",
        )


if __name__ == "__main__":
    unittest.main()
