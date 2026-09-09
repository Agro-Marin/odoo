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

    def test_a_predicate_hiding_behind_detect_is_reported(self):
        # `detect` names neither row it can belong to, so the body picks: the
        # six in addons/mail all returned a computed bool and became
        # `_is_` / `_has_`. `_detect_is_bounce` is the entry's whole argument in
        # one name -- a predicate that has to say `is` in the middle because a
        # verb took the front.
        for name in ("_detect_is_bounce", "_detect_loop_headers"):
            with self.subTest(name):
                hit = ncv.classify_name(name)
                self.assertIsNotNone(hit, name)
                self.assertEqual(hit[0], "synonym")

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

    def test_a_predicate_that_raises_is_reported(self):
        # The mirror of `check-returns`. §2.4.3's Predicate row says "never
        # raises, no side effect"; the Validation row is the one that raises on
        # failure, so this asserts the opposite of what it does.
        node = self.parse(
            "def _can_confirm_state(self):\n"
            "    wrong = self.filtered(lambda o: o.state != 'draft')\n"
            "    if not wrong:\n"
            "        return\n"
            "    raise UserError('nope')\n"
        )
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "predicate-raises")

    def test_an_abstract_predicate_whose_whole_body_raises_is_not_reported(self):
        # A base declaring a contract for its overrides. The name describes what
        # the OVERRIDE returns, so there is no body to judge it on -- a class of
        # name, like `is_declaration_only`, not an allowlist entry.
        node = self.parse(
            "def _is_insertion_blocked(self, user):\n"
            '    """Returns True if insertion should be blocked."""\n'
            "    raise NotImplementedError\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_the_abstract_test_is_not_always_raises(self):
        # `nv._always_raises` asks whether the LAST statement is a raise, which
        # is true of every validator that guards with an early return. Reusing it
        # here exempted two of the eight definitions the rule was written for,
        # and the count stayed plausible because it fell to 6 rather than to 0.
        guarded = self.parse(
            "def _can_confirm_state(self):\n"
            "    if not self.wrong:\n"
            "        return\n"
            "    raise UserError('nope')\n"
        )
        self.assertTrue(nv._always_raises(guarded))
        self.assertFalse(ncv._is_abstract_raise(guarded))
        self.assertEqual(ncv.classify_definition(guarded)[0], "predicate-raises")

    def test_a_predicate_that_raises_but_also_returns_is_not_reported(self):
        # It answers a question and raises on a bad argument, which is ordinary.
        node = self.parse(
            "def _is_ok(self, x):\n"
            "    if x is None:\n"
            "        raise ValueError(x)\n"
            "    return x > 0\n"
        )
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

    def test_an_abolished_verb_in_the_last_token_is_reported(self):
        # nv.infix_abolished_verb scans tokens[1:-1], so the last token is read
        # by nothing -- classify never reaches it and the infix rule stops one
        # short of it on purpose.
        for name in ("_relation_delete", "_compile_and_validate", "_term_lookup"):
            self.assertIsNone(nv.infix_abolished_verb(name), name)
            hit = ncv.classify_name(name)
            self.assertIsNotNone(hit, name)
            self.assertEqual(hit[0], "trailing", name)

    def test_a_synonym_in_the_last_token_is_reported(self):
        hit = ncv.classify_name("_get_rows_to_purge")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "trailing")

    def test_the_reserved_orm_read_is_exempt_in_the_last_token(self):
        # `fetch` is §2.4.3's reserved ORM operation and lands there correctly:
        # _get_fields_to_fetch names the operand set of fetch().
        for name in ("_get_fields_to_fetch", "search_fetch", "_prefetch_field_fetch"):
            self.assertIsNone(ncv.classify_name(name), name)

    def test_domain_is_exempt_in_the_last_token(self):
        # §2.4.1 makes it right on both sides: the field-hook spelling and the
        # ordinary Read. 48 of stock's were read by hand and none was a verb.
        for name in ("_get_company_domain", "_domain_partner_id", "_get_x_domain"):
            self.assertIsNone(ncv.classify_name(name), name)

    def test_an_assemble_verb_in_the_last_token_is_reported_unconditionally(self):
        # The shared table makes them payload-only, and that carve-out cannot
        # survive in this position: a verb that is LAST is what the name ends
        # with, so it can never also end in `_vals`. Reading payload_only here
        # makes the branch unreachable and exempts every `_report_build`.
        hit = ncv.classify_name("_report_build")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "trailing")
        self.assertIsNone(nv.infix_abolished_verb("_report_build"))

    def test_a_single_token_name_has_no_trailing_position(self):
        self.assertIsNone(ncv.trailing_abolished_verb("delete"))
        self.assertIsNone(ncv.trailing_abolished_verb("_lookup"))

    def test_a_resolve_annotated_optional_is_a_partial_producer(self):
        # The body cannot show it: one `return status`, and whether that is None
        # is a runtime question. The annotation is the contract.
        for hint in ("CompletionStatus | None", "Optional[str]", "Union[int, None]"):
            node = self.parse(f"def _resolve_attempt(job) -> {hint}:\n    return s\n")
            self.assertTrue(ncv.annotates_optional(node), hint)
            self.assertIsNone(ncv.classify_definition(node), hint)

    def test_a_resolve_annotated_total_is_still_a_finding(self):
        # The exclusion must not swallow what the rule is for.
        node = self.parse(
            "def _resolve_scope(self, user_id) -> tuple[int, int]:\n"
            "    return user_id, 1\n"
        )
        self.assertFalse(ncv.annotates_optional(node))
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "resolve-total")

    def test_an_unannotated_resolve_is_judged_on_its_body_as_before(self):
        node = self.parse("def _resolve_thing(self):\n    return 1\n")
        self.assertFalse(ncv.annotates_optional(node))
        self.assertIsNotNone(ncv.classify_definition(node))

    def test_a_bare_non_assemble_verb_is_not_reported(self):
        # `delete` alone is a Protocol member in orm/runtime/backend.py and the
        # contract in libs/password.py's neighbourhood. §2.4.6 [review], and the
        # line this gate deliberately does not cross.
        self.assertIsNone(ncv.classify_name("delete"))

    def test_a_show_that_answers_a_question_is_a_predicate(self):
        # §2.4.20's fourth predicate prefix. It is out of the SHARED table for a
        # reason about that table rather than about the verb -- an `ABOLISHED`
        # entry prints ONE canonical and this family has three -- so the rule
        # belongs here, where the `why` is free-form and can print all three.
        node = self.parse(
            "def _show_discount(self):\n"
            "    if not self:\n"
            "        return False\n"
            "    return self.compute_price == 'percentage'\n"
        )
        self.assertIsNone(ncv.classify_name("_show_discount"))
        hit = ncv.classify_definition(node)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "show-predicate")

    def test_a_show_that_returns_a_truthy_operand_is_not_a_predicate(self):
        # The Predicate row's own warning: the return TYPE is not the test. A
        # `show_*` returning a recordset or a truthy operand is not answering a
        # question, and sale's nested `show_line` is exactly that shape.
        node = self.parse(
            "def show_line(line):\n    return line.display_type and lines\n"
        )
        self.assertIsNone(ncv.classify_definition(node))

    def test_a_call_to_a_predicate_is_evidence_of_a_computed_boolean(self):
        # §2.4.3's Predicate row is a CONTRACT -- "the returned `bool` is the
        # answer to a question about the subject" -- so a `self._is_x()` is a
        # boolean on the vocabulary's own authority, read like `bool(...)`.
        # Without this the `and` below fails on its first operand and the
        # clearest member of the `_show_` family reads as a non-predicate.
        node = self.parse(
            "def _show_discount(self):\n"
            "    if not self:\n"
            "        return False\n"
            "    return self._is_feature_enabled() and self.price == 'pct'\n"
        )
        self.assertTrue(ncv.answers_a_question(node))
        self.assertEqual(ncv.classify_definition(node)[0], "show-predicate")

    def test_a_call_to_something_that_is_not_a_predicate_is_not(self):
        node = self.parse(
            "def _show_thing(self):\n    return self._compute_it() and self.x\n"
        )
        self.assertFalse(ncv.answers_a_question(node))

    def test_the_two_synonyms_this_sweep_added_are_reported(self):
        # Both are §2.4.20's shape: a row of the abolished table performed under
        # a word nobody listed, invisible to the sibling by construction.
        for name, kind in (
            ("_tweak_notify_recipient_groups", "synonym"),
            ("_synchronize_crons", "synonym"),
        ):
            with self.subTest(name=name):
                self.assertIsNone(nv.classify(name))
                hit = ncv.classify_name(name)
                self.assertIsNotNone(hit)
                self.assertEqual(hit[0], kind)

    def test_the_synchronize_entry_names_both_canonicals(self):
        # The entry is the renamer's instruction, and this family splits: five
        # of the workspace's eight converge on a source of truth elsewhere and
        # are §2.4.3's reserved `_sync_`, three RETURN a values dict and are the
        # Payload row. An entry printing `_sync_` alone would send those three
        # to the wrong row -- the reservation losing to the synonym table.
        canonical, why = ncv.SYNONYMS["synchronize"]
        self.assertIn("_sync_", canonical)
        self.assertIn("_prepare_", canonical)
        self.assertIn("values", why)

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
        # Two sources, and one of them is empty again: bare abolished verbs,
        # plus whatever kinds a scope declines to gate because nobody has read
        # the population. `resolve-total` was the second group and its nineteen
        # have been read, so UNSWEPT_IN_CORE_KINDS is empty and this reduces to
        # the bare verbs. That is the tighter assertion, not a weaker one -- a
        # `resolve-total-review` appearing here now FAILS. The set stays a set
        # because the next unswept rule belongs in it.
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


