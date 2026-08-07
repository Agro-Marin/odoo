"""Python lint gates, all driven by one shared parse of the corpus.

Replaces ``test_ruff`` (which ran no ruff), ``test_onchange_domains``,
``test_orm_import`` and ``test_noqa_rationale``. Those four re-read and
re-parsed the same tree between them; the scan behind this module does it once.
See :mod:`_py_scan` for the measurements and :mod:`_suppression` for what
``# noqa`` means to all of them.

Standard lint rules are ruff's job (``ruff.toml``, ratcheted in CI). What lives
here is the set of Odoo-specific rules no general linter knows about.

The same division settles JavaScript: ESLint owns it, as a blocking ratchet in
CI (``.github/workflows/lint.yml`` against ``tooling/ratchet/baselines/``), so
this module carries no JS gate of its own.

**Every rule is a ratchet, and that is the point.** The suite this replaces
failed 3 562 times on a clean checkout -- most of it against sibling checkouts
the fork must not edit, but 1 585 findings in its own code too. A gate that is
red on arrival is a gate nobody reads, and two of the old tests had already
given up and downgraded themselves to ``_logger.warning`` (one of them
referencing a ``_BATCH_FAIL_MODULES`` constant that was never written). Freezing
today's counts makes the suite green, so that tomorrow's regression is the only
thing in it -- and the exact-match check means a fix cannot be quietly undone,
because lowering the count without committing the new floor fails too. Same
mechanism as ``tooling/ratchet`` and ``SINGLE_BUNDLE_GAP_FLOOR``.
"""

from . import _py_scan
from .lint_case import LintCase

#: Findings currently present in the code this fork owns (addons + framework).
#: Exact match: raising one of these is a regression, lowering one is progress
#: that must be committed here in the same change.
#:
#: Measured 2026-08-07 on a base+test_lint install. The corpus is install
#: independent -- it is read off the addons path, not out of the registry -- so
#: these numbers do not move with what happens to be installed.
FLOORS = {
    "sql-injection": 43,
    "gettext-variable": 1,
    "gettext-placeholders": 5,
    "gettext-repr": 8,
    "missing-gettext": 20,
    "raise-unlink-override": 1,
    "orm-import": 0,
    "onchange-domain": 0,
    "noqa-rationale": 79,
    "n-plus-one-query": 417,
}

#: ``sql-injection`` was 15 and is 43. Nothing regressed: the checker stopped
#: exempting every ``_``-prefixed function, which in a codebase where that is
#: the convention for *all* model methods had been hiding 1 366 of 2 703 query
#: construction sites -- and it stopped recursing forever on a value built by
#: accumulating onto itself (``where_clause = "…" % (where_clause, …)``), which
#: had been dropping a whole file from the scan with a warning.
#:
#: ``n-plus-one-query`` went 418 -> 417 and the gettext rules did not move: the
#: three private definitions of "is this a test file" became one, which for
#: those rules is the scope the gettext checker already had.
#:
#: ``gettext-placeholders`` went 4 -> 5 because the placeholder regex now uses
#: the conversion types Python's ``%`` operator actually has. It was missing
#: ``i``, ``u`` and ``a``, so ``l10n_ar``'s ``_('No VAT configured for partner
#: [%i] %s', …)`` -- two unnamed placeholders, the precise thing this rule is
#: for -- had never been counted.


_ADVICE = {
    "sql-injection": (
        "Build the query with `SQL()` so the value is passed as a parameter, or "
        "add `# noqa: E8501  <why this one is safe>`"
    ),
    "gettext-variable": "_() takes a literal; a variable cannot be extracted into the .pot",
    "gettext-placeholders": (
        "use %(name)s rather than a second bare %s, so a translator can reorder them"
    ),
    "gettext-repr": "%r leaks Python syntax into a user-facing sentence",
    "missing-gettext": "wrap the message in _() so it can be translated",
    "raise-unlink-override": (
        "use @api.ondelete(at_uninstall=False): raising in unlink also blocks "
        "uninstalling the module"
    ),
    "orm-import": "reach the ORM through odoo.api / odoo.fields / odoo.models",
    "onchange-domain": (
        "put the domain on the field, so every reader of it agrees rather than "
        "just this one form view"
    ),
    "noqa-rationale": (
        "write the reason after the codes: `# noqa: F401  re-exported by __init__`"
    ),
    "n-plus-one-query": "hoist the query out of the loop and index the result in memory",
}


