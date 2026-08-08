from . import _py_scan
from .lint_case import LintCase

FLOORS = {
    # 43 -> 44: `env.cr` and `self._cr` joined CURSOR_EXPRESSIONS. The one
    # call they brought into scope, odoo/tools/translate.py, builds
    # identifiers from a .po file -- but only after checking each against
    # `_fields`, so it is safe and wants an inline suppression saying why.
    "sql-injection": 44,
    # The one site is `_description_falsy_value_label`, whose literal lives in
    # the field declaration where the extractor already finds it -- safe, and
    # wants an inline suppression saying so.
    "gettext-variable": 1,
    # Five messages with two bare %s, which a translator cannot reorder.
    "gettext-placeholders": 5,
    # Eight messages rendering Python repr syntax into a sentence a user
    # reads. Replace each %r with a quoted %s.
    "gettext-repr": 8,
    # 20 -> 23: a raw string literal concatenated onto a translated one is
    # itself untranslated, and the BinOp whitelist used to accept the pair on
    # the strength of either half.
    "missing-gettext": 23,
    # `stock.location.unlink` rewrites the recordset it delegates to, which an
    # @api.ondelete hook cannot do; uninstall was tested and still succeeds,
    # so it wants an inline suppression carrying that evidence.
    "raise-unlink-override": 1,
    "orm-import": 0,
    # The rule reads `tokenize` comments now, so a directive spelled inside a
    # string literal is no longer one. That is also what retired `_NOQA_SELF`,
    # the five-file blanket that hid exactly those three fixtures. 79 was never
    # right: the tree held 80 the day the floor was written, which is why this
    # gate had not been green since.
    "noqa-rationale": 80,
    "onchange-domain": 0,
    # 417 -> 430. Two corrections, both measured:
    #   * a later commit fixed one N+1 in `base_import` without lowering the
    #     floor, which is the "debt went down" case working as designed (-1);
    #   * `<anything>.env[...]` is a recordset, so the 14 sites shaped
    #     `for rec in recs: rec.env['model'].search(...)` are reported again.
    #     The receiver test demanded a `self` root and silently dropped the most
    #     idiomatic N+1 there is.
    "n-plus-one-query": 430,
}


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


class TestPythonLint(LintCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _py_scan.findings()

    def _assert_ratchet(self, rule):
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
        self._assert_ratchet("sql-injection")

    def test_gettext_variable(self):
        self._assert_ratchet("gettext-variable")

    def test_gettext_placeholders(self):
        self._assert_ratchet("gettext-placeholders")

    def test_gettext_repr(self):
        self._assert_ratchet("gettext-repr")

    def test_missing_gettext(self):
        self._assert_ratchet("missing-gettext")

    def test_unlink_override(self):
        self._assert_ratchet("raise-unlink-override")

    def test_orm_import(self):
        self._assert_ratchet("orm-import")

    def test_onchange_domains(self):
        self._assert_ratchet("onchange-domain")

    def test_noqa_rationale(self):
        self._assert_ratchet("noqa-rationale")

    def test_batch_queries(self):
        self._assert_ratchet("n-plus-one-query")

    def test_every_rule_has_a_floor(self):
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
        self.assertEqual(
            sorted(_py_scan.RULES - FLOORS.keys()),
            [],
            "these rules exist but have no committed floor, so nothing holds "
            "them at zero",
        )

    def test_the_scan_leaves_no_child_process_behind(self):
        # `multiprocessing` keeps a resource_tracker and a forkserver resident
        # for the life of the interpreter. `BaseCase`'s class cleanup treats a
        # surviving child as a leak, terminates it and waits ten seconds --
        # and neither helper dies on SIGTERM, so every later test class paid
        # the full ten. The scan saved 11 seconds and cost the suite 160.
        import psutil

        _py_scan.findings()
        _py_scan._run_parallel([], 2)
        self.assertEqual(
            [f"{child.pid} {child.name()}" for child in psutil.Process().children()],
            [],
            "a worker pool must reap its own helpers, or every test class "
            "after this one waits ten seconds for them",
        )

    def test_the_parallel_scan_agrees_with_the_serial_one(self):
        # `findings()` fans the corpus out over worker processes. That is only
        # ever an optimisation, so the answer has to be identical to the
        # in-process scan -- and it has to stay identical when a checker is
        # added, which is what comparing the whole finding set buys over
        # comparing counts.
        sample = [
            (source.path, source.in_module)
            for source in _py_scan.corpus()
            if source.path.endswith(".py")
        ][:400]
        self.assertTrue(sample, "no files to compare the two scans on")

        serial = sorted(_py_scan.scan_many(sample))
        parallel = sorted(_py_scan._run_parallel(sample, 4))
        self.assertEqual(parallel, serial)

    def test_the_corpus_is_not_empty(self):
        corpus = _py_scan.corpus()
        self.assertGreater(len(corpus), 5000, "the corpus scan reached almost nothing")
        self.assertTrue(
            any(not source.in_module for source in corpus),
            "the framework (odoo/orm, odoo/tools, ...) is missing from the "
            "corpus again -- it is where hand-built SQL actually lives",
        )