class TestTheShapingRuleReadsTheReceiver(unittest.TestCase):
    """§2.4.22: one ORM shaping call produces nothing, so it is not a producer.

    Every assertion here is about a narrowing rather than about the rule, because
    the rule is one line and the narrowings are the whole of why it reads zero in
    core rather than reporting every read that ends in a `filtered`.
    """

    def parse(self, source: str):
        import ast
        import textwrap

        return ast.parse(textwrap.dedent(source)).body[0]

    def test_a_body_that_is_one_filtered_on_self_is_reported(self):
        hit = ncv.classify_definition(
            self.parse(
                """
                def _get_open_moves(self):
                    return self.filtered(lambda m: m.state != "done")
                """
            )
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "shaping")
        self.assertIn("_filtered_", hit[1])

    def test_each_shape_asks_for_its_own_prefix(self):
        for call, prefix in (
            ("filtered(lambda m: m.x)", "_filtered_"),
            ("filtered_domain([])", "_filtered_"),
            ("sorted('date')", "_sorted_"),
            ("grouped('partner_id')", "_grouped_"),
            ("with_context(active_test=False)", "_with_"),
            ("sudo()", "_with_"),
        ):
            hit = ncv.classify_definition(
                self.parse(f"def _get_rows(self):\n    return self.{call}\n")
            )
            self.assertIsNotNone(hit, call)
            self.assertIn(prefix, hit[1], call)

    def test_the_canonical_spelling_is_not_reported(self):
        for name, call in (
            ("_filtered_open", "filtered(lambda m: m.x)"),
            ("_sorted_by_date", "sorted('date')"),
            ("_grouped_by_partner", "grouped('partner_id')"),
            ("_with_stock_context", "with_context(x=1)"),
        ):
            self.assertIsNone(
                ncv.classify_definition(
                    self.parse(f"def {name}(self):\n    return self.{call}\n")
                ),
                name,
            )

    def test_a_navigation_before_the_filter_is_a_read_and_not_a_narrowing(self):
        # §2.4.22 excludes a body returning rows the caller never held. This is
        # `stock.move.line._get_pending_dest_moves`, which is correct as it
        # stands: what comes back is not a subset of the receiver.
        self.assertIsNone(
            ncv.classify_definition(
                self.parse(
                    """
                    def _get_pending_dest_moves(self):
                        return self.move_id.move_dest_ids.filtered(lambda m: m.x)
                    """
                )
            )
        )

    def test_a_with_prefixed_call_that_is_not_an_orm_envelope_is_not_reshaping(self):
        # The measured false positive that made the envelope list explicit:
        # assetsbundle's `minify` is `return self.with_header()` on a plain
        # class, and what comes back is a string.
        self.assertIsNone(
            ncv.classify_definition(
                self.parse("def minify(self):\n    return self.with_header()\n")
            )
        )

    def test_more_than_one_statement_is_a_read(self):
        self.assertIsNone(
            ncv.classify_definition(
                self.parse(
                    """
                    def _get_late_moves(self):
                        self.env["stock.move"].flush_model()
                        return self.filtered(lambda m: m.late)
                    """
                )
            )
        )


