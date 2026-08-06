"""``<function name="...">`` in a data file must refuse unsafe attribute names.

``_eval_xml`` resolves the ``name`` attribute of a ``<function>`` element with a
plain ``getattr`` on the model, so the name decides which attribute of a live
recordset gets called.  Data files are not always authored by the operator —
``base_import_module`` lets an administrator upload a module whose data files
run through this path — so dunders and the frame/code internals listed in
``safe_eval._UNSAFE_ATTRIBUTES`` are refused, the same names ``safe_eval``
refuses for attribute access in expressions.

The guard existed upstream and was dropped in this fork's ``convert.py``
decomposition with nothing replacing it and no test covering it; these tests
exist so its removal is loud rather than silent.  They are DB-free: the check
runs on the name alone, before any model, env or registry is touched, which is
also why it can be tested without a database.
"""

import unittest

from lxml import etree

from odoo.tools.convert import _eval_xml
from odoo.tools.safe_eval import _UNSAFE_ATTRIBUTES


class _ExplodingEnv(dict):
    """An env whose every use fails — the guard must not reach it."""

    context: dict = {}

    def __getitem__(self, key):
        raise AssertionError(f"the name guard let {key!r} through to model resolution")


def _function_node(name: str) -> etree._Element:
    return etree.fromstring(f'<function model="res.partner" name="{name}"/>')


class TestFunctionNameGuard(unittest.TestCase):
    def test_dunder_names_are_refused(self):
        for name in (
            "__getattribute__",
            "__class__",
            "__init__",
            "__dict__",
            "_do__thing",
        ):
            with self.subTest(name=name):
                with self.assertRaises(NameError) as ctx:
                    _eval_xml(None, _function_node(name), _ExplodingEnv())
                self.assertIn(name, str(ctx.exception))

    def test_every_unsafe_attribute_is_refused(self):
        for name in _UNSAFE_ATTRIBUTES:
            with self.subTest(name=name):
                with self.assertRaises(NameError):
                    _eval_xml(None, _function_node(name), _ExplodingEnv())

    def test_a_missing_name_becomes_the_empty_string(self):
        """A ``<function>`` with no ``name`` must not reach ``getattr(model, None)``.

        The empty name is not itself forbidden (upstream does not forbid it
        either) — it passes the guard and fails later on attribute lookup. What
        the ``or ""`` guarantees is that the guard's membership tests operate on
        a string, so a nameless element cannot skip them via ``None``.
        """
        node = etree.fromstring('<function model="res.partner"/>')
        with self.assertRaises(AssertionError):
            _eval_xml(None, node, _ExplodingEnv())

    def test_an_ordinary_name_passes_the_guard(self):
        """The guard rejects on the name only — an ordinary one proceeds.

        Asserted through ``_ExplodingEnv``: reaching model resolution (an
        ``AssertionError``, not a ``NameError``) is exactly what "passed the
        guard" means here, and keeps the test DB-free.
        """
        with self.assertRaises(AssertionError) as ctx:
            _eval_xml(None, _function_node("create"), _ExplodingEnv())
        self.assertIn("res.partner", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
