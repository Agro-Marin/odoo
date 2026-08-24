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
    # Three below the committed 69, on an archive of HEAD. Whoever earned those
    # three did not re-floor, so the gate has been failing in the falling
    # direction since. Recorded rather than attributed, the way ruff.json's
    # ninety were.
    #
    "noqa-rationale": 66,
    "onchange-domain": 0,
    # 394 -> 392. The gate has been red in the *falling* direction since
    # 392 -> 384 and 69 -> 66 on the linear replay onto origin/19.0-marin. Neither
    # is a query removed or a rationale written: both floors were replayed from this
    # branch, measured before origin's 23 commits were under them, so they describe a
    # tree that no longer exists. Measured on the replayed tree with test_lint
    # installed at CI scope, the only scope these floors are defined at. An exact
    # ratchet fails in the falling direction too, so the improvement is banked in the
    # same change that produced it rather than left red.
    # 5bed3c22f90 committed 394 against a tree that measures 392 -- the same
    # mis-floor 0e393e4955f had just corrected for `computectx`. Measured in
    # two worktrees, 5bed3c22f90's tree and this one, whose offender lists are
    # identical line for line: no commit since is the -2, it was already stale
    # when it was written.
    # 392 -> 389. ALL THREE ARE EARNED, ALL THREE IN gamification.
    #
    # Attributed by DELTA, not by an absolute reading: the shared checkout is
    # carrying another session's uncommitted digest/loyalty work, which moves
    # this count by -8 under any whole-tree measurement and is not this change's
    # to floor. `addons/gamification` was swapped between HEAD and this change
    # in the same checkout, seconds apart, and only its own findings counted:
    # 18 at HEAD, 15 here. 392 - 3 = 389 is what a clean tree measures; the
    # whole-tree reading here is 381, which is 389 with that -8 on top.
    #
    #   gamification_team._compute_team_stats   a search_count per team, run on
    #       every karma change of every member because the field was stored and
    #       depended on `member_ids.karma`. Now two _read_groups for the whole
    #       recordset, and the fields are not stored at all, so an ordinary
    #       kudos stops touching the team table.
    #   res_users._rank_changed                 a badge search per user. Now one
    #       search and one create over the batch the caller already had.
    #   gamification_goal.update_goal           a search_count per goal even
    #       when the definition's domain never mentions `user`. Goals are
    #       grouped by their evaluated domain now, so goals that must get the
    #       same answer share the query that produces it: measured 1.9 -> 1.0
    #       queries per goal over 15 goals of one count-mode definition.
    #
    # The same domain-grouping shape went into `_check_achievement_for_users`
    # and the streak checker; neither moves this count, because the scanner sees
    # a call inside a loop either way -- what changed is how many distinct loops
    # run. The streak one is the larger win regardless: its daily cron went from
    # 4.2 to 0.20 queries per additional streak, measured at 5 and at 25.
    # 52 -> 51, and the whole of the -1 is `digest`'s `/set_periodicity` route,
    # which answered a periodicity outside the selection with
    # `raise ValueError(_("Invalid periodicity set on digest"))` -- a 500 out of
    # a translated developer string. It raises `NotFound` now.
    #
    # 389 -> 381 and 69 -> 66, re-measured after this change was replayed onto
    # origin/19.0-marin. Two re-floorings composed here: the linear replay had
    # already banked 392 -> 384 and 69 -> 66 against a tree this change had not
    # landed on, and neither parent's number describes the result. Measured on
    # the composed tree at CI scope, test_lint installed: 381 and 66. The -3 on
    # top of 384 is this change's own, from the crons that stopped asking per
    # record.
    # 381 -> 378. ALL THREE ARE EARNED, ALL THREE IN gamification, and they are
    # the follow-up to the three above -- same attribution method, same addon,
    # measured the same way: 15 findings there at 250683d676f, 12 now.
    #
    #   challenge.report_progress          a personal-mode report ran
    #       `_get_serialized_challenge_lines` per recipient, each with its own
    #       search_fetch. The goals come out once for the whole audience and are
    #       sliced per user now; the render and the notification stay per user
    #       because each is in that user's language and to their partner alone.
    #       Marginal cost 16.2 -> 10.7 queries per participant, measured at 5
    #       and 20 recipients. What is left is the mail, which no grouping
    #       removes.
    #   badge._compute_owner_stats         two SQL passes over
    #       gamification_badge_user carrying the same @api.depends, so they
    #       always recomputed together and always cost two round-trips to answer
    #       one question about one table. One pass with FILTER clauses now: all
    #       seven statistics on a badge read in 1 query.
    #   res_users._recompute_rank          the second implementation this
    #       dispatched to, `_recompute_rank_bulk`, is deleted. It ran three
    #       searches per rank to derive what the grouped path already holds in
    #       memory, and it skipped `_rank_changed` for users dropping below the
    #       lowest rank, so the two did not agree on behaviour either. Measured
    #       on 60 users with every rank changing: 385 queries against its 429.
    # 378 -> 373, and 378 was never a reading of any tree. It was DERIVED during
    # the conflict resolution that realigned this branch onto origin/19.0-marin:
    # origin had already banked its own -3 into 381, the gamification second
    # round above is a further -3, and 381 - 3 was written down rather than
    # measured. The ten commits this branch replays compose further savings that
    # arithmetic on one commit's delta cannot see.
    #
    # 373 is the first MEASURED reading of the realigned branch, taken per §9.5
    # at the only scope these floors are defined at -- `-i test_lint` alone, the
    # install `.github/workflows/test_lint.yml` builds -- and against a `git
    # archive` of HEAD, because the shared working tree is carrying another
    # session's uncommitted digest/loyalty work and cannot be counted in.
    #
    # The remaining savings are NOT attributed unit by unit here. They are the
    # composition of the digest, loyalty, link_tracker and rating commits this
    # branch replays, each of which measured its own delta against a base that
    # the realignment then moved. Recorded rather than attributed, the way
    # ruff.json's ninety were.
    #
    # 373 -> 369 on the SECOND rebase onto origin/19.0-marin (2026-08-24), which
    # brought 125 further commits under this branch. Both trees were measured the
    # same way -- `-i test_lint --test-tags /test_lint` against a `git archive`,
    # never the shared working tree -- so the two readings are comparable:
    #
    #   origin/19.0-marin alone       377   (its own committed floor says 381,
    #                                        so that gate is red in the falling
    #                                        direction at origin, by 4)
    #   this branch on top of it      369
    #
    # The -8 is this branch's. The 4 origin is carrying is inherited, not earned
    # here, and 369 pays it off in the same number rather than leaving a floor
    # nobody's tree matches. An exact ratchet fails in the falling direction too.
    "n-plus-one-query": 369,
    # 52 -> 49, measured in the same run and the same scope as the floor above.
    # `digest`'s /set_periodicity route is one of the three -- it answered a
    # periodicity outside the selection with `raise ValueError(_("Invalid
    # periodicity set on digest"))`, a 500 out of a translated developer string,
    # and raises `NotFound` now. The other two are not attributed; they come
    # from the same replayed set, and 52 is origin's number for a tree these
    # commits had not landed on.
    "gettext-developer-error": 49,
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