class TestTheModelNounRuleReadsTheClass(unittest.TestCase):
    """§2.4.4: a first token repeating the model is what hides the verb."""

    def parse_class(self, source: str):
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(source))
        return next(
            (node, cls)
            for cls in ast.walk(tree)
            if isinstance(cls, ast.ClassDef)
            for node, _ in ncv.definitions(tree)
            if node in cls.body
        )

    MODEL = """
        class StockWarehouse(models.Model):
            _name = "stock.warehouse"

            def _warehouse_redirect_warning(self):
                raise UserError("no warehouse")
        """

    def test_the_models_own_noun_in_first_position_is_reported(self):
        node, cls = self.parse_class(self.MODEL)
        hit = ncv.classify_definition(node, cls)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "model-noun")
        self.assertIn("warehouse", hit[1])

    def test_the_same_name_off_a_model_class_is_not_reported(self):
        # The rule's whole content is the receiver's name, so a definition with
        # no model class behind it has nothing to repeat. This is also what a
        # closure inside a method gets, which is why `definitions` drops the
        # class when it descends into one.
        node, _cls = self.parse_class(self.MODEL)
        self.assertIsNone(ncv.classify_definition(node, None))

    def test_a_verb_that_happens_to_be_in_the_model_name_is_not_reported(self):
        # Without this the rule is a report about wizard model names: a model
        # called `...merge...` makes every `_merge_*` on it a finding.
        node, cls = self.parse_class(
            """
            class PartnerMerge(models.TransientModel):
                _name = "base.partner.merge.automatic.wizard"

                def _merge_bank_accounts(self):
                    return True
            """
        )
        self.assertIsNone(ncv.classify_definition(node, cls))

    def test_an_inherited_mixin_is_a_protocol_and_not_the_models_own_name(self):
        # §2.4.4 licenses a noun-first prefix where it names a protocol several
        # models implement. A class carrying `_name` alongside `_inherit` is a
        # model MIXING IN protocols, so a mixin's noun in leading position is
        # the licensed case. Reading `_inherit` as the model's own name turned
        # `mixin.order.merge`'s deliberate 21-name convention into 21 findings
        # across base_order, sale and purchase.
        node, cls = self.parse_class(
            """
            class SaleOrderLine(models.Model):
                _name = "sale.order.line"
                _inherit = ["mixin.order.line", "mixin.order.merge"]

                def _merge_group_orders(self):
                    return True
            """
        )
        self.assertIsNone(ncv.classify_definition(node, cls))

    def test_inherit_alone_is_the_model_this_class_extends(self):
        # The other half, and the one the rule was written for: this fork splits
        # a model across extension classes by seam (§2.4.13), and such a class
        # has no `_name`. `stock.picking.type`'s dashboard is exactly this, and
        # `_picking_count_buckets` was found on this evidence.
        node, cls = self.parse_class(
            """
            class StockPickingTypeDashboard(models.Model):
                _inherit = "stock.picking.type"

                def _picking_count_buckets(self, query):
                    return {}
            """
        )
        hit = ncv.classify_definition(node, cls)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "model-noun")

    def test_the_converter_idiom_names_its_source_first_by_construction(self):
        node, cls = self.parse_class(
            """
            class Partner(models.Model):
                _name = "res.partner"

                def partner_to_vcard(self):
                    return b""
            """
        )
        self.assertIsNone(ncv.classify_definition(node, cls))

    def test_a_multi_token_converter_is_recognised_too(self):
        # `nv._CONVERTER_IDIOM` wants a single token on each side, so it cannot
        # see this one; the rule carries its own test for that reason.
        self.assertIsNone(ncv.model_noun_first("date_category_to_domain", None))
        self.assertIsNotNone(ncv._CONVERTER_IDIOM.fullmatch("date_category_to_domain"))
        self.assertIsNone(nv._CONVERTER_IDIOM.fullmatch("date_category_to_domain"))

    def test_a_prefix_several_model_classes_declare_is_a_protocol_namespace(self):
        # §2.4.4 licenses a noun-first prefix where it names a protocol several
        # models implement, and gives the test: would it survive being moved to
        # another model. Counting the declarers is that test, and it is what
        # takes `addons/mail` from 99 findings to 13.
        import ast
        import textwrap

        source = textwrap.dedent(
            """
            class MailThread(models.AbstractModel):
                _name = "mail.thread"

                def _mail_get_partners(self):
                    return {}

            class Partner(models.Model):
                _name = "res.partner"

                def _mail_get_partners(self):
                    return {}
            """
        )
        tree = ast.parse(source)
        path = Path(__file__).with_name("__planted_mail__.py")
        path.write_text(source, encoding="utf-8")
        try:
            namespaces = ncv.protocol_namespaces([path])
        finally:
            path.unlink()
        self.assertIn("mail", namespaces)
        node, cls = next(
            (node, cls) for node, cls in ncv.definitions(tree) if cls is not None
        )
        self.assertIsNotNone(ncv.classify_definition(node, cls))
        self.assertIsNone(ncv.classify_definition(node, cls, namespaces))

    def test_a_two_token_run_used_behind_a_verb_is_a_namespace(self):
        # §2.4.4's other sentence: for a leading run of two or more tokens, ask
        # whether those tokens name something that exists in the system. Three
        # methods naming the *project sharing* feature behind their own verbs
        # are that evidence, and they are why
        # `project_sharing_toggle_is_follower` is a namespace at the head rather
        # than `project.task`'s own noun leaking into first position.
        import ast
        import textwrap

        source = textwrap.dedent(
            """
            class ProjectTask(models.Model):
                _name = "project.task"

                def project_sharing_toggle_is_follower(self):
                    return True

                def _get_project_sharing_company(self):
                    return self.company_id

                def _is_project_sharing_accessible(self):
                    return True
            """
        )
        path = Path(__file__).with_name("__planted_sharing__.py")
        path.write_text(source, encoding="utf-8")
        try:
            namespaces = ncv.protocol_namespaces([path])
        finally:
            path.unlink()
        self.assertIn(("project", "sharing"), namespaces)
        node, cls = next(
            (node, cls)
            for node, cls in ncv.definitions(ast.parse(source))
            if node.name == "project_sharing_toggle_is_follower"
        )
        self.assertIsNotNone(ncv.classify_definition(node, cls))
        self.assertIsNone(ncv.classify_definition(node, cls, namespaces))

    def test_the_same_wrong_prefix_twice_is_not_a_namespace(self):
        # The narrowing that makes the pair rule a rule. Without the verb-head
        # requirement `_channel_type_policies` and `_channel_type_policy` exempt
        # each other -- one wrong prefix, written twice -- and `channel_join`
        # is exempted by `discuss_channel_join`, which is a concatenation and
        # not a concept. Both must stay findings.
        import ast
        import textwrap

        source = textwrap.dedent(
            """
            class DiscussChannel(models.Model):
                _name = "discuss.channel"

                def _channel_type_policies(self):
                    return {}

                def _channel_type_policy(self):
                    return {}

                def channel_join(self):
                    return True

                def discuss_channel_join(self):
                    return True
            """
        )
        path = Path(__file__).with_name("__planted_channel__.py")
        path.write_text(source, encoding="utf-8")
        try:
            namespaces = ncv.protocol_namespaces([path])
        finally:
            path.unlink()
        self.assertNotIn(("channel", "type"), namespaces)
        self.assertNotIn(("channel", "join"), namespaces)
        reported = {
            node.name
            for node, cls in ncv.definitions(ast.parse(source))
            if ncv.classify_definition(node, cls, namespaces)
        }
        # `discuss_channel_join` is in the set for the same reason and not by
        # accident: `discuss` is the model's noun too, so the witness that
        # would have exempted `channel_join` is itself a finding.
        self.assertEqual(
            reported,
            {
                "_channel_type_policies",
                "_channel_type_policy",
                "channel_join",
                "discuss_channel_join",
            },
        )

    def test_the_rule_is_held_back_in_core_and_printed_instead(self):
        # Core's 19 are mostly wizards whose model name IS the operation, and
        # nobody has read them. A rule that is neither blocking nor printed has
        # been dropped rather than deferred.
        self.assertIn("model-noun", ncv.UNSWEPT_IN_CORE_KINDS)
        self.assertNotIn("model-noun", ncv.CORE_ONLY_KINDS)


