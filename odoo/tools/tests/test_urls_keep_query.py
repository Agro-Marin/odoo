"""``keep_query`` builds the "carry the current querystring forward" links.

Untested until now, and its behaviour is not obvious from the signature: the
no-argument call means "keep everything", explicit ``additional_params`` must
win over what the request carries, patterns are ``fnmatch`` globs (not
prefixes), multi-valued parameters must survive as repeated pairs, and the
whole thing must degrade to "just the extra params" outside a request.

``odoo.tools.urls`` does ``from odoo.http import request`` at import time, and
``odoo.http`` drags the whole HTTP stack in, so a stub is registered before the
import (the standalone-suite convention -- see ``odoo._testing_bootstrap``).
The tests then rebind ``odoo.tools.urls.request``, which is where the name the
function actually reads lives.
"""

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

# Drop the stub as soon as the import that needed it is done.  It used to be
# left in ``sys.modules`` for the rest of the process: pytest imports every
# test module during collection, so a later module importing the *real*
# ``odoo.http`` (``test_hashing.py``, via ``odoo.addons.base``) got this
# two-attribute stub instead and failed on an unrelated name -- a failure that
# appears only in the whole-directory run, never in isolation.  ``urls``
# already holds its own reference to the stubbed ``request``, and the tests
# rebind that attribute anyway.  Keyed on a marker rather than a flag set
# above, so the preamble stays import-only (ruff E402).
if getattr(sys.modules.get("odoo.http"), "__odoo_test_stub__", False):
    del sys.modules["odoo.http"]


class _Args(dict):
    """Minimal stand-in for werkzeug's MultiDict over the query string."""

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
        """The documented ``keep_params = ("*",)`` default."""
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
        """``?`` and ``[]`` are real glob syntax here, not literals."""
        out = self._keep({"p1": "a", "p2": "b", "px": "c"}, "p[12]")
        self.assertEqual(sorted(out.split("&")), ["p1=a", "p2=b"])

    def test_additional_params_are_added(self):
        out = self._keep({"a": "1"}, "a", page=4)
        self.assertEqual(sorted(out.split("&")), ["a=1", "page=4"])

    def test_additional_params_override_the_request(self):
        """The override guard: an explicit value must win over the query string."""
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
        """Outside a request (cron, shell) there is no querystring to keep."""
        with mock.patch.object(urls, "request", None):
            self.assertEqual(urls.keep_query("a", page=4), "page=4")
            self.assertEqual(urls.keep_query(), "")

    def test_empty_query_string(self):
        self.assertEqual(self._keep({}), "")


if __name__ == "__main__":
    unittest.main()
