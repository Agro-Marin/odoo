"""safe_eval must not destroy the class of a database error.

`_BUBBLEUP_EXCEPTIONS` named `OperationalError`, so what survived evaluation was
whatever psycopg happens to derive from it. Measured, raised from inside
evaluated code: `SerializationFailure`, `DeadlockDetected` and
`LockNotAvailable` came out intact, while `UniqueViolation`,
`ForeignKeyViolation`, `ReadOnlySqlTransaction` and `FeatureNotSupported` came
out as `ValueError`.

Every one of those is a class the framework has a policy for, and every policy
keys on the class: `retrying()` turns an `IntegrityError` into a
`ValidationError`, and replays `PG_RETRY_EXCEPTIONS` and a marked stale cached
plan. Wrapped, none of that fires -- a server action violating a constraint
reached the user as `ValueError: UniqueViolation(...) while evaluating ...`.

These are the mechanism checks, which run without a database. The end-to-end
behaviour -- that a constraint violated by a server action now arrives as a
`ValidationError` -- is pinned in `base/tests/test_db_cursor.py`, because the
taxonomy lookup needs a real `import odoo.db`.
"""

import inspect
import sys
import unittest

import psycopg

from odoo.tools import safe_eval as mod
from odoo.tools.safe_eval import safe_eval


def _thrower(exc):
    def go():
        raise exc

    return go


def _eval_raising(exc):
    try:
        safe_eval("boom()", {"boom": _thrower(exc)}, mode="exec")
    except BaseException as caught:
        return caught
    raise AssertionError("safe_eval swallowed the exception")


class TestTheTaxonomyIsReadNotImported(unittest.TestCase):
    def test_it_is_a_sys_modules_lookup(self):
        src = inspect.getsource(mod._is_classified_db_error)
        self.assertIn('sys.modules.get("odoo.db.errors")', src)
        self.assertNotIn(
            "import",
            src.split('"""')[-1],
            "importing odoo.db.errors here is a cycle -- odoo.db's package "
            "__init__ imports odoo.tools -- and raising ImportError from inside "
            "an exception handler would replace the error being reported",
        )

    def test_it_degrades_to_the_old_behaviour_when_odoo_db_is_absent(self):
        saved = sys.modules.pop("odoo.db.errors", None)
        try:
            self.assertFalse(
                mod._is_classified_db_error(psycopg.errors.UniqueViolation("x")),
                "with no taxonomy loaded it must answer False, not raise",
            )
            self.assertIsInstance(
                _eval_raising(psycopg.errors.UniqueViolation("x")),
                ValueError,
                "and the wrapper then behaves exactly as it did before",
            )
        finally:
            if saved is not None:
                sys.modules["odoo.db.errors"] = saved

    def test_a_lookup_miss_cannot_raise(self):
        saved = sys.modules.pop("odoo.db.errors", None)
        try:
            for exc in (ValueError("x"), psycopg.errors.DeadlockDetected("x")):
                with self.subTest(exc=type(exc).__name__):
                    mod._is_classified_db_error(exc)
        finally:
            if saved is not None:
                sys.modules["odoo.db.errors"] = saved


class TestOrdinaryErrorsAreStillWrapped(unittest.TestCase):
    def test_a_coding_error_keeps_its_expression_context(self):
        caught = _eval_raising(NameError("no such name"))
        self.assertIsInstance(
            caught,
            ValueError,
            "the wrapper earns its place for real coding errors: it carries the "
            "expression text, which is what makes a broken server action "
            "debuggable",
        )
        self.assertIn("while evaluating", str(caught))

    def test_the_bubbleup_list_still_holds_its_originals(self):
        self.assertIn(psycopg.OperationalError, mod._BUBBLEUP_EXCEPTIONS)
        self.assertIn(ZeroDivisionError, mod._BUBBLEUP_EXCEPTIONS)


if __name__ == "__main__":
    unittest.main()