# `LintCase` already carries `@no_retry`.
class TestPythonLint(LintCase):
    """Odoo-specific AST rules, checked against the code this fork owns."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Warm the shared scan here rather than in whichever test happens to run
        # first, so its cost is attributed to the class.
        _py_scan.findings()

    def _assert_ratchet(self, rule):
        # One implementation of the ratchet, on `LintCase`. There were two, with
        # different wording and different truncation, and a gate that reports its
        # debt differently depending on which one it inherited is a gate people
        # learn to read selectively.
        self.assert_ratchet(
            sorted(
                _py_scan.findings().get(rule, []),
                key=lambda f: (f.path, f.lineno),
            ),
            FLOORS[rule],
            f"{rule} finding(s)",
            f"{_ADVICE[rule]}.",
        )

    def test_sql_injection(self):
        """No query may be built from a value that is not a compile-time constant."""
        self._assert_ratchet("sql-injection")

    def test_gettext_variable(self):
        """``_()`` takes a literal: a variable cannot be extracted into the .pot."""
        self._assert_ratchet("gettext-variable")

    def test_gettext_placeholders(self):
        """Two bare ``%s`` cannot be reordered by a translator."""
        self._assert_ratchet("gettext-placeholders")

    def test_gettext_repr(self):
        """``%r`` leaks Python syntax into a user-facing sentence."""
        self._assert_ratchet("gettext-repr")

    def test_missing_gettext(self):
        """A user-facing error message has to be translatable."""
        self._assert_ratchet("missing-gettext")

    def test_unlink_override(self):
        """Raising in ``unlink`` also blocks uninstall."""
        self._assert_ratchet("raise-unlink-override")

    def test_orm_import(self):
        """Addon code reaches the ORM through the public facade."""
        self._assert_ratchet("orm-import")

    def test_onchange_domains(self):
        """A domain returned from an onchange binds only that one form view."""
        self._assert_ratchet("onchange-domain")

    def test_noqa_rationale(self):
        """Every ``# noqa`` should say why the rule was waived.

        A suppression without a reason is unreviewable: nobody can tell later
        whether it is still needed.
        """
        self._assert_ratchet("noqa-rationale")

    def test_batch_queries(self):
        """A query inside a ``for`` is an N+1; hoist it and index in memory."""
        self._assert_ratchet("n-plus-one-query")

    def test_every_rule_has_a_floor(self):
        """A rule the scan reports but ``FLOORS`` does not name would go unchecked.

        The scan is the source of truth for which rules exist, so adding a
        checker without a floor must fail here rather than silently report
        nothing.
        """
        self.assertEqual(
            sorted(_py_scan.findings().keys() - FLOORS.keys()),
            [],
            "these rules produce findings but have no committed floor",
        )
        self.assertEqual(
            sorted(FLOORS.keys() - _py_scan.RULES),
            [],
            "these floors name a rule no checker produces",
        )
        # The direction that was missing. The two checks above compare the
        # floors against the rules that *fired* and against `RULES`; neither
        # notices a rule declared in `RULES` with no floor, because a rule with
        # no findings never reaches `findings()`. A new checker that happens to
        # be clean on the day it lands would therefore go in ungated, and only
        # start being enforced once it broke something.
        self.assertEqual(
            sorted(_py_scan.RULES - FLOORS.keys()),
            [],
            "these rules exist but have no committed floor, so nothing holds "
            "them at zero",
        )

    def test_the_corpus_is_not_empty(self):
        """A scan that reached nothing would pass every rule above."""
        corpus = _py_scan.corpus()
        self.assertGreater(len(corpus), 5000, "the corpus scan reached almost nothing")
        self.assertTrue(
            any(not source.in_module for source in corpus),
            "the framework (odoo/orm, odoo/tools, ...) is missing from the "
            "corpus again -- it is where hand-built SQL actually lives",
        )
