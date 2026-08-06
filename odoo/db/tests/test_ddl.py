"""Tier-1 (database-free) tests for :mod:`odoo.db.ddl`.

DDL detection and client-side parameter inlining are pure string functions —
and the security-sensitive core of the cursor layer (a splice bug here is a
SQL-injection or wrong-statement bug).  They are tested at the lowest tier
that can express them (coding_guidelines §6): plain pytest, no database, no
framework import.  ``psycopg.sql.quote`` runs with a null adapter context.

Moved from ``odoo/addons/base/tests/test_db_cursor.py`` so a regression fails
in milliseconds instead of requiring a live database with ``base`` installed.
"""

import unittest

from odoo.db.ddl import (
    _SCHEMA_CHANGING_DDL,
    _changes_schema,
    _ddl_keyword,
    _find_value_markers,
    _inline_ddl_params,
    _is_rollback_to_savepoint,
)


def _classify_ddl(qs):
    """Test predicate: ``True`` when *qs* begins with a DDL keyword.

    Production keys off :func:`_ddl_keyword`'s keyword identity directly; these
    tests pin the underlying gate's yes/no behaviour.
    """
    return _ddl_keyword(qs) is not None


class TestClassifyDdl(unittest.TestCase):
    """Direct unit tests for the pure ``_classify_ddl`` gate extracted from
    ``Cursor.execute``.  The gate is a fast 2-char prefix filter over a 64-char
    window in front of the authoritative ``_RE_DDL`` regex; its only job is to
    never *disagree* with the regex while skipping it on the hot path.  These
    run without a connection (the function is pure).
    """

    def test_keywords_detected(self):
        for kw in ("CREATE", "ALTER", "DROP", "COMMENT", "GRANT", "REVOKE", "DO"):
            self.assertTrue(_classify_ddl(f"{kw} something"), kw)

    def test_dml_not_detected(self):
        for kw in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "TRUNCATE", "SET"):
            self.assertFalse(_classify_ddl(f"{kw} something"), kw)

    def test_leading_whitespace_and_comments(self):
        self.assertTrue(_classify_ddl("\n   CREATE TABLE t (id int)"))
        self.assertTrue(_classify_ddl("-- migrate\nCREATE TABLE t (id int)"))
        self.assertTrue(_classify_ddl("/* c */ ALTER TABLE t ADD COLUMN b int"))
        self.assertFalse(_classify_ddl("   SELECT 1"))

    def test_window_boundary_matches_regex(self):
        """The 63/64-char window fallback must never disagree with the regex.

        Sweep every indentation length across the window boundary (and past it)
        for each keyword + a DML control; the fast gate and a bare ``_RE_DDL``
        match must agree on every one — otherwise deeply-indented DDL slips past
        the gate (params not inlined, prepared cache not invalidated).
        """
        from odoo.db.ddl import _RE_DDL

        keywords = ("CREATE", "ALTER", "DROP", "COMMENT", "GRANT", "DO", "SELECT")
        tails = (" TABLE t (id int)", " 1", " * FROM t", "")
        for pad in range(96):
            for kw in keywords:
                for tail in tails:
                    qs = " " * pad + kw + tail
                    self.assertEqual(
                        _classify_ddl(qs),
                        _RE_DDL.match(qs) is not None,
                        f"gate/regex disagree at pad={pad} kw={kw!r} tail={tail!r}",
                    )


