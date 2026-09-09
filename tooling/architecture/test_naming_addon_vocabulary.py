"""The vocabulary gate pointed at a bundled addon, and the ways that goes vacuous.

`test_naming_core_vocabulary` asks whether the gate still sees the core package.
This file asks the two questions a second scope adds, and neither is answered by
the first:

* **Does the scope reach anything?** A `--addon` whose directory is wrong scans
  an empty tree, and a gate that has stopped looking reports the same zero as a
  clean one.
* **Do the scopes stay apart?** The allowlist is keyed by name, so a flat list
  shared across scopes would exempt a stock method because a core function of
  the same name was argued years earlier. §2.4.20 records two definitions of
  `_check_path` in one tree precisely to say that a name is not unique.

The third question is the one that decided which rules travel. §2.4.4's infix
rules cannot tell a verb parked behind a noun from a noun spelled like a verb;
core gates them because core was swept by hand, and `addons/stock` is where the
difference is legible -- all four of its infix hits are `assign`, which is that
module's own operation. Those two rules stay behind, and the assertion that they
do is here rather than in a comment.
"""

from __future__ import annotations

import ast
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import naming_core_vocabulary as ncv
import naming_vocabulary as nv

# One definition per rule that travels to an addon scope, plus one infix name
# that must not. Planted rather than cited from the tree: a fixture quoting a
# real method stops being a fixture the moment somebody renames it, and this
# file's whole subject is what happens when a scan stops matching.
PLANTED = """
class StockThing(models.Model):
    _name = "stock.thing"

    def _get_nothing(self):
        self.env["stock.quant"].search([])

    def check_it(self):
        return True

    def _collect_rows(self):
        rows = []
        rows.append(1)
        return rows

    def _get_rows(self):
        self.env["stock.quant"].create({})
        return 1

    def _push_and_assign_downstream(self):
        pass
"""


class TestEveryGovernedScopeReachesSomething(unittest.TestCase):
    def test_every_scope_names_a_directory_that_exists(self):
        for addon in ncv.GOVERNED_ADDONS:
            src = ncv.addon_src(addon)
            self.assertTrue(src.is_dir(), f"{addon} -> {src} is not a directory")

    def test_every_scope_scans_more_than_a_handful_of_files(self):
        for addon in ncv.GOVERNED_ADDONS:
            files = ncv.scan_files(ncv.addon_src(addon))
            self.assertGreater(
                len(files),
                20,
                f"the {addon} scan yielded {len(files)} files; a zero from this "
                f"scope would mean it had stopped looking",
            )

    def test_an_addon_scope_refuses_an_empty_tree(self):
        with self.assertRaises(RuntimeError) as caught:
            ncv.measure(Path(__file__).with_name("__pycache__"), addon="stock")
        self.assertIn("refusing", str(caught.exception))

    def test_a_scope_the_gate_does_not_govern_is_refused_at_the_cli(self):
        with self.assertRaises(SystemExit):
            ncv.main(["--addon", "an_addon_nobody_has_read", "--count"])


class TestTheBodyRulesTravelAndTheSpellingRulesDoNot(unittest.TestCase):
    def plant(self, addon: str) -> dict[str, str]:
        tree = ast.parse(textwrap.dedent(PLANTED))
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if (hit := ncv.classify_definition(node)) is None:
                continue
            if addon != "core" and hit[0] in ncv.CORE_ONLY_KINDS:
                continue
            found[node.name] = hit[0]
        return found

    def test_all_four_body_rules_fire_in_an_addon_scope(self):
        self.assertEqual(
            self.plant("stock"),
            {
                "_get_nothing": "empty-return",
                "check_it": "check-returns",
                "_collect_rows": "accumulate",
                "_get_rows": "producer-writes",
            },
        )

    def test_the_infix_rule_fires_in_core_and_not_in_an_addon_scope(self):
        self.assertEqual(self.plant("core").get("_push_and_assign_downstream"), "infix")
        self.assertNotIn("_push_and_assign_downstream", self.plant("stock"))

    def test_the_sibling_gate_reports_none_of_the_four(self):
        # The reason the scope was added at all: `naming_vocabulary` matches a
        # literal abolished token in a leading position, and not one of the four
        # wears one, so the addon floor it feeds reads zero over all of them.
        for name in ("_get_nothing", "check_it", "_collect_rows", "_get_rows"):
            self.assertIsNone(nv.classify(name), name)


class TestTheScopedAllowlistDoesNotLeak(unittest.TestCase):
    def test_a_core_entry_does_not_exempt_an_addon_definition(self):
        core = set(ncv.load_allowlist("core"))
        self.assertTrue(core, "the core allowlist is empty; this proves nothing")
        for addon in ncv.GOVERNED_ADDONS:
            if addon == "core":
                continue
            self.assertFalse(
                core & set(ncv.load_allowlist(addon)),
                f"{addon} and core share an allowlist entry, so one scope's "
                f"argument is silently answering for the other's",
            )

    def test_an_unread_scope_gets_no_allowlist_rather_than_the_core_one(self):
        self.assertEqual(ncv.load_allowlist("a_scope_with_no_entries"), {})

    def test_every_scoped_entry_is_a_name_the_scan_would_otherwise_report(self):
        # An entry that hides nothing is dead weight, and worse than dead: it
        # reads as a settled argument about a name no rule reaches any more.
        for addon in ncv.GOVERNED_ADDONS:
            if addon == "core":
                continue
            allowed = ncv.load_allowlist(addon)
            if not allowed:
                continue
            reported = {
                v.name
                for v in ncv.measure(
                    ncv.addon_src(addon), apply_allowlist=False, addon=addon
                )
            }
            self.assertEqual(
                set(allowed) - reported,
                set(),
                f"{addon}: allowlist entries no rule reports any more",
            )

    def test_every_scoped_entry_carries_an_argument(self):
        # Scoped entries only. The core list predates this file and holds
        # several one-line reservations that are entirely adequate for a term
        # of art (`fetch` is the ORM read operation, and that is the whole
        # argument); an addon entry is exempting a name in a tree nobody has
        # read end to end, so it owes the reasoning rather than the label.
        for addon in ncv.GOVERNED_ADDONS:
            if addon == "core":
                continue
            for name, why in ncv.load_allowlist(addon).items():
                self.assertGreater(
                    len(why), 60, f"{addon}:{name} is allowed without an argument"
                )


