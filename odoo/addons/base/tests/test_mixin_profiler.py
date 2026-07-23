import threading

from odoo.tests import TransactionCase
from odoo.tools import mixin_profiler as mp


class TestMixinProfiler(TransactionCase):
    """The method-level mixin profiler must collect stats for wrapped methods
    and undo its monkey-patching cleanly."""

    def setUp(self):
        super().setUp()
        mp.clear_profile_data()
        # metrics only accumulate thread.query_time if the attribute exists
        threading.current_thread().query_time = 0.0
        self.addCleanup(mp.clear_profile_data)
        self.addCleanup(
            mp.unprofile_methods, "res.partner", ["create", "write"], self.registry
        )

    def test_collects_stats_and_restores(self):
        Partner = self.registry["res.partner"]
        original_create = Partner.create

        mp.profile_methods("res.partner", ["create", "write"], self.registry)
        self.assertTrue(hasattr(Partner.create, "_profiled"))

        with mp.profiling_enabled():
            partners = self.env["res.partner"].create(
                [{"name": f"Prof {i}"} for i in range(5)]
            )
            partners.write({"comment": "x"})

        report = mp.get_profile_report()
        self.assertIn("res.partner.create", report)
        self.assertIn("res.partner.write", report)

        data = mp._get_data()
        self.assertGreaterEqual(data.methods["res.partner.create"]["calls"], 1)
        self.assertGreaterEqual(data.methods["res.partner.write"]["calls"], 1)

        mp.unprofile_methods("res.partner", ["create", "write"], self.registry)
        self.assertIs(Partner.create, original_create)

    def test_disabled_is_noop(self):
        mp.profile_methods("res.partner", ["create"], self.registry)
        # not inside profiling_enabled(): nothing should be collected
        self.env["res.partner"].create({"name": "NoProf"})
        self.assertEqual(mp.get_profile_report(), "No profiling data collected.")

    def _unprofile_all(self, profiled, extra_by_model=None):
        """Cleanup helper: unwrap every model touched by profile_module().

        Leaving even one wrapped model behind leaks the wrapper (or, worse, a
        pinned copy of the original method) on the shared registry class for
        the rest of the process, breaking later tests that patch the model
        definition classes.
        """
        extra_by_model = extra_by_model or {}
        for model_name in profiled:
            methods = list(mp._DEFAULT_MODULE_METHODS) + list(
                extra_by_model.get(model_name, ())
            )
            self.addCleanup(mp.unprofile_methods, model_name, methods, self.registry)
        for model_name, methods in extra_by_model.items():
            if model_name not in profiled:
                self.addCleanup(
                    mp.unprofile_methods, model_name, list(methods), self.registry
                )

    def test_profile_module_discovers_models(self):
        profiled = mp.profile_module(self.env, "base")
        self._unprofile_all(profiled)
        self.assertIn("res.partner", profiled)
        self.assertIn("res.users", profiled)

    def test_profile_module_skips_abstract_crud(self):
        # An abstract mixin has no records; wrapping its inherited create only
        # catches super()-chain pass-throughs and double-counts concrete models.
        # profile_module must skip the default CRUD on abstract models but still
        # honour explicitly requested methods.
        extra_by_model = {"base": ["_compute_display_name"]}
        profiled = mp.profile_module(self.env, "base", extra_by_model=extra_by_model)
        self._unprofile_all(profiled, extra_by_model)
        # 'base' is abstract: not wrapped for default CRUD via discovery of a
        # concrete model, and its own 'create' stays the framework generic
        Base = self.registry["base"]
        self.assertTrue(Base._abstract)
        self.assertFalse(hasattr(Base.create, "_profiled"))
        # a concrete model discovered by the same module is still wrapped
        self.assertIn("res.partner", profiled)
        self.assertTrue(hasattr(self.registry["res.partner"].create, "_profiled"))

    def test_unprofile_restores_mro_resolution(self):
        """Un-profiling must not pin a copy of an MRO-inherited method onto the
        registry class's own ``__dict__``.

        The registry class for ``res.partner`` inherits ``create`` from its
        model definition class; a pinned own-attribute copy would permanently
        shadow the definition class, silently bypassing any later
        ``patch.object(ResPartner, "create")`` (a supported test idiom) —
        this was an order-dependent failure of
        ``TestPartner.test_find_or_create`` in full-suite runs.
        """
        Partner = self.registry["res.partner"]
        self.assertNotIn("create", Partner.__dict__)
        mp.profile_methods("res.partner", ["create"], self.registry)
        self.assertIn("create", Partner.__dict__)
        mp.unprofile_methods("res.partner", ["create"], self.registry)
        self.assertNotIn("create", Partner.__dict__)
        # resolution falls back to the definition class through the MRO
        self.assertFalse(hasattr(Partner.create, "_profiled"))
