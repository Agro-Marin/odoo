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


@tagged("post_install", "-at_install")
class TestFallbackRelationCarried(TransactionCase):
    def test_the_old_relation_becomes_ordered_hops(self):
        claude = self.env.ref("api_ai.ai_model_claude_sonnet_5")
        later_provider = self.env["ai.provider"].search([("code", "=", "moonshot")])
        earlier_provider = self.env["ai.provider"].search([("code", "=", "deepseek")])
        self.assertLess(earlier_provider.sequence, later_provider.sequence)
        created_first = self.env["ai.model"].create(
            {"provider_id": later_provider.id, "name": "Kimi hop", "code": "kimi-hop"}
        )
        created_second = self.env["ai.model"].create(
            {"provider_id": earlier_provider.id, "name": "DS hop", "code": "ds-hop"}
        )
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("CREATE TABLE ai_model_fallback_rel (model_id int, fallback_id int)")
        cr.execute(
            "INSERT INTO ai_model_fallback_rel VALUES (%s, %s), (%s, %s), (%s, %s)",
            (
                claude.id,
                created_first.id,
                claude.id,
                created_second.id,
                claude.id,
                claude.id,
            ),
        )
        _load("1.18.0").migrate(cr, "19.0.1.17.0")
        self.env.invalidate_all()

        self.assertEqual(
            claude.fallback_model_ids.ids,
            [created_second.id, created_first.id],
            "hops run in provider order, which here is the reverse of creation "
            "order, and a self-hop is not carried",
        )
        cr.execute("SELECT to_regclass('ai_model_fallback_rel')")
        self.assertIsNone(cr.fetchone()[0])

    def test_providers_tied_on_sequence_keep_their_name_order(self):
        claude = self.env.ref("api_ai.ai_model_claude_sonnet_5")
        moonshot = self.env["ai.provider"].search([("code", "=", "moonshot")])
        groq = self.env["ai.provider"].search([("code", "=", "groq")])
        (moonshot | groq).endpoint_id.write({"sequence": 5})
        by_moonshot = self.env["ai.model"].create(
            {"provider_id": moonshot.id, "name": "A hop", "code": "a-hop"}
        )
        by_groq = self.env["ai.model"].create(
            {"provider_id": groq.id, "name": "Z hop", "code": "z-hop"}
        )
        self.env.flush_all()
        cr = self.env.cr
        cr.execute("CREATE TABLE ai_model_fallback_rel (model_id int, fallback_id int)")
        cr.execute(
            "INSERT INTO ai_model_fallback_rel VALUES (%s, %s), (%s, %s)",
            (claude.id, by_moonshot.id, claude.id, by_groq.id),
        )
        _load("1.18.0").migrate(cr, "19.0.1.17.0")
        self.env.invalidate_all()
        self.assertEqual(
            claude.fallback_model_ids.ids,
            [by_groq.id, by_moonshot.id],
            "the Many2many ordered tied providers by provider name, Groq before "
            "Moonshot, before it looked at the models' own names",
        )

    def test_a_database_without_the_relation_is_left_alone(self):
        _load("1.18.0").migrate(self.env.cr, "19.0.1.17.0")


@tagged("post_install", "-at_install")
class TestExperimentalGeminiRetired(TransactionCase):
    def setUp(self):
        super().setUp()
        self.google = self.env["ai.provider"].search([("code", "=", "gemini")])
        self.current = self.env.ref("api_ai.ai_model_gemini_3_5_flash_lite")
        self.experimental = self.env["ai.model"].create(
            {
                "provider_id": self.google.id,
                "name": "Gemini 2.0 Flash (experimental)",
                "code": "gemini-2.0-flash-exp",
                "has_vision": True,
            }
        )
        self.env["ir.model.data"].create(
            {
                "module": "api_ai",
                "name": "ai_model_gemini_2_0_flash_exp",
                "model": "ai.model",
                "res_id": self.experimental.id,
                "noupdate": True,
            }
        )

    def test_a_provider_still_on_the_seed_moves_and_the_seed_is_archived(self):
        self.google.default_model_id = self.experimental
        _load("1.18.0").migrate(self.env.cr, "19.0.1.17.0")
        self.assertEqual(self.google.default_model_id, self.current)
        self.assertFalse(self.experimental.active)

    def test_an_administrators_default_is_kept(self):
        chosen = self.env["ai.model"].create(
            {"provider_id": self.google.id, "name": "Pro", "code": "gemini-pro-x"}
        )
        self.google.default_model_id = chosen
        _load("1.18.0").migrate(self.env.cr, "19.0.1.17.0")
        self.assertEqual(self.google.default_model_id, chosen)


@tagged("post_install", "-at_install")
class TestProviderChainsCarried(TransactionCase):
    def test_a_provider_chain_becomes_a_hop_between_default_models(self):
        claude = self.env["ai.provider"].search([("code", "=", "claude")])
        openai = self.env["ai.provider"].search([("code", "=", "openai")])
        cr = self.env.cr
        cr.execute(
            "CREATE TABLE ai_provider_fallback_rel (provider_id int, fallback_id int)"
        )
        cr.execute(
            "INSERT INTO ai_provider_fallback_rel VALUES (%s, %s)",
            (claude.id, openai.id),
        )
        _load("1.14.0").migrate(cr, "19.0.1.13.0")
        self.env.invalidate_all()
        self.assertEqual(
            claude.default_model_id.fallback_model_ids, openai.default_model_id
        )
