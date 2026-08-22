import tomllib
from pathlib import Path

import odoo

from . import _py_scan, _suppression
from .lint_case import LintCase

FLOORS = {
    "sql-injection": 36,
    "gettext-variable": 1,
    "gettext-placeholders": 5,
    # 8 -> 7. base_sql_report._drop_existing_relation raised UserError twice --
    # once for a regular table, once for any other unexpected relkind -- and both
    # sentences carried %r. Generalising the mixin so a model can own a table
    # made the first case legal, and the two raises became one. An exact ratchet
    # fails on the fall as hard as on the rise, so the unit is banked in the
    # change that earned it.
    "gettext-repr": 7,
    "missing-gettext": 23,
    "raise-unlink-override": 1,
    "orm-import": 0,
    # 72 -> 69, and the three are NOT this change's: it adds no suppression
    # anywhere, and the files it touches contain no noqa directive at all.
    # Measured at CI scope (--addons-path=odoo/addons,addons, only test_lint
    # installed) the tree reports 69, so the gate has been red in the falling
    # direction since whichever change paid these down without re-flooring.
    # Recorded rather than attributed, for the same reason test_batch_queries
    # was: the scanner counts findings and not provenance, and guessing an owner
    # would be worse than saying there isn't one.
    "noqa-rationale": 69,
    "onchange-domain": 0,
    # 402 -> 395 on the rebase onto origin/19.0-marin, and the seven are this
    # branch's own. Both parents were measured by running the gate at CI scope
    # (`--addons-path=odoo/addons,addons`, only test_lint installed), which is the
    # only scope these floors are defined at:
    #
    #   origin/19.0-marin   402   (its whole test_lint suite passes; 402 reproduces)
    #   merged              395
    #
    # This branch's committed floor said 409 against origin's 402, so the two
    # parents had each reduced findings the other could not see -- fourteen on
    # origin's side, seven on this one -- over a common base of 416. They are
    # disjoint, so the composition keeps both and lands on 395 rather than on
    # either parent's number. Nothing here removed a query: an exact ratchet fails
    # in the falling direction too, which is why the improvement is banked in the
    # same change that produced it.
    #
    # 400 -> 399, and this unit is not this branch's work: `deb97078d7f`
    # (stock.move's method split and the reservation helpers) removed it and did not
    # re-floor, so `test_batch_queries` was failing in the falling direction from
    # that commit onward. Measured in two clean worktrees, `deb97078d7f` and the
    # commit before this note, with stock, purchase_stock and mrp installed so the
    # scan sees the same surface: both report 399. Re-floored here rather than left
    # red, with the attribution rather than a guess at which loop it was.
    #
    # 402 -> 400, two units, both the replenishment report's.
    # `stock_orderpoint._compute_rules` called `product._get_total_routes()` inside
    # its per-record loop, and each override answered with an unbounded
    # `stock.rule` search whose result does not depend on the product; the batched
    # `_get_total_routes_by_product` searches once for the recordset.
    # `_compute_replenishment_uom_id_placeholder` called
    # `_get_replenishment_multiple_alternative` per record, whose mrp override ran a
    # `_bom_find` and whose purchase_stock override ran `_get_dates_info` for each
    # one; `_get_replenishment_multiple_alternative_map` resolves both in batch.
    # Measured on 300 orderpoints carrying real routes, vendors and BoMs, the whole
    # 16-column list read went 983 queries to 77. Queries removed, not findings
    # hidden: the loops the scanner was pointing at are gone.
    #
    # 403 -> 402. The unit was already gone when this was measured: a clean
    # worktree of HEAD reports 402 against the committed 403, so `test_batch_queries`
    # had been failing in the falling direction for every commit since whichever
    # change removed it. Re-floored here without an attribution, because the
    # scanner records counts and not provenance and guessing one would be worse
    # than saying so.
    #
    # 405 -> 403, two units, neither of them a hoisted query.
    # 405 -> 404 was already standing at HEAD when this was measured: the gateway
    # extraction that landed before it moved the count and did not re-floor, so
    # `test_batch_queries` was failing in the falling direction for every commit
    # since. Measured on a clean worktree of HEAD: 404.
    # 404 -> 403 is `mail.message._discard_followed_documents`, whose
    # `mail.followers.search_fetch()` moved into the named
    # `_filter_records_followed_by_self` so `mail.activity._accessible_ids` could
    # ask the same question rather than spell it a second time. **The query is
    # still run once per model** -- the scanner is syntactic and no longer sees
    # the call inside a `for`. It was never an N+1 to begin with: that loop is
    # over document *models*, of which a message batch has one or two, not over
    # records. A finding removed, not a query.
    #
    # 399 -> 396 is stock.warehouse, and all three are queries that stopped being
    # run: `_update_name_and_code` and `_update_extra_picking_type_sequences` each
    # walked the warehouse's operation types one at a time to rebuild a reference
    # sequence payload that `stock.picking.type._prepare_sequence_vals` already
    # owns, and `_unlink_except_in_use` called the per-record `_check_archivable`
    # once per warehouse after batching the very lookup that feeds it. Measured on
    # a worktree carrying only this change, so the count is this change's alone.
    #
    # 396 -> 395, and the unit is the scanner losing sight of a query rather than
    # a query going away -- said plainly because the opposite reading would be a
    # win this change did not earn. `mrp._update_uom` ran `_read_group` lexically
    # inside a `for model, ... in (...)` loop over mrp.bom, mrp.bom.line and
    # mrp.production, which is what E8507 matches. The loop body is now a call to
    # the shared `product.product._restamp_uom`, so the three read_groups still
    # happen -- they are three different models and cannot be one query -- but no
    # query sits inside a loop for the scanner to see. Diffed finding-by-finding
    # between two worktrees at the same commit: one removal,
    # `addons/mrp/models/product.py:787`, and no additions; the three other moved
    # lines are the same findings shifted by edits above them.
    "n-plus-one-query": 394,
    "gettext-developer-error": 52,
    "config-chainmap-patch": 0,
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
    "gettext-developer-error": (
        "drop the `_()` and use an f-string: a builtin exception reaches a reader "
        "as a traceback, and translating it books a developer diagnostic into the "
        "module catalogue"
    ),
    "config-chainmap-patch": (
        "use config.patch(**values); patch.dict on the options ChainMap "
        "flattens every lower layer into _override_options and the damage "
        "lands on the next test"
    ),
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

    def test_gettext_on_a_developer_error(self):
        self._assert_ratchet("gettext-developer-error")

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

    def test_config_chainmap_patch(self):
        self._assert_ratchet("config-chainmap-patch")

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
        sample = [
            (source.path, source.in_module)
            for source in _py_scan.corpus()
            if source.path.endswith(".py")
        ][:400]
        self.assertTrue(sample, "no files to compare the two scans on")

        serial = sorted(_py_scan.scan_many(sample))
        parallel = sorted(_py_scan._run_parallel(sample, 4))
        self.assertEqual(parallel, serial)

    def test_every_rule_code_is_declared_external_to_ruff(self):
        ruff_toml = Path(odoo.__path__[0]).parent / "ruff.toml"
        declared = set(tomllib.loads(ruff_toml.read_text())["lint"]["external"])
        codes = {
            alias
            for aliases in _suppression.RULE_ALIASES.values()
            for alias in aliases
            if alias.startswith("E85")
        }
        self.assertEqual(
            sorted(codes - declared),
            [],
            f"these checker codes are not in {ruff_toml.name}'s lint.external, "
            "so ruff reports RUF102 on any noqa that uses them",
        )

    def test_every_rule_has_a_suppression_alias(self):
        self.assertEqual(
            sorted(
                _py_scan.RULES - set(_suppression.RULE_ALIASES) - {"noqa-rationale"}
            ),
            [],
            "these rules have no entry in RULE_ALIASES, so they carry no short "
            "code and cannot be named in a `# noqa:`",
        )

    def test_the_corpus_is_not_empty(self):
        corpus = _py_scan.corpus()
        self.assertGreater(len(corpus), 5000, "the corpus scan reached almost nothing")
        self.assertTrue(
            any(not source.in_module for source in corpus),
            "the framework (odoo/orm, odoo/tools, ...) is missing from the "
            "corpus again -- it is where hand-built SQL actually lives",
        )
