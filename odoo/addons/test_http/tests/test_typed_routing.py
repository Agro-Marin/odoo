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
        specs = build_param_specs(_all_optional)
        for bad in ({"a": 1}, [1, 2]):
            with self.assertRaises(BadRequest):
                coerce_params({"name": bad}, specs)

    def test_unannotated_route_has_no_specs(self):
        self.assertEqual(build_param_specs(lambda self, **kw: None), {})

    def test_override_inherits_typed_without_restating_it(self):
        from odoo.http.routing import _check_and_complete_route_definition

        def parent(self, n: int, **kw):
            return None

        parent.original_routing = {"routes": ["/x"], "type": "http", "typed": True}
        parent.original_endpoint = parent

        def child(self, n: int, **kw):
            return None

        child.original_routing = {}
        child.original_endpoint = child

        class FakeController:
            pass

        merged = {"auth": "user", "methods": None, "routes": []}
        merged.update(
            _check_and_complete_route_definition(FakeController, parent, merged)
        )
        self.assertTrue(merged["typed"])

        merged.update(
            _check_and_complete_route_definition(FakeController, child, merged)
        )
        self.assertTrue(merged["typed"], "the override must inherit parameter coercion")

    def test_override_can_opt_out_of_typed(self):
        from odoo.http.routing import _check_and_complete_route_definition

        def child(self, n: int, **kw):
            return None

        child.original_routing = {"typed": False}
        child.original_endpoint = child

        class FakeController:
            pass

        merged = {"auth": "user", "methods": None, "routes": [], "typed": True}
        merged.update(
            _check_and_complete_route_definition(FakeController, child, merged)
        )
        self.assertFalse(merged["typed"])

    def test_merge_never_writes_specs_on_the_shared_wrapper(self):
        from odoo.http.routing import _check_and_complete_route_definition

        def parent(self, n: int, **kw):
            return None

        parent.original_routing = {"routes": ["/x"], "type": "http", "typed": True}
        parent.original_endpoint = parent

        class FakeController:
            pass

        merged = {"auth": "user", "methods": None, "routes": []}
        _check_and_complete_route_definition(FakeController, parent, merged)
        self.assertFalse(hasattr(parent, "_param_specs"))
        self.assertFalse(hasattr(parent, "typed_list_params"))


@tagged("post_install", "-at_install")
class TestTypedRouting(TestHttpBase):
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
