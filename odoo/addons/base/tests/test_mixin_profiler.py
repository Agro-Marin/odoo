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

    def test_profile_module_discovers_models(self):
        profiled = mp.profile_module(self.env, "base")
        self.assertIn("res.partner", profiled)
        self.assertIn("res.users", profiled)
        self.addCleanup(
            mp.unprofile_methods,
            "res.partner",
            list(mp._DEFAULT_MODULE_METHODS),
            self.registry,
        )
