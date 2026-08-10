import ast
import pathlib

import pytest

from odoo.exceptions import AccessDenied

_HTTP_DIR = pathlib.Path(__file__).resolve().parent.parent
_EXPECTED_CALL_SITES = {"application.py", "_serve.py"}


class TestSuppression:
    def test_construction_leaves_nothing_to_suppress(self):
        exc = AccessDenied()
        assert exc.__traceback__ is None
        assert exc.__context__ is None
        assert exc.__cause__ is None

    def test_a_raise_attaches_a_traceback_and_a_context(self):
        with pytest.raises(AccessDenied) as caught:
            self._raise_denied_from_a_value_error()
        exc = caught.value
        assert exc.__traceback__ is not None
        assert isinstance(exc.__context__, ValueError)

    def test_suppress_traceback_clears_all_three_after_a_raise(self):
        with pytest.raises(AccessDenied) as caught:
            self._raise_denied_from_a_value_error()
        exc = caught.value
        exc.suppress_traceback()
        assert exc.__traceback__ is None
        assert exc.__context__ is None
        assert exc.__cause__ is None

    @staticmethod
    def _raise_denied_from_a_value_error() -> None:
        try:
            raise ValueError("inner")
        except ValueError:
            raise AccessDenied  # noqa: B904  the implicit context IS the fixture

    def test_no_dead_traceback_attribute(self):
        assert not hasattr(AccessDenied(), "traceback")


class TestTheHttpLayerStillCallsIt:
    def test_both_http_call_sites_are_present(self):
        found = set()
        for path in _HTTP_DIR.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "suppress_traceback"
                ):
                    found.add(path.name)
        assert found == _EXPECTED_CALL_SITES, (
            f"AccessDenied.suppress_traceback() call sites changed: {found}. "
            f"Removing one serves a full traceback and the chained cause in an "
            f"authentication failure; the constructor does NOT cover for it."
        )
