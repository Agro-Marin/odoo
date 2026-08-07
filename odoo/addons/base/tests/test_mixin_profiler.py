import threading

from odoo.tests import TransactionCase
from odoo.tools import mixin_profiler as mp


class TestMixinProfiler(TransactionCase):
    def setUp(self):
        super().setUp()
        mp.clear_profile_data()
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
        self.env["res.partner"].create({"name": "NoProf"})
        self.assertEqual(mp.get_profile_report(), "No profiling data collected.")

    def _unprofile_all(self, profiled, extra_by_model=None):
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
        extra_by_model = {"base": ["_compute_display_name"]}
        profiled = mp.profile_module(self.env, "base", extra_by_model=extra_by_model)
        self._unprofile_all(profiled, extra_by_model)
        Base = self.registry["base"]
        self.assertTrue(Base._abstract)
        self.assertFalse(hasattr(Base.create, "_profiled"))
        self.assertIn("res.partner", profiled)
        self.assertTrue(hasattr(self.registry["res.partner"].create, "_profiled"))

    def test_unprofile_restores_mro_resolution(self):
        Partner = self.registry["res.partner"]
        self.assertNotIn("create", Partner.__dict__)
        mp.profile_methods("res.partner", ["create"], self.registry)
        self.assertIn("create", Partner.__dict__)
        mp.unprofile_methods("res.partner", ["create"], self.registry)
        self.assertNotIn("create", Partner.__dict__)
        self.assertFalse(hasattr(Partner.create, "_profiled"))
