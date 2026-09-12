import importlib.util
from pathlib import Path

from odoo.tests import TransactionCase, tagged


def _load(version):
    path = Path(__file__).parent.parent / "migrations" / version / "post-migrate.py"
    spec = importlib.util.spec_from_file_location(f"api_ai_{version}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestSeedPriceCorrection(TransactionCase):
    SEEDED = {
        "cost_per_1m_input": 2.50,
        "cost_per_1m_output": 10.00,
        "cost_per_1m_image": 2.125,
    }

    def setUp(self):
        super().setUp()
        self.migration = _load("1.17.0")
        self.mini = self.env.ref("api_ai.ai_model_openai_gpt_4o_mini")

    def _migrate(self, version="19.0.1.16.0"):
        self.env.flush_all()
        self.migration.migrate(self.env.cr, version)
        self.env.invalidate_all()

    def test_a_row_still_carrying_the_seed_is_corrected(self):
        self.mini.write(self.SEEDED)
        self._migrate()
        self.assertEqual(
            (self.mini.cost_per_1m_input, self.mini.cost_per_1m_output),
            (0.15, 0.60),
        )

    def test_a_row_an_administrator_touched_is_left_alone(self):
        self.mini.write({**self.SEEDED, "cost_per_1m_input": 2.40})
        self._migrate()
        self.assertEqual(
            (self.mini.cost_per_1m_input, self.mini.cost_per_1m_output),
            (2.40, 10.00),
        )

    def test_a_fresh_install_is_not_migrated(self):
        self.mini.write(self.SEEDED)
        self._migrate(version=None)
        self.assertEqual(self.mini.cost_per_1m_input, 2.50)
