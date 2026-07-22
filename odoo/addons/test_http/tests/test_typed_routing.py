"""Typed routing: annotation-driven param coercion/validation (``@route(typed=True)``).

``TestTypedParams`` is a DB-free unit test of the coercion core
(:mod:`odoo.http._params`); ``TestTypedRouting`` drives a real ``typed=True``
route over HTTP to prove the wiring end to end, including the 400 responses.
"""

from werkzeug.exceptions import BadRequest

from odoo.http._params import ParamSpec, build_param_specs, coerce_params
from odoo.tests import BaseCase, tagged

from odoo.addons.test_http.tests.test_common import TestHttpBase


def _all_optional(
    self,
    n: int = 0,
    x: float = 1.0,
    flag: bool = False,
    name: str = "",
    ids: list[int] | None = None,
    raw=None,
    opt: int | None = None,
    **kw,
):
    return None


def _required(self, n: int, **kw):
    return None


@tagged("post_install", "-at_install")
class TestTypedParams(BaseCase):
    """Pure unit tests of build_param_specs / coerce_params."""

    def test_specs_cover_annotated_keyword_params_only(self):
        specs = build_param_specs(_all_optional)
        self.assertEqual(set(specs), {"n", "x", "flag", "name", "ids", "opt"})
        self.assertEqual(specs["n"], ParamSpec(int, None, False, False))
        self.assertEqual(specs["ids"], ParamSpec(list, int, True, False))
        self.assertEqual(specs["opt"], ParamSpec(int, None, True, False))
        self.assertTrue(build_param_specs(_required)["n"].required)

    def test_scalar_coercion(self):
        out = coerce_params(
            {"n": "5", "x": "2.5", "flag": "on", "name": 7, "raw": "kept"},
            build_param_specs(_all_optional),
        )
        self.assertEqual(
            out, {"n": 5, "x": 2.5, "flag": True, "name": "7", "raw": "kept"}
        )

    def test_bool_tokens(self):
        specs = build_param_specs(_all_optional)
        for token in ("true", "1", "on", "yes"):
            self.assertIs(coerce_params({"flag": token}, specs)["flag"], True)
        for token in ("false", "0", "off", ""):
            self.assertIs(coerce_params({"flag": token}, specs)["flag"], False)

    def test_list_wraps_and_coerces_elements(self):
        specs = build_param_specs(_all_optional)
        self.assertEqual(coerce_params({"ids": "5"}, specs)["ids"], [5])
        self.assertEqual(coerce_params({"ids": ["1", "2"]}, specs)["ids"], [1, 2])

    def test_optional_and_absent(self):
        specs = build_param_specs(_all_optional)
        self.assertIsNone(coerce_params({"opt": None}, specs)["opt"])
        self.assertNotIn("opt", coerce_params({}, specs))

    def test_missing_required_raises_bad_request(self):
        with self.assertRaises(BadRequest):
            coerce_params({}, build_param_specs(_required))

    def test_uncoercible_values_raise_bad_request(self):
        specs = build_param_specs(_all_optional)
        for bad in ({"n": "abc"}, {"flag": "maybe"}, {"n": True}, {"x": "NaNN"}):
            with self.assertRaises(BadRequest):
                coerce_params(bad, specs)

    def test_fractional_float_for_int_param_is_rejected(self):
        # ``int(3.7)`` truncates; a fractional JSON number for an int param is
        # a caller bug and must 400, not silently round toward zero. Integral
        # floats (JS clients serialize 3 as 3.0) still coerce.
        specs = build_param_specs(_all_optional)
        with self.assertRaises(BadRequest):
            coerce_params({"n": 3.7}, specs)
        self.assertEqual(coerce_params({"n": 3.0}, specs)["n"], 3)

    def test_non_finite_float_is_rejected(self):
        specs = build_param_specs(_all_optional)
        for bad in ("nan", "inf", "-inf", float("nan"), float("inf")):
            with self.assertRaises(BadRequest):
                coerce_params({"x": bad}, specs)

    def test_container_for_str_param_is_rejected(self):
        # A JSON object/array for a str param must not arrive as its repr.
        specs = build_param_specs(_all_optional)
        for bad in ({"a": 1}, [1, 2]):
            with self.assertRaises(BadRequest):
                coerce_params({"name": bad}, specs)

    def test_unannotated_route_has_no_specs(self):
        self.assertEqual(build_param_specs(lambda self, **kw: None), {})

    def test_override_without_typed_restated_warns(self):
        """Coercion is compiled per decorator; an override that drops
        ``typed=True`` must be flagged, since the merged routing (and OpenAPI)
        still advertise coercion."""
        from odoo.http.routing import _check_and_complete_route_definition

        def parent(self, n: int, **kw):
            return None

        parent.original_routing = {"routes": ["/x"], "type": "http", "typed": True}

        def child(self, n: int, **kw):
            return None

        child.original_routing = {}

        class FakeController:
            pass

        merged = {"auth": "user", "methods": None, "routes": []}
        # The hook returns the effective fragment (it no longer mutates
        # ``original_routing``); merge from the return value like the caller.
        merged.update(
            _check_and_complete_route_definition(FakeController, parent, merged)
        )
        with self.assertLogs("odoo.http.routing", level="WARNING") as capture:
            _check_and_complete_route_definition(FakeController, child, merged)
        self.assertIn("without restating typed=True", capture.output[0])

        # Restating typed=True (or explicitly opting out) stays silent.
        child.original_routing = {"typed": True}
        with self.assertNoLogs("odoo.http.routing", level="WARNING"):
            _check_and_complete_route_definition(FakeController, child, merged)


@tagged("post_install", "-at_install")
class TestTypedRouting(TestHttpBase):
    """End-to-end: a ``typed=True`` route coerces query strings and 400s on bad input."""

    def test_query_strings_are_coerced(self):
        res = self.nodb_url_open("/test_http/typed-echo?n=5&flag=on")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "5:int:True:bool")

    def test_default_applies_when_optional_absent(self):
        res = self.nodb_url_open("/test_http/typed-echo?n=7")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "7:int:False:bool")

    def test_uncoercible_int_is_400(self):
        res = self.nodb_url_open("/test_http/typed-echo?n=abc")
        self.assertEqual(res.status_code, 400)

    def test_missing_required_is_400(self):
        res = self.nodb_url_open("/test_http/typed-echo")
        self.assertEqual(res.status_code, 400)

    def test_repeated_query_key_fills_list_param(self):
        # The flat params merge keeps one value per key; the dispatcher re-reads
        # ``list``-annotated params via ``getlist`` so none are dropped.
        res = self.nodb_url_open("/test_http/typed-list?vals=1&vals=2&vals=3")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "[1, 2, 3]")

    def test_single_query_key_still_wraps_to_list(self):
        res = self.nodb_url_open("/test_http/typed-list?vals=7")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "[7]")

    def test_absent_list_param_keeps_default(self):
        res = self.nodb_url_open("/test_http/typed-list")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "None")

    def test_uncoercible_list_item_is_400(self):
        res = self.nodb_url_open("/test_http/typed-list?vals=1&vals=x")
        self.assertEqual(res.status_code, 400)