class TestDdlKeyword(unittest.TestCase):
    """``_ddl_keyword`` reports the leading DDL keyword (UPPERCASE) so
    ``Cursor.execute`` can tell schema-changing DDL (invalidate caches) from
    DDL that only needs client-side param inlining.  ``_classify_ddl`` is now a
    thin bool wrapper over it.  Pure — runs without a connection.
    """

    def test_keyword_extraction(self):
        cases = {
            "CREATE TABLE t (x int)": "CREATE",
            "   alter table t add c int": "ALTER",
            "DROP TABLE t": "DROP",
            "COMMENT ON TABLE t IS %s": "COMMENT",
            "GRANT SELECT ON t TO r": "GRANT",
            "REVOKE SELECT ON t FROM r": "REVOKE",
            "DO $$ BEGIN END $$": "DO",
            "-- migrate\nCREATE TABLE t (x int)": "CREATE",
            "SELECT 1": None,
            "WITH a AS (SELECT 1) SELECT * FROM a": None,
        }
        for qs, expected in cases.items():
            self.assertEqual(_ddl_keyword(qs), expected, qs)
            self.assertIs(_classify_ddl(qs), expected is not None, qs)

    def test_schema_changing_set(self):
        self.assertEqual(
            _SCHEMA_CHANGING_DDL, frozenset({"CREATE", "ALTER", "DROP", "DO"})
        )
        for kw in ("CREATE", "ALTER", "DROP", "DO"):
            self.assertIn(kw, _SCHEMA_CHANGING_DDL)
        for kw in ("COMMENT", "GRANT", "REVOKE"):
            self.assertNotIn(kw, _SCHEMA_CHANGING_DDL)


class TestRollbackToSavepointDetection(unittest.TestCase):
    """``_is_rollback_to_savepoint`` re-arms the catalog-cache hook for raw SQL
    savepoint rollbacks that bypass ``cr.savepoint()``."""

    def test_rollback_to_savepoint_is_detected(self):
        for qs in (
            "ROLLBACK TO SAVEPOINT foo",
            'ROLLBACK TO SAVEPOINT "foo"',
            "ROLLBACK TO foo",  # SAVEPOINT keyword is optional in PostgreSQL
            "rollback to savepoint foo",
            "  \n ROLLBACK   TO   SAVEPOINT bar",
            "/* c */ ROLLBACK TO SAVEPOINT baz",
        ):
            self.assertTrue(_is_rollback_to_savepoint(qs), qs)

    def test_non_partial_rollbacks_are_not_detected(self):
        for qs in (
            "ROLLBACK",  # ends the whole transaction — handled elsewhere
            "ROLLBACK;",
            "ROLLBACK WORK",
            "RELEASE SAVEPOINT foo",  # merges, undoes nothing
            "SAVEPOINT foo",
            "SELECT 1",
            "UPDATE t SET x = 1",
            "-- ROLLBACK TO SAVEPOINT foo\nSELECT 1",  # commented out
        ):
            self.assertFalse(_is_rollback_to_savepoint(qs), qs)

    def test_prefix_gate_short_circuits_non_ro_queries(self):
        # A deeply indented statement still gets classified (no false negative).
        self.assertTrue(_is_rollback_to_savepoint(" " * 40 + "ROLLBACK TO SAVEPOINT x"))
        self.assertFalse(_is_rollback_to_savepoint(" " * 40 + "SELECT 1"))


