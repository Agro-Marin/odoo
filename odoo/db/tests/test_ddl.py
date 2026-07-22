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
    _ddl_keyword,
    _find_value_markers,
    _inline_ddl_params,
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
            "   alter table t add c int": "ALTER",  # case-folded to UPPER
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
            # _classify_ddl stays a strict bool mirroring "is there a keyword"
            self.assertIs(_classify_ddl(qs), expected is not None, qs)

    def test_schema_changing_set(self):
        # CREATE/ALTER/DROP/DO change shape; COMMENT/GRANT/REVOKE never do.
        self.assertEqual(
            _SCHEMA_CHANGING_DDL, frozenset({"CREATE", "ALTER", "DROP", "DO"})
        )
        for kw in ("CREATE", "ALTER", "DROP", "DO"):
            self.assertIn(kw, _SCHEMA_CHANGING_DDL)
        for kw in ("COMMENT", "GRANT", "REVOKE"):
            self.assertNotIn(kw, _SCHEMA_CHANGING_DDL)


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

        def gate(qs):  # mirrors the fast prefix gate in Cursor.execute()
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
                # leading whitespace that overflows the 64-char gate window:
                # 62 (last that fits 2 keyword chars), 63 (boundary), 64, 80.
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
        # strings are single-quoted and internal quotes doubled
        self.assertEqual(
            _inline_ddl_params("c = %s", ("o'reilly",), None), "c = 'o''reilly'"
        )

    def test_named_dict_params(self):
        self.assertEqual(_inline_ddl_params("a = %(x)s", {"x": "v"}, None), "a = 'v'")

    def test_named_dict_missing_key_raises_valueerror(self):
        # A marker whose key is absent must raise the same clear ValueError the
        # positional path raises on a count mismatch — not a bare KeyError from
        # inside re.sub (no statement context, no marker name).
        with self.assertRaises(ValueError) as cm:
            _inline_ddl_params("DEFAULT %(naem)s", {"name": 1}, None)
        self.assertIn("naem", str(cm.exception))

    def test_named_dict_unused_key_is_lenient(self):
        # Extra/unused keys are ignored, matching psycopg's %(name)s binding and
        # the legacy ``qs % params`` formatting (rejecting them would be a
        # behaviour change, unlike the positional count check).
        self.assertEqual(
            _inline_ddl_params("a = %(x)s", {"x": "v", "unused": 9}, None), "a = 'v'"
        )

    def test_named_dict_missing_with_literal_percent(self):
        # The %%-escape must not be mistaken for a missing-key marker.
        with self.assertRaises(ValueError):
            _inline_ddl_params("'100%%' DEFAULT %(v)s", {}, None)
        self.assertEqual(
            _inline_ddl_params("'100%%' = %(v)s", {"v": 1}, None), "'100%' = 1"
        )

    def test_literal_percent_is_unescaped_around_marker(self):
        # `%%` is a literal percent, not a marker; it must survive as a single
        # `%`, while the real `%s` is replaced.  Naive `qs % params` raises here.
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
        # %% is a literal percent, not a marker
        self.assertEqual(_find_value_markers("LIKE 'a%%s'"), [])
        # the space at index 11 means the second marker starts at 12, not 11
        self.assertEqual(_find_value_markers("x %s y %% z %s"), [2, 12])
        self.assertEqual(_find_value_markers("%%"), [])
        self.assertEqual(_find_value_markers("ends %s"), [5])


if __name__ == "__main__":
    unittest.main()
