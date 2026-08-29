import ast
import contextlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from odoo.tools import urls


class _Args(dict):
    def getlist(self, key):
        value = self[key]
        return value if isinstance(value, list) else [value]


def fake_request(**query):
    request = mock.Mock()
    request.httprequest.args = _Args(query)
    return request


@contextlib.contextmanager
def _http_serving(request):
    """Stand in for a live odoo.http while keep_query runs.

    keep_query imports `request` when it is called, not when the module loads,
    so the stub has to be in sys.modules at call time -- and only then.
    """
    stub = types.ModuleType("odoo.http")
    stub.request = request  # type: ignore[attr-defined]
    previous = sys.modules.get("odoo.http")
    sys.modules["odoo.http"] = stub
    try:
        yield
    finally:
        if previous is None:
            del sys.modules["odoo.http"]
        else:
            sys.modules["odoo.http"] = previous


class TestKeepQuery(unittest.TestCase):
    def _keep(self, query, *keep, **extra):
        with _http_serving(fake_request(**query)):
            return urls.keep_query(*keep, **extra)

    def test_no_arguments_keeps_everything(self):
        out = self._keep({"a": "1", "b": "2"})
        self.assertEqual(sorted(out.split("&")), ["a=1", "b=2"])

    def test_named_parameter_is_kept(self):
        self.assertEqual(self._keep({"a": "1", "b": "2"}, "a"), "a=1")

    def test_unlisted_parameters_are_dropped(self):
        self.assertNotIn("b=", self._keep({"a": "1", "b": "2"}, "a"))

    def test_glob_pattern(self):
        out = self._keep(
            {"shop_page": "2", "shop_sort": "name", "other": "x"}, "shop_*"
        )
        self.assertEqual(sorted(out.split("&")), ["shop_page=2", "shop_sort=name"])

    def test_glob_is_fnmatch_not_a_prefix(self):
        out = self._keep({"p1": "a", "p2": "b", "px": "c"}, "p[12]")
        self.assertEqual(sorted(out.split("&")), ["p1=a", "p2=b"])

    def test_additional_params_are_added(self):
        out = self._keep({"a": "1"}, "a", page=4)
        self.assertEqual(sorted(out.split("&")), ["a=1", "page=4"])

    def test_additional_params_override_the_request(self):
        out = self._keep({"page": "1"}, "page", page=9)
        self.assertEqual(out, "page=9")

    def test_multi_valued_parameter_is_repeated(self):
        out = self._keep({"tag": ["a", "b"]}, "tag")
        self.assertEqual(sorted(out.split("&")), ["tag=a", "tag=b"])

    def test_values_are_url_encoded(self):
        out = self._keep({"q": "a b&c=d"}, "q")
        self.assertNotIn(" ", out)
        self.assertEqual(out, "q=a+b%26c%3Dd")

    def test_no_request_yields_only_additional_params(self):
        with _http_serving(None):
            self.assertEqual(urls.keep_query("a", page=4), "page=4")
            self.assertEqual(urls.keep_query(), "")

    def test_empty_query_string(self):
        self.assertEqual(self._keep({}), "")


if __name__ == "__main__":
    unittest.main()


class TestToolsStaysBelowTheServingTier(unittest.TestCase):
    """odoo.tools sits below odoo.http, which imports odoo.tools in eight places.

    urls.py used to do `from odoo.http import request` at module scope, so
    `import odoo.tools.urls` -- which ir_qweb and ~60 other modules do, most of
    them only for `urljoin` -- dragged in the whole serving tier.  layer_check's
    `tools-stays-below-the-serving-tier` contract is the repo-wide gate; this is
    the unit-level one, and it also pins the deferral itself.
    """

    def test_the_module_does_not_import_odoo_http_at_module_scope(self):
        tree = ast.parse(Path(urls.__file__).read_text(encoding="utf-8"))
        for node in tree.body:  # module scope only, not function bodies
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                self.assertFalse(
                    name == "odoo.http" or name.startswith("odoo.http."),
                    f"{name!r} imported at module scope in {urls.__file__}; "
                    "import it inside the function that needs it",
                )

    def test_importing_it_does_not_pull_in_the_http_stack(self):
        if "odoo.http" in sys.modules:
            self.skipTest("odoo.http already imported by another suite")
        importlib = __import__("importlib")
        importlib.reload(urls)
        self.assertNotIn("odoo.http", sys.modules)

    def test_all_covers_what_libs_web_publishes(self):
        from odoo.libs import web

        self.assertEqual(
            sorted(urls.__all__),
            sorted([*web.__all__, "keep_query"]),
            "odoo.tools.urls re-exports odoo.libs.web; keep the two in step",
        )