class TestDDLKeywordPrefixGate(unittest.TestCase):
    """The 2-char prefix gate (``_DDL_PREFIXES``) and the detection regex
    (``_RE_DDL``) are both *computed* from ``_DDL_KEYWORDS`` at import.  This
    pins that derivation so they can never disagree on whether a statement is
    DDL — the guarantee the source comment in ddl.py relies on.  (A drift would
    silently skip client-side param inlining and prep-cache invalidation.)
    """

    def test_prefixes_are_derived_from_keywords(self):
        from odoo.db.ddl import _COMMENT_PREFIXES, _DDL_KEYWORDS, _DDL_PREFIXES

        expected = frozenset(kw[:2] for kw in _DDL_KEYWORDS) | _COMMENT_PREFIXES
        self.assertEqual(_DDL_PREFIXES, expected)

    def test_every_keyword_prefix_admitted_by_gate(self):
        from odoo.db.ddl import _DDL_KEYWORDS, _DDL_PREFIXES

        for kw in _DDL_KEYWORDS:
            self.assertIn(
                kw[:2].upper(),
                _DDL_PREFIXES,
                f"keyword {kw!r}'s 2-char prefix is not admitted by the gate",
            )

    def test_gate_and_regex_never_disagree(self):
        from odoo.db.ddl import _DDL_KEYWORDS, _DDL_PREFIXES, _RE_DDL

        def gate(qs):
            head = qs[:64].lstrip()
            if len(head) < 2 and len(qs) > 64:
                head = qs.lstrip()
            c = head[:2].upper()
            return c in _DDL_PREFIXES and _RE_DDL.match(qs) is not None

        def regex(qs):
            return _RE_DDL.match(qs) is not None

        samples = []
        for kw in _DDL_KEYWORDS:
            samples += [
                f"{kw} TABLE x (c int)",
                f"  {kw} foo",
                f"\n\n\t{kw} foo",
                f"-- lead\n{kw} foo",
                f"/* lead */ {kw} foo",
                kw.lower() + " foo",
                " " * 62 + f"{kw} foo",
                " " * 63 + f"{kw} foo",
                " " * 64 + f"{kw} foo",
                " " * 80 + f"{kw} foo",
            ]
        samples += [
            "SELECT 1",
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t",
            "WITH a AS (SELECT 1) SELECT * FROM a",
        ]
        for s in samples:
            self.assertEqual(
                gate(s),
                regex(s),
                f"prefix gate and regex disagree on {s!r} — derivation drifted",
            )


class TestInlineDdlParams(unittest.TestCase):
    """_inline_ddl_params splices params into DDL as client-side quoted
    literals (DDL rejects server-side $N parameters).  Extracted from
    Cursor.execute() so the %%-escape-aware splice — the trickiest bit of
    the cursor — is unit-testable without a DDL round-trip.  ``quote`` runs
    with a null adapter context, so these need no database connection.
    """

    def test_positional_inlines_and_quotes(self):
        self.assertEqual(_inline_ddl_params("DEFAULT %s", (7,), None), "DEFAULT 7")
        self.assertEqual(
            _inline_ddl_params("c = %s", ("o'reilly",), None), "c = 'o''reilly'"
        )

    def test_named_dict_params(self):
        self.assertEqual(_inline_ddl_params("a = %(x)s", {"x": "v"}, None), "a = 'v'")

    def test_named_dict_missing_key_raises_valueerror(self):
        with self.assertRaises(ValueError) as cm:
            _inline_ddl_params("DEFAULT %(naem)s", {"name": 1}, None)
        self.assertIn("naem", str(cm.exception))

    def test_named_dict_unused_key_is_lenient(self):
        self.assertEqual(
            _inline_ddl_params("a = %(x)s", {"x": "v", "unused": 9}, None), "a = 'v'"
        )

    def test_named_dict_missing_with_literal_percent(self):
        with self.assertRaises(ValueError):
            _inline_ddl_params("'100%%' DEFAULT %(v)s", {}, None)
        self.assertEqual(
            _inline_ddl_params("'100%%' = %(v)s", {"v": 1}, None), "'100%' = 1"
        )

    def test_literal_percent_is_unescaped_around_marker(self):
        self.assertEqual(
            _inline_ddl_params("IS '50%% done' DEFAULT %s", ("v",), None),
            "IS '50% done' DEFAULT 'v'",
        )

    def test_double_percent_only_no_marker(self):
        self.assertEqual(
            _inline_ddl_params("COMMENT IS '100%% sure'", (), None),
            "COMMENT IS '100% sure'",
        )

    def test_marker_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _inline_ddl_params("%s %s", ("only-one",), None)
        with self.assertRaises(ValueError):
            _inline_ddl_params("DEFAULT %s", (1, 2), None)

    def test_multiple_positional_in_order(self):
        self.assertEqual(
            _inline_ddl_params("(%s, %s, %s)", (1, 2, 3), None), "(1, 2, 3)"
        )


