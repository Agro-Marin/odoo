import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.api_ai.tools.claude_sdk import _resolve_work_dir, get_claude_api_token


@tagged("post_install", "-at_install")
class TestClaudeCredentialLookup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ.setdefault("ODOO_API_ENCRYPTION_KEY", Fernet.generate_key().decode())
        cls.service = cls.env["api.endpoint.outbound"].search(
            [("code", "=", "claude")], limit=1
        )

    def _make_credential(self, value="sk-test", company=None):
        category = self.env.ref("credential.credential_category_api_key")
        return self.env["credential.credential"].create(
            {
                "name": "Test Claude Key",
                "category_id": category.id,
                "endpoint_id": self.service.id,
                "company_id": (company or self.env.company).id,
                "api_key": value,
            }
        )

    def test_the_service_record_exists(self):
        self.assertTrue(self.service, "api_ai must seed the claude service")

    def test_get_token_returns_the_key_for_this_company(self):
        self._make_credential("sk-test")
        self.assertEqual(get_claude_api_token(self.env), "sk-test")

    def test_get_token_raises_when_nothing_is_configured(self):
        with self.assertRaises(UserError):
            get_claude_api_token(self.env)

    def test_get_token_raises_when_the_credential_carries_no_key(self):
        self._make_credential("sk-test").write({"credential_value_encrypted": False})
        with self.assertRaises(UserError):
            get_claude_api_token(self.env)

    def test_another_companys_credential_is_not_used(self):
        other = self.env["res.company"].create({"name": "Second Co"})
        self._make_credential("sk-other", company=other)

        with self.assertRaises(UserError):
            get_claude_api_token(self.env)

        env_other = self.env(
            context=dict(self.env.context, allowed_company_ids=[other.id])
        )
        self.assertEqual(get_claude_api_token(env_other), "sk-other")


@tagged("post_install", "-at_install")
class TestResolveWorkDir(TransactionCase):
    def setUp(self):
        super().setUp()
        self.base = Path(tempfile.mkdtemp(prefix="api_ai_claude_base_"))
        self.addCleanup(self._rmtree, self.base)

    def _rmtree(self, path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def test_a_caller_supplied_base_is_honoured(self):
        resolved = _resolve_work_dir(self.env, "my_module", base_dir=str(self.base))
        self.assertEqual(resolved, (self.base / "my_module").resolve())
        self.assertTrue(resolved.is_dir())

    def test_absolute_work_dir_is_refused(self):
        with self.assertRaises(UserError):
            _resolve_work_dir(self.env, "/etc", base_dir=str(self.base))

    def test_traversal_out_of_the_base_is_refused(self):
        for escape in ("../outside", "a/../../outside", "../../../../etc"):
            with self.assertRaises(UserError, msg=escape):
                _resolve_work_dir(self.env, escape, base_dir=str(self.base))

    def test_the_legacy_parameter_is_still_read(self):
        legacy = self.base / "legacy"
        self.env["ir.config_parameter"].sudo().set_param(
            "ai_claude.base_workdir", str(legacy)
        )
        resolved = _resolve_work_dir(self.env, "mod")
        self.assertEqual(resolved, (legacy / "mod").resolve())

    def test_the_new_parameter_wins_over_the_legacy_one(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ai_claude.base_workdir", str(self.base / "legacy"))
        params.set_param("api_ai.claude_workdir", str(self.base / "current"))
        resolved = _resolve_work_dir(self.env, "mod")
        self.assertEqual(resolved, (self.base / "current" / "mod").resolve())
