"""Tests for the server-side feature-flag surface.

``IrHttp._resolve_feature_flags`` reads ``ir.config_parameter`` rows
whose key starts with ``web.feature.`` and exposes them under
``session_info["feature_flags"]``.  The JS resolver in
``services/feature_flags.js`` then consumes the dict as the
"server" layer of its four-step cascade
(URL > localStorage > server > default).

These tests pin:
  1. The prefix selection (only ``web.feature.*`` keys land in the dict).
  2. Value parsing matches the JS ``_parseValue`` literal-set
     (bool/null literals, signed integers, floats, otherwise raw string).
  3. The dict is present in ``session_info`` even when empty,
     so the JS side never has to special-case missing.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged("web_unit", "web_feature_flags")
class TestFeatureFlagsResolver(TransactionCase):
    """Pins ``IrHttp._resolve_feature_flags`` shape and parsing."""

    def setUp(self):
        super().setUp()
        self.ICP = self.env["ir.config_parameter"].sudo()
        # Clear any pre-existing web.feature.* rows so each test's assertion
        # set (e.g. test_only_prefixed_keys_are_included) is self-contained
        # rather than relying on TransactionCase's per-test savepoint rollback.
        self.ICP.search([("key", "=like", "web.feature.%")]).unlink()
        self.ir_http = self.env["ir.http"]

    def _set(self, name, value):
        self.ICP.set_param(f"web.feature.{name}", value)

    def test_resolve_returns_empty_dict_when_no_flags_set(self):
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(result, {})

    def test_only_prefixed_keys_are_included(self):
        self.ICP.set_param("web.feature.enabled", "true")
        self.ICP.set_param("web.unrelated", "ignore-me")
        self.ICP.set_param("base.show_effect", "true")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(set(result.keys()), {"enabled"})

    def test_bool_literal_parsing(self):
        self._set("on_flag", "true")
        self._set("off_flag", "false")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertIs(result["on_flag"], True)
        self.assertIs(result["off_flag"], False)

    def test_null_literal_parsing(self):
        self._set("explicit_null", "null")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertIsNone(result["explicit_null"])

    def test_integer_parsing(self):
        self._set("retries", "3")
        self._set("negative", "-1")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(result["retries"], 3)
        self.assertIsInstance(result["retries"], int)
        self.assertEqual(result["negative"], -1)
        self.assertIsInstance(result["negative"], int)

    def test_float_parsing(self):
        self._set("ratio", "0.25")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(result["ratio"], 0.25)
        self.assertIsInstance(result["ratio"], float)

    def test_arbitrary_string_passthrough(self):
        self._set("strategy", "ab_test_cohort_42")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(result["strategy"], "ab_test_cohort_42")

    def test_scientific_notation_and_infinity_stay_strings(self):
        # Python's float() accepts ``1.5e2`` / ``inf`` / ``nan`` but the JS
        # numeric regex does not, so the JS resolver would leave these as
        # strings.  This test pins the Python parser to that gate so a flag
        # value resolves to the same type regardless of source layer.
        self._set("scientific", "1.5e2")
        self._set("infinity", "inf")
        self._set("not_a_number", "nan")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(result["scientific"], "1.5e2")
        self.assertEqual(result["infinity"], "inf")
        self.assertEqual(result["not_a_number"], "nan")

    def test_empty_string_parses_to_truthy(self):
        # Mirror JS behaviour: bare ``features=name:`` is treated as enabling
        # the flag, so a stored empty string must also resolve truthy, not
        # falsy. Built directly via create() to make the empty value explicit;
        # set_param() would store it identically (it only special-cases
        # True/False/None, not "").
        self.ICP.create({"key": "web.feature.bare", "value": ""})
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertIs(result["bare"], True)

    # -- ormcache behavior (cache="stable") -----------------------------------

    def test_flags_cached_second_call_issues_no_query(self):
        """The flag set is ormcached: a second resolve within the same cache
        generation must not touch the database at all."""
        self._set("cache_probe", "true")
        first = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertIs(first["cache_probe"], True)
        with self.assertQueryCount(0):
            second = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(second, first)

    def test_param_change_invalidates_cache(self):
        """The cache lives in the "stable" group, the one
        ``ir.config_parameter`` create()/write()/unlink() clear — so every
        mutation path must be reflected by the next resolve."""
        self._set("inval_probe", "1")
        self.assertEqual(
            self.ir_http._resolve_feature_flags(self.ICP)["inval_probe"], 1
        )
        # write() path
        self._set("inval_probe", "2")
        self.assertEqual(
            self.ir_http._resolve_feature_flags(self.ICP)["inval_probe"], 2
        )
        # create() path
        self._set("created_probe", "true")
        self.assertIs(
            self.ir_http._resolve_feature_flags(self.ICP)["created_probe"], True
        )
        # unlink() path
        self.ICP.search([("key", "=", "web.feature.inval_probe")]).unlink()
        self.assertNotIn("inval_probe", self.ir_http._resolve_feature_flags(self.ICP))

    def test_returned_dict_mutation_cannot_poison_cache(self):
        """_resolve_feature_flags builds a fresh dict per call; mutating a
        returned dict must not alter what later calls observe."""
        self._set("mut_probe", "true")
        flags = self.ir_http._resolve_feature_flags(self.ICP)
        flags["mut_probe"] = "tampered"
        self.assertIs(self.ir_http._resolve_feature_flags(self.ICP)["mut_probe"], True)

    def test_value_typing_parity_with_js(self):
        """The Python parser must agree with ``_parseValue`` in feature_flags.js
        on every literal documented in the cascade comment block.
        """
        self._set("a", "true")
        self._set("b", "false")
        self._set("c", "null")
        self._set("d", "0")
        self._set("e", "1.5")
        self._set("f", "hello world")
        result = self.ir_http._resolve_feature_flags(self.ICP)
        self.assertEqual(
            result,
            {
                "a": True,
                "b": False,
                "c": None,
                "d": 0,
                "e": 1.5,
                "f": "hello world",
            },
        )
