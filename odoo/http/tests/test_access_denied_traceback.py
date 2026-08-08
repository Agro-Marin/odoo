"""``AccessDenied`` must not serve its traceback or exception chain.

The suppression is done by the HTTP layer after the raise, not by the
constructor. That is easy to get backwards: until 2026-08-08 ``__init__`` also
called ``suppress_traceback()``, which was a guaranteed no-op — the interpreter
sets ``__traceback__``/``__context__``/``__cause__`` at the ``raise``, not at
construction — and reading it invited deleting the two call sites that actually
work. These tests pin both halves so neither can be removed as redundant.
"""

import ast
import pathlib

import pytest

from odoo.exceptions import AccessDenied

_HTTP_DIR = pathlib.Path(__file__).resolve().parent.parent
#: The call sites that do the real suppression, and the file each lives in.
_EXPECTED_CALL_SITES = {"application.py", "_serve.py"}


class TestSuppression:
    def test_construction_leaves_nothing_to_suppress(self):
        exc = AccessDenied()
        assert exc.__traceback__ is None
        assert exc.__context__ is None
        assert exc.__cause__ is None

    def test_a_raise_attaches_a_traceback_and_a_context(self):
        """Why the constructor cannot do this job."""
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
        """Raise ``AccessDenied`` with an implicit ``__context__``, as a handler would."""
        try:
            raise ValueError("inner")
        except ValueError:
            raise AccessDenied  # noqa: B904  the implicit context IS the fixture

    def test_no_dead_traceback_attribute(self):
        """``self.traceback = ("", "", "")`` had zero readers workspace-wide."""
        assert not hasattr(AccessDenied(), "traceback")


class TestTheHttpLayerStillCallsIt:
    """A behavioural test needs a served request; this pins the call sites."""

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