class TestFindValueMarkers(unittest.TestCase):
    """_find_value_markers locates real ``%s`` placeholders and skips ``%%``
    escapes — the escape-aware scan that execute_values and _inline_ddl_params
    both rely on.  A naive str.count/replace would mis-handle ``%%s``.
    """

    def test_basic_and_escapes(self):
        self.assertEqual(_find_value_markers("%s and %s"), [0, 7])
        self.assertEqual(_find_value_markers("LIKE 'a%%s'"), [])
        self.assertEqual(_find_value_markers("x %s y %% z %s"), [2, 12])
        self.assertEqual(_find_value_markers("%%"), [])
        self.assertEqual(_find_value_markers("ends %s"), [5])


class TestChangesSchema(unittest.TestCase):
    """Cache invalidation must look past the LEADING statement.

    ``Cursor.execute`` keys the prepared-statement / catalog-cache drop on this,
    not on ``_ddl_keyword`` alone: a multi-statement string can hide its ALTER
    behind a harmless first statement, and the next ``SELECT *`` on a cached
    plan then raises FeatureNotSupported (0A000, not retryable -> HTTP 500).
    """

    def _check(self, qs):
        return _changes_schema(qs, _ddl_keyword(qs))

    def test_single_statement_schema_ddl(self):
        for qs in (
            "CREATE TABLE t (id int)",
            "ALTER TABLE t ADD COLUMN c int",
            "DROP TABLE t",
            "DO $$ BEGIN END $$",
            "  -- note\n  ALTER TABLE t ALTER COLUMN c TYPE text",
        ):
            with self.subTest(qs=qs):
                self.assertTrue(self._check(qs))

    def test_single_statement_non_schema_ddl_and_dml(self):
        for qs in (
            "SELECT 1",
            "UPDATE t SET a = 1",
            "COMMENT ON TABLE t IS 'x'",
            "GRANT SELECT ON t TO PUBLIC",
            "REVOKE ALL ON t FROM PUBLIC",
            "TRUNCATE TABLE t",
        ):
            with self.subTest(qs=qs):
                self.assertFalse(self._check(qs))

    def test_ddl_hidden_behind_a_leading_non_ddl_statement(self):
        """The reproduced defect: BEGIN hides the ALTER from a leading-keyword
        test, so the caches were never dropped."""
        for qs in (
            "BEGIN; ALTER TABLE t ADD COLUMN c int; COMMIT",
            "SET LOCAL lock_timeout = '5s'; DROP TABLE t",
            "SELECT 1; CREATE INDEX i ON t (id)",
            "UPDATE t SET a = 1;\n  ALTER TABLE t DROP COLUMN b",
        ):
            with self.subTest(qs=qs):
                self.assertTrue(self._check(qs), qs)

    def test_multi_statement_without_schema_ddl_stays_false(self):
        for qs in (
            "SELECT 1; SELECT 2",
            "BEGIN; UPDATE t SET a = 1; COMMIT",
            "SET x = 1; COMMENT ON TABLE t IS 'y'",
        ):
            with self.subTest(qs=qs):
                self.assertFalse(self._check(qs))

    def test_leading_schema_ddl_short_circuits_before_any_scan(self):
        qs = "CREATE TABLE t (id int); COMMENT ON TABLE t IS 'x'"
        self.assertTrue(_changes_schema(qs, "CREATE"))

    def test_over_reports_rather_than_misses(self):
        """A semicolon inside a literal can produce a false positive; that costs
        one needless cache drop.  The reverse (missing a real DDL boundary) is
        what corrupts, and cannot happen: every boundary IS a semicolon."""
        self.assertTrue(self._check("SELECT 'a; DROP TABLE t'"))

    def test_no_semicolon_never_pays_for_a_split(self):
        self.assertFalse(_changes_schema("SELECT " + "x" * 10_000, None))


if __name__ == "__main__":
    unittest.main()
