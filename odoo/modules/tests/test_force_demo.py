"""`force_demo` must record which modules actually took demo data.

`ir_module_module.demo` gates `ModuleNode.demo_installable` and the upgrade
branch of `load_module_graph`, so it has to mean "demo mode was applied to this
module". `force_demo` used to set the whole column true before loading anything
and then discard every `load_demo` return value, which recorded a module whose
demo XML had just raised as carrying demo data. Reproduced through the real
`odoo-bin module force-demo`: a probe addon whose demo referenced a nonexistent
field logged "demo data failed to install" and came out `demo = t`, while the
ordinary install path recorded `f` for the same module.

Note that `load_demo` returns True for a module with *no* demo data at all, and
must: `demo_installable` is `all(p.demo for p in self.depends)`, so a
demo-less dependency has to count as satisfied or nothing downstream of it
could ever take demo.
"""

import unittest
from unittest.mock import patch

from odoo.modules import loading

BaseCase = unittest.TestCase


class _Package:
    def __init__(self, name):
        self.name = name
        self.id = 0
        self.demo = False


class _Cursor:
    def __init__(self, installed):
        self.installed = installed
        self.statements = []
        self._rows = []

    def execute(self, query, params=None):
        self.statements.append((" ".join(query.split()), params))
        if "SELECT name FROM ir_module_module" in query:
            self._rows = [(name,) for name in self.installed]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


class _Env:
    def __init__(self, cr):
        self.cr = cr

    def __getitem__(self, _model):
        return self

    def invalidate_model(self, _fields):
        return None


def _run(installed, failing):
    cr = _Cursor(installed)
    packages = [_Package(name) for name in installed]

    def fake_load_demo(env, package, idref, mode):
        return package.name not in failing

    with (
        patch.object(loading, "ModuleGraph") as graph_cls,
        patch.object(loading, "load_demo", fake_load_demo),
    ):
        graph_cls.return_value.__iter__ = lambda self: iter(packages)
        loading.force_demo(_Env(cr))
    return cr


class TestForceDemoRecordsWhatLoaded(BaseCase):
    def _update(self, cr):
        return next(
            (q, p) for q, p in cr.statements if q.startswith("UPDATE ir_module_module")
        )

    def test_a_module_whose_demo_failed_is_not_recorded_as_having_demo(self):
        cr = _run(["mod_ok", "mod_broken"], failing={"mod_broken"})
        _query, params = self._update(cr)
        loaded, scope = params
        self.assertEqual(loaded, ["mod_ok"])
        self.assertIn("mod_broken", scope)

    def test_the_update_is_scoped_to_the_modules_that_were_considered(self):
        # The blanket `UPDATE ir_module_module SET demo=True` touched every row
        # in the table -- 654 of 671 on a fresh database, including every
        # uninstalled and uninstallable module, none of which is ever a
        # candidate for demo data.
        cr = _run(["mod_a", "mod_b"], failing=set())
        query, params = self._update(cr)
        self.assertIn("WHERE name = ANY", query)
        self.assertEqual(params, [["mod_a", "mod_b"], ["mod_a", "mod_b"]])

    def test_no_blanket_update_is_issued_before_loading(self):
        cr = _run(["mod_a"], failing=set())
        blanket = [
            q
            for q, _p in cr.statements
            if q.startswith("UPDATE ir_module_module") and "WHERE" not in q
        ]
        self.assertEqual(blanket, [])
