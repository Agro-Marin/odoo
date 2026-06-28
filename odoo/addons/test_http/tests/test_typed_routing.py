"""Typed routing: annotation-driven param coercion/validation (``@route(typed=True)``).

``TestTypedParams`` is a DB-free unit test of the coercion core
(:mod:`odoo.http._params`); ``TestTypedRouting`` drives a real ``typed=True``
route over HTTP to prove the wiring end to end, including the 400 responses.
"""

from werkzeug.exceptions import BadRequest

from odoo.http._params import ParamSpec, build_param_specs, coerce_params
from odoo.tests import BaseCase, tagged

from odoo.addons.test_http.tests.test_common import TestHttpBase


def _all_optional(self, n: int = 0, x: float = 1.0, flag: bool = False,
                  name: str = "", ids: list[int] | None = None, raw=None,
                  opt: int | None = None, **kw):
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
        self.assertEqual(out, {"n": 5, "x": 2.5, "flag": True, "name": "7", "raw": "kept"})

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

    def test_unannotated_route_has_no_specs(self):
        self.assertEqual(build_param_specs(lambda self, **kw: None), {})


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