class TestTheNewRulesCatchAPlantedRegression(unittest.TestCase):
    def plant(self, source: str) -> list[ncv.Violation]:
        import tempfile
        import textwrap

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "planted.py").write_text(
                textwrap.dedent(source), encoding="utf-8"
            )
            return ncv.measure(Path(tmp), addon="stock")

    def test_a_shaping_body_fails_the_gate_end_to_end(self):
        found = self.plant(
            """
            class StockMove(models.Model):
                _name = "stock.move"

                def _get_open_moves(self):
                    return self.filtered(lambda m: m.state != "done")
            """
        )
        self.assertEqual(
            [(v.name, v.kind) for v in found], [("_get_open_moves", "shaping")]
        )

    def test_a_model_noun_first_name_fails_the_gate_end_to_end(self):
        # measure() has to be building the namespace index and carrying the
        # class down the walk; a rule that only worked through
        # classify_definition would pass every unit test above and report
        # nothing here.
        found = self.plant(
            """
            class StockWarehouse(models.Model):
                _name = "stock.warehouse"

                def _warehouse_redirect_warning(self):
                    raise UserError("no warehouse")
            """
        )
        self.assertEqual(
            [(v.name, v.kind) for v in found],
            [("_warehouse_redirect_warning", "model-noun")],
        )

    def test_a_closure_inside_a_method_is_not_declared_on_the_model(self):
        found = self.plant(
            """
            class StockWarehouse(models.Model):
                _name = "stock.warehouse"

                def _get_codes(self):
                    def warehouse_code(record):
                        return record.code
                    return [warehouse_code(w) for w in self]
            """
        )
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
