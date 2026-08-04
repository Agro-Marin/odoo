"""Regression tests for the twelfth mail hardening audit.

Each test pins a defect reproduced end to end before being fixed, so a refactor
cannot silently reintroduce it.
"""

import inspect
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.tests.common import MailCommon


@tagged("-at_install", "post_install", "mail_hardening_v12")
class TestRestrictedRenderRoots(MailCommon):
    """The restricted (regex) renderers must read what the allow-list says: it is
    the security boundary for non-``group_mail_template_editor`` users, so a
    reviewed entry must describe what is actually read."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["res.partner"].create(
            {"name": "RECORD NAME", "email": "rec@test.example.com"}
        )

    def _patch_allowed(self, expressions):
        return patch.object(
            type(self.env["res.partner"]),
            "mail_allowed_qweb_expressions",
            lambda records: expressions,
        )

    def test_qweb_regex_resolves_declared_root(self):
        """The defect: ``user.name`` rendered the record's name."""
        with self._patch_allowed(("object.name", "user.name")):
            rendered = self.env["mail.render.mixin"]._render_template_qweb_regex(
                '<p t-out="user.name">x</p>', "res.partner", self.record.ids
            )
            self.assertIn(self.env.user.name, rendered[self.record.id])
            self.assertNotIn("RECORD NAME", rendered[self.record.id])

            rendered = self.env["mail.render.mixin"]._render_template_qweb_regex(
                '<p t-out="object.name">x</p>', "res.partner", self.record.ids
            )
            self.assertIn("RECORD NAME", rendered[self.record.id])

    def test_inline_regex_resolves_declared_root(self):
        with self._patch_allowed(("object.name", "user.name")):
            rendered = self.env[
                "mail.render.mixin"
            ]._render_template_inline_template_regex(
                "{{ user.name }}", "res.partner", self.record.ids
            )
            self.assertEqual(rendered[self.record.id], self.env.user.name)

            rendered = self.env[
                "mail.render.mixin"
            ]._render_template_inline_template_regex(
                "{{ object.name }}", "res.partner", self.record.ids
            )
            self.assertEqual(rendered[self.record.id], "RECORD NAME")

    def test_unknown_root_is_refused_not_guessed(self):
        """An allow-listed but unresolvable root must raise, not silently read
        the record."""
        with self._patch_allowed(("ctx.company_id",)):
            with self.assertRaises(SyntaxError):
                self.env["mail.render.mixin"]._render_template_inline_template_regex(
                    "{{ ctx.company_id }}", "res.partner", self.record.ids
                )


@tagged("-at_install", "post_install", "mail_hardening_v12")
class TestPrepareMessageDataContract(MailCommon):
    """``from_create`` governs portal author attribution: keep it declared."""

    def test_from_create_is_declared_not_kwargs_borne(self):
        signature = inspect.signature(ThreadController._prepare_message_data)
        self.assertIn(
            "from_create",
            signature.parameters,
            "from_create must be an explicit parameter: portal keys anonymous "
            "author attribution on it, so a typo must fail loudly, not degrade "
            "to a falsy kwargs lookup",
        )

    def test_message_type_defaulted_on_create_only(self):
        thread = self.env["res.partner"].create(
            {"name": "T", "email": "t@test.example.com"}
        )
        controller = ThreadController()
        created = controller._prepare_message_data({}, thread=thread, from_create=True)
        self.assertEqual(created.get("message_type"), "comment")
        edited = controller._prepare_message_data({}, thread=thread, from_create=False)
        self.assertNotIn(
            "message_type",
            edited,
            "the edit path must not inject a message_type it does not own",
        )
