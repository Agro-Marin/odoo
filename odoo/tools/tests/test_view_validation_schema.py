import unittest

from lxml import etree

from odoo.tools import view_validation


class TestRegisterSchema(unittest.TestCase):
    """`register_schema` is the seam a view type declares its RelaxNG through.

    Before it, `relaxng()` resolved `base/rng/<type>_view.rng` and nothing else,
    so a module shipping its own schema could not use the helper and hand-rolled
    the load/cache/log block instead -- four near-identical copies across
    web_map, web_cohort, web_grid and web_threed.
    """

    def setUp(self):
        self._schemas = view_validation.registered_schemas()
        self._cache = dict(view_validation._relaxng_cache)
        self.addCleanup(self._restore)

    def _restore(self):
        view_validation._view_schemas.clear()
        view_validation._view_schemas.update(self._schemas)
        view_validation._relaxng_cache.clear()
        view_validation._relaxng_cache.update(self._cache)

    def test_the_core_view_types_are_registered(self):
        schemas = view_validation.registered_schemas()
        for view_type in ("activity", "calendar", "graph", "list", "pivot", "search"):
            self.assertIn(view_type, schemas)
            self.assertTrue(schemas[view_type].endswith(f"{view_type}_view.rng"))

    def test_form_and_kanban_declare_no_schema(self):
        # Not an oversight: both are qweb-based and validated structurally by
        # ir.ui.view._check_view_tag_*. Absence of a file and a declaration of
        # None have to stay distinguishable, or a gate cannot tell a deliberate
        # omission from a forgotten one.
        schemas = view_validation.registered_schemas()
        self.assertIsNone(schemas.get("form"))
        self.assertIsNone(schemas.get("kanban"))

    def test_a_registered_schema_is_compiled_and_cached(self):
        first = view_validation.relaxng("list")
        self.assertIsNotNone(first)
        self.assertIs(view_validation.relaxng("list"), first)

    def test_re_registering_drops_the_compiled_schema(self):
        view_validation.relaxng("list")
        self.assertIn("list", view_validation._relaxng_cache)
        view_validation.register_schema("list", "base/rng/pivot_view.rng")
        self.assertNotIn("list", view_validation._relaxng_cache)

    def test_registered_schemas_returns_a_copy(self):
        view_validation.registered_schemas()["list"] = "tampered"
        self.assertNotEqual(view_validation.registered_schemas()["list"], "tampered")


class TestSchemaValid(unittest.TestCase):
    def setUp(self):
        self._schemas = view_validation.registered_schemas()
        self._cache = dict(view_validation._relaxng_cache)
        self.addCleanup(self._restore)

    def _restore(self):
        view_validation._view_schemas.clear()
        view_validation._view_schemas.update(self._schemas)
        view_validation._relaxng_cache.clear()
        view_validation._relaxng_cache.update(self._cache)

    def test_a_conforming_arch_passes(self):
        arch = etree.fromstring('<list><field name="name"/></list>')
        self.assertTrue(view_validation.schema_valid(arch))

    def test_a_violating_arch_is_refused(self):
        arch = etree.fromstring("<list><nonsense/></list>")
        self.assertFalse(view_validation.schema_valid(arch))

    def test_an_unregistered_view_type_is_skipped(self):
        # A type nobody declared must pass rather than be refused: this runs on
        # every arch, including tags that are not view roots at all.
        arch = etree.fromstring("<whatever><nonsense/></whatever>")
        self.assertTrue(view_validation.schema_valid(arch))

    def test_a_type_declaring_None_is_skipped(self):
        view_validation.register_schema("kanban", None)
        arch = etree.fromstring("<kanban><nonsense/></kanban>")
        self.assertTrue(view_validation.schema_valid(arch))

    def test_a_declared_schema_that_will_not_load_refuses_the_view(self):
        # The failure mode this exists to prevent: a typo in the path silently
        # switching validation off for the type, so every arch passes and the
        # check becomes indistinguishable from a check that is not running.
        view_validation.register_schema("list", "base/rng/no_such_view.rng")
        arch = etree.fromstring('<list><field name="name"/></list>')
        with self.assertLogs("odoo.tools.view_validation", "ERROR"):
            self.assertFalse(view_validation.schema_valid(arch))


class TestValidViewRunsTheSchema(unittest.TestCase):
    def test_valid_view_refuses_a_schema_violation_without_a_registered_predicate(self):
        # The schema check moved into `valid_view` itself, ahead of the per-tag
        # predicates, so a type is schema-validated because it declared a schema
        # and not because someone added it to a decorator in this module.
        arch = etree.fromstring("<list><nonsense/></list>")
        self.assertFalse(view_validation.valid_view(arch))

    def test_valid_view_still_runs_the_per_tag_predicates(self):
        calls = []

        @view_validation.register_validator("probe")
        def _probe(arch, **kwargs):
            calls.append(arch.tag)
            return False

        try:
            arch = etree.fromstring("<probe/>")
            self.assertFalse(view_validation.valid_view(arch))
            self.assertEqual(calls, ["probe"])
        finally:
            view_validation._validators["probe"].remove(_probe)
