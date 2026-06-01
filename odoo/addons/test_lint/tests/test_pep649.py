"""Regression test for PEP 649 annotation-resolution failures.

Guards against the pattern where a module imports a type only under
``if TYPE_CHECKING:`` but uses it in a runtime-visible annotation.
See :mod:`_checker_pep649` for background.
"""

from odoo.tests import BaseCase

from ._checker_pep649 import scan_module

# Modules whose public callables must introspect cleanly.  A regression
# that re-introduces a ``TYPE_CHECKING``-only annotation in any of these
# modules will fail the test and name the offending identifier so the
# contributor knows what to fix.
#
# When the cycle itself cannot be runtime-imported (e.g. ``Environment``
# in ``odoo.tools`` or ``Field`` in ``odoo.tools.sql``), the fix pattern
# is to keep the ``TYPE_CHECKING`` import for static type checkers but
# provide a runtime fallback alias (usually ``typing.Any``) in the
# ``else:`` branch — see ``odoo.tools.files``, ``odoo.tools.locale_utils``
# and ``odoo.tools.sql`` for the shape.
CLEAN_MODULES = (
    "odoo.cli.command",
    "odoo.cli.module",
    "odoo.cli.obfuscate",
    "odoo.cli.populate",
    "odoo.cli.scaffold",
    "odoo.cli.upgrade_code",
    "odoo.db.cursor",
    "odoo.db.pool",
    "odoo.db.utils",
    "odoo.http._csrf",
    "odoo.http._protocols",
    "odoo.http._response",
    "odoo.http._serve",
    "odoo.http.application",
    "odoo.http.controller",
    "odoo.http.dispatcher",
    "odoo.http.helpers",
    "odoo.http.request_class",
    "odoo.http.routing",
    "odoo.http.session",
    "odoo.service.db",
    "odoo.service.server",
    "odoo.tools.cloc",
    "odoo.tools.config",
    "odoo.tools.files",
    "odoo.tools.locale_utils",
    "odoo.tools.sql",
)


class TestPEP649Annotations(BaseCase):
    """Ensure annotations on public symbols remain introspectable."""

    def test_clean_modules_introspect(self):
        for modname in CLEAN_MODULES:
            with self.subTest(module=modname):
                fails = scan_module(modname)
                self.assertFalse(
                    fails,
                    msg=(
                        f"{modname} has annotation-resolution failures.  "
                        f"Move the offending import out of `if TYPE_CHECKING:`, "
                        f"or — if a runtime import would cycle — keep the "
                        f"TYPE_CHECKING import and add a ``typing.Any`` "
                        f"fallback in an ``else:`` branch.  Failures:\n  "
                        + "\n  ".join(fails)
                    ),
                )