class TestResolveIsReservedForAPartialProducer(unittest.TestCase):
    def parse(self, source: str):
        return ast.parse(textwrap.dedent(source)).body[0]

    def test_a_resolve_that_always_produces_is_reported(self):
        hit = ncv.classify_definition(
            self.parse("def _resolve_products(self):\n    return self.ids\n")
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "resolve-total")

    def test_the_four_spellings_of_not_applicable_are_all_recognised(self):
        # Every one of these was a false positive the rule produced against a
        # real tree before the spelling was added. They are the reason the
        # population is four and not seven.
        for label, source in (
            (
                "bare return",
                "def _resolve_a(self):\n    if x:\n        return\n    return 1\n",
            ),
            (
                "explicit None",
                "def _resolve_b(self):\n    if x:\n        return None\n    return 1\n",
            ),
            (
                "empty recordset",
                "def _resolve_c(self):\n    if x:\n        return self.browse()\n    return self\n",
            ),
            (
                "ternary None",
                "def _resolve_d(self):\n    return None if x is None else (x, 1)\n",
            ),
        ):
            with self.subTest(label):
                self.assertIsNone(ncv.classify_definition(self.parse(source)), label)

    def test_it_is_now_gated_in_every_scope(self):
        # It was held back in core while the nineteen went unread. They have
        # been read -- five were partial by ANNOTATION, six were ordinary
        # producers and are renamed, eight are the name-resolution sense and are
        # argued into the allowlist -- so the kind gates everywhere.
        self.assertNotIn("resolve-total", ncv.UNSWEPT_IN_CORE_KINDS)
        self.assertNotIn("resolve-total", ncv.CORE_ONLY_KINDS)


class TestAGetThatAnswersAQuestionIsAPredicate(unittest.TestCase):
    def parse(self, source: str):
        return ast.parse(textwrap.dedent(source)).body[0]

    def test_a_get_returning_a_computed_bool_is_reported(self):
        hit = ncv.classify_definition(
            self.parse("def _get_locked(self):\n    return self.state == 'done'\n")
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "bool-under-get")

    def test_a_stub_returning_only_the_literal_false_is_not_reported(self):
        # §2.4.3: "the return type is not the test". A hook's default returns
        # False and its overrides return a value -- ir.ui.view.get_formview_id
        # and _get_placeholder_filename are core's two, and a rule keyed on the
        # TYPE would have demanded a predicate name from both.
        self.assertIsNone(
            ncv.classify_definition(
                self.parse("def get_formview_id(self):\n    return False\n")
            )
        )

    def test_an_or_of_non_booleans_is_not_a_boolean(self):
        # `a or b` yields an OPERAND. Reading it as boolean reported _get_lang
        # and five like it, whose operands are strings.
        self.assertIsNone(
            ncv.classify_definition(
                self.parse(
                    "def _get_lang(self):\n    return self.partner_id.lang or self.env.lang\n"
                )
            )
        )

    def test_a_predicate_prefix_is_not_reported_for_returning_a_bool(self):
        for name in ("_is_locked", "_has_lot", "_can_ship"):
            with self.subTest(name):
                self.assertIsNone(
                    ncv.classify_definition(
                        self.parse(
                            f"def {name}(self):\n    return self.state == 'done'\n"
                        )
                    )
                )


class TestWhatAScopeDeclinesToGateIsStillPrinted(unittest.TestCase):
    """A rule that is neither blocking nor printed has been dropped, not deferred."""

    def test_core_no_longer_prints_a_resolve_population(self):
        # The complement of the assertion this replaces: core gates the kind
        # now, so nothing of it may reach the candidate list. A
        # `resolve-total-review` appearing here again means a finding is being
        # printed where it should be failing.
        kinds = {v.kind for v in ncv.candidates()}
        self.assertNotIn("resolve-total-review", kinds)
        self.assertTrue(kinds, "the candidate finder returned nothing at all")

    def test_an_addon_prints_the_infix_population_it_does_not_gate(self):
        kinds = {v.kind for v in ncv.candidates(addon="stock")}
        self.assertIn("infix-review", kinds)

    def test_every_held_back_kind_is_reachable_from_some_scope(self):
        # A kind in neither set is gated everywhere; a kind in both is gated
        # nowhere and would be invisible. Neither is intended.
        self.assertFalse(ncv.CORE_ONLY_KINDS & ncv.UNSWEPT_IN_CORE_KINDS)


class TestEveryGovernedScopeIsClean(unittest.TestCase):
    def test_each_scope_is_at_its_hard_zero(self):
        for addon in ncv.GOVERNED_ADDONS:
            found = ncv.measure(addon=addon)
            self.assertEqual(
                [str(v) for v in found],
                [],
                f"{addon} is above its floor; the gate carries no baseline file, "
                f"so its floor is zero and an entry has to be argued or renamed",
            )


if __name__ == "__main__":
    unittest.main()
