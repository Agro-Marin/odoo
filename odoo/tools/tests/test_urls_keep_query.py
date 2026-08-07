import sys
import types
import unittest
from unittest import mock

if "odoo.http" not in sys.modules:
    _http_stub = types.ModuleType("odoo.http")
    _http_stub.request = None
    _http_stub.__odoo_test_stub__ = True
    sys.modules["odoo.http"] = _http_stub

from odoo.tools import urls

if getattr(sys.modules.get("odoo.http"), "__odoo_test_stub__", False):
    del sys.modules["odoo.http"]


class _Args(dict):
    def getlist(self, key):
        value = self[key]
        return value if isinstance(value, list) else [value]


def fake_request(**query):
    request = mock.Mock()
    request.httprequest.args = _Args(query)
    return request


class TestKeepQuery(unittest.TestCase):
    def _keep(self, query, *keep, **extra):
        with mock.patch.object(urls, "request", fake_request(**query)):
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
        with mock.patch.object(urls, "request", None):
            self.assertEqual(urls.keep_query("a", page=4), "page=4")
            self.assertEqual(urls.keep_query(), "")

    def test_empty_query_string(self):
        self.assertEqual(self._keep({}), "")


if __name__ == "__main__":
    unittest.main()
