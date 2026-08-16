"""Regression tests for the 2026-08-15 mail.template audit."""

from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("mail_template", "post_install", "-at_install")
class TestMailTemplateAudit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env["ir.model"]._get("mail.test.gateway.groups")
        cls.Record = cls.env["mail.test.gateway.groups"]
        cls.MailTemplate = cls.env["mail.template"]

    # ---------------------------------------------------------------- 1.1
    def test_category_compute_and_search_agree_on_export_xmlid(self):
        """A record exported with external IDs must not land in two categories."""
        template = self.MailTemplate.create(
            {
                "name": "audit export",
                "model_id": self.model.id,
                "description": "has a description",
                "active": True,
            }
        )
        self.env["ir.model.data"].create(
            {
                "module": "__export__",
                "name": f"mail_template_{template.id}",
                "model": "mail.template",
                "res_id": template.id,
            }
        )
        self.env.invalidate_all()
        computed = template.template_category
        found_in = {
            category
            for category in ("base_template", "hidden_template", "custom_template")
            if template
            in self.MailTemplate.with_context(active_test=False).search(
                [("template_category", "in", [category])]
            )
        }
        self.assertEqual(
            found_in,
            {computed},
            f"compute says {computed!r} but search files it under {found_in!r}",
        )

    # ---------------------------------------------------------------- 1.2
    def test_copy_does_not_mutate_the_callers_default(self):
        template = self.MailTemplate.create(
            {
                "name": "audit copy",
                "model_id": self.model.id,
            }
        )
        default = {"name": "renamed"}
        template.copy(default=default)
        self.assertEqual(default, {"name": "renamed"})

    def test_copy_with_a_reused_default_keeps_copying_attachments(self):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "a.txt",
                "datas": "Zm9v",
                "res_model": "mail.template",
            }
        )
        templates = self.MailTemplate.create(
            [
                {
                    "name": f"audit reuse {i}",
                    "model_id": self.model.id,
                    "attachment_ids": [(4, attachment.copy().id)],
                }
                for i in range(2)
            ]
        )
        default = {"user_id": self.env.user.id}
        copies = self.env["mail.template"]
        for template in templates:
            copies |= template.copy(default=default)
        self.assertEqual(
            [len(c.attachment_ids) for c in copies],
            [1, 1],
            "the second copy lost its attachments because copy() wrote "
            "attachment_ids=False into the caller's dict",
        )

    # ---------------------------------------------------------------- 1.3
    def test_parse_partner_to_rejects_non_ids(self):
        for partner_to, expected in [
            ("True", []),
            ("[True]", []),
            ("1,True", [1]),
            ("1.9", []),
            ("[[1]]", []),
        ]:
            with self.subTest(partner_to=partner_to):
                self.assertEqual(
                    self.MailTemplate._parse_partner_to(partner_to), expected
                )

    def test_parse_partner_to_survives_a_non_string(self):
        self.assertEqual(self.MailTemplate._parse_partner_to(12), [12])
        self.assertEqual(self.MailTemplate._parse_partner_to(None), [])

    # ---------------------------------------------------------------- 1.5
    def test_print_report_name_evaluating_to_false(self):
        """An unset Char makes print_report_name evaluate to False, not to a str."""
        record = self.Record.create({"name": "audit report"})
        self.assertFalse(record.email_from)
        report = self.env["ir.actions.report"].create(
            {
                "name": "audit",
                "model": "mail.test.gateway.groups",
                "report_type": "qweb-pdf",
                "report_name": "test_mail.audit_report",
                "print_report_name": "object.email_from",
            }
        )
        template = self.MailTemplate.create(
            {
                "name": "audit report",
                "model_id": self.model.id,
                "report_template_ids": [(6, 0, report.ids)],
            }
        )
        MailTemplate = self.env.registry["mail.template"]
        with patch.object(
            MailTemplate,
            "_render_report_per_record",
            lambda self, report, res_ids: dict.fromkeys(res_ids, (b"body", "pdf")),
        ):
            values = template._prepare_attachment_vals(
                record.ids, {"report_template_ids"}
            )
        name, _content = values[record.id]["attachments"][0]
        self.assertTrue(name.endswith(".pdf"), name)
        self.assertIn(report.name, name)

    def test_report_name_falls_back_per_report(self):
        """Two reports without print_report_name must not produce one name twice."""
        record = self.Record.create({"name": "audit names"})
        reports = self.env["ir.actions.report"].create(
            [
                {
                    "name": f"audit report {i}",
                    "model": "mail.test.gateway.groups",
                    "report_type": "qweb-pdf",
                    "report_name": f"test_mail.audit_{i}",
                }
                for i in range(2)
            ]
        )
        template = self.MailTemplate.create(
            {
                "name": "audit names",
                "model_id": self.model.id,
                "report_template_ids": [(6, 0, reports.ids)],
            }
        )
        MailTemplate = self.env.registry["mail.template"]
        with patch.object(
            MailTemplate,
            "_render_report_per_record",
            lambda self, report, res_ids: dict.fromkeys(res_ids, (b"body", "pdf")),
        ):
            values = template._prepare_attachment_vals(
                record.ids, {"report_template_ids"}
            )
        names = [name for name, _content in values[record.id]["attachments"]]
        self.assertEqual(len(set(names)), 2, names)

    # ---------------------------------------------------------------- 1.6
    def test_generate_attachments_preserves_caller_supplied_values(self):
        record = self.Record.create({"name": "audit clobber"})
        template = self.MailTemplate.create(
            {
                "name": "audit clobber",
                "model_id": self.model.id,
            }
        )
        render_results = {record.id: {"attachments": [("keep.pdf", b"x")]}}
        out = template._prepare_attachment_vals(
            record.ids, {"report_template_ids"}, render_results=render_results
        )
        self.assertEqual(out[record.id]["attachments"], [("keep.pdf", b"x")])

    # ---------------------------------------------------------------- 1.8
    def test_template_without_model_fails_with_a_user_error(self):
        template = self.MailTemplate.create({"name": "audit no model"})
        with self.assertRaises(UserError):
            template.send_mail_batch([1])

    # ---------------------------------------------------------------- 2.1
    # The probe still samples `search([], limit=1)`, so it stays silent when the model
    # has no rows. Rendering against browse(0) instead would close that, and was tried:
    # it rejects `{{ object.event_id.event_date_range }}` — an expression `event` ships
    # — because every Many2one resolves empty and that compute calls ensure_one(). The
    # audit records the remaining gap as open. What the probe must not do is give two
    # users two answers, which is what these two pin.
    def _make_restricted_user(self):
        group = self.env.ref("base.group_user")
        user = self.env["res.users"].create(
            {
                "name": "audit acl",
                "login": "audit_acl",
                "group_ids": [
                    (
                        6,
                        0,
                        (group | self.env.ref("mail.group_mail_template_editor")).ids,
                    )
                ],
            }
        )
        records = self.Record.create([{"name": f"audit acl {i}"} for i in range(3)])
        self.env["ir.rule"].create(
            {
                "name": "audit acl",
                "model_id": self.model.id,
                "domain_force": f"[('id', '=', {records[-1].id})]",
                "groups": [(4, group.id)],
                "perm_read": True,
            }
        )
        self.env.invalidate_all()
        self.assertNotEqual(
            self.Record.search([], limit=1),
            self.Record.with_user(user).search([], limit=1),
            "the two users must disagree about records for this to mean anything",
        )
        return user

    def test_validation_verdict_does_not_depend_on_the_saving_user(self):
        """Whether a template renders is a property of the template."""
        user = self._make_restricted_user()
        for env_user, label in ((self.env.user, "admin"), (user, "restricted")):
            with self.subTest(user=label):
                MailTemplate = self.MailTemplate.with_user(env_user)
                template = MailTemplate.create(
                    {
                        "name": f"audit acl {label}",
                        "model_id": self.model.id,
                        "subject": "{{ object.name }}",
                    }
                )
                self.assertTrue(template.id)
                with self.assertRaises(ValidationError):
                    template.write({"subject": "{{ object.field_that_is_missing }}"})

    def test_validation_does_not_depend_on_record_read_access(self):
        """A field the saving user cannot read must not fail the save."""
        user = self._make_restricted_user()
        self.env["ir.rule"].create(
            {
                "name": "audit acl none",
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "domain_force": "[(0, '=', 1)]",
                "groups": [(4, self.env.ref("base.group_user").id)],
                "perm_read": True,
            }
        )
        self.env.invalidate_all()
        template = self.MailTemplate.with_user(user).create(
            {
                "name": "audit acl unreadable",
                "model_id": self.model.id,
                "subject": "{{ object.customer_id.name }}",
            }
        )
        self.assertTrue(template.id)

    # ---------------------------------------------------------------- 2.2
    def test_access_error_during_render_stays_an_access_error(self):
        self.Record.create({"name": "audit access"})
        MailRenderMixin = self.env.registry["mail.render.mixin"]

        def refuse(self, field, res_ids, **kwargs):
            raise AccessError("refused")

        with patch.object(MailRenderMixin, "_render_field", refuse):
            with self.assertRaises(AccessError):
                self.MailTemplate.create(
                    {
                        "name": "audit access",
                        "model_id": self.model.id,
                        "subject": "{{ object.name }}",
                    }
                )

    # ---------------------------------------------------------------- 2.3
    def test_layout_is_rendered_in_the_same_language_as_the_body(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        partner = self.env["res.partner"].create(
            {
                "name": "audit fr",
                "email": "fr@example.com",
                "lang": "fr_FR",
            }
        )
        record = self.Record.create(
            {
                "name": "audit lang",
                "email_from": "fr@example.com",
                "customer_id": partner.id,
            }
        )
        template = self.MailTemplate.create(
            {
                "name": "audit lang",
                "model_id": self.model.id,
                "lang": False,
                "subject": "s",
                "body_html": "<p>b</p>",
                "use_default_to": True,
                "email_layout_xmlid": "mail.mail_notification_light",
            }
        )
        seen = {"body": set(), "layout": set()}
        MailRenderMixin = self.env.registry["mail.render.mixin"]
        render_template = MailRenderMixin._render_template
        encapsulate = MailRenderMixin._render_encapsulate

        def spy_body(self, src, model, res_ids, **kwargs):
            seen["body"].add(self.env.context.get("lang"))
            return render_template(self, src, model, res_ids, **kwargs)

        def spy_layout(self, xmlid, html, **kwargs):
            seen["layout"].add(self.env.context.get("lang"))
            return encapsulate(self, xmlid, html, **kwargs)

        with (
            patch.object(MailRenderMixin, "_render_template", spy_body),
            patch.object(MailRenderMixin, "_render_encapsulate", spy_layout),
        ):
            template.send_mail_batch(record.ids)
        self.assertEqual(
            seen["layout"],
            seen["body"],
            "body and notification layout were rendered in different languages",
        )

    # ---------------------------------------------------------------- 2.4
    def test_partner_ids_does_not_leak_onto_the_message(self):
        partner = self.env["res.partner"].create(
            {
                "name": "audit leak",
                "email": "leak@example.com",
            }
        )
        record = self.Record.create({"name": "audit leak"})
        template = self.MailTemplate.create(
            {
                "name": "audit leak",
                "model_id": self.model.id,
                "use_default_to": False,
                "partner_to": str(partner.id),
                "subject": "s",
                "body_html": "<p>b</p>",
            }
        )
        mail = template.send_mail_batch(record.ids)
        self.assertEqual(mail.recipient_ids, partner)
        self.assertFalse(
            mail.mail_message_id.partner_ids,
            "the undeclared partner_ids key reached mail.message",
        )
