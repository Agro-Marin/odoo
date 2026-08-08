"""Regression guards for the ``portal.share`` wizard.

The wizard is opened with ``res_model`` / ``res_id`` taken straight from the
``active_model`` / ``active_id`` context (see :meth:`PortalShare.default_get`),
and ``res_model`` is a plain ``Char`` the wizard's own ACL lets a partner
manager write. Nothing in that path guarantees the target inherits
``portal.mixin`` -- but ``resource_ref`` is a ``Reference`` whose selection is
restricted to concrete ``portal.mixin`` models, so assigning anything else to it
raises ``ValueError`` from the field itself.

``_compute_share_link`` and ``_compute_access_warning`` already route through
``_get_portal_record()`` and degrade to ``False``; ``_compute_resource_ref`` did
not, so any read of that field raised instead.

Scope, verified rather than assumed: ``resource_ref`` is **not** in the wizard's
form view, so opening the dialog never touched it -- the form comes up with an
empty link and no error. The raise reached the user on **Send**, via
``_send_public_link`` / ``_post_share_email``, as an HTTP 500.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestPortalShareTarget(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.recipient = cls.env["res.partner"].create(
            {"name": "Share Recipient", "email": "share.recipient@example.com"}
        )
        # res.partner is a mail.thread but NOT a portal.mixin: it has no
        # access_url / access_token, so it can never be shared this way.
        cls.non_portal_record = cls.env["res.partner"].create({"name": "Share Target"})

    def _wizard_on(self, res_model, res_id):
        return self.env["portal.share"].create(
            {
                "res_model": res_model,
                "res_id": res_id,
                "partner_ids": [(6, 0, self.recipient.ids)],
            }
        )

    def test_reading_a_non_portal_target_does_not_raise(self):
        """Reading the field must degrade, not raise, on a non-shareable model.

        Not the dialog-open path (the form view omits ``resource_ref``); this
        covers overrides, exports and any downstream read of the field.
        """
        wizard = self._wizard_on("res.partner", self.non_portal_record.id)
        # read() is what the form view does; it must survive.
        values = wizard.read(["resource_ref", "share_link", "access_warning"])[0]
        self.assertFalse(
            values["resource_ref"],
            "a model outside the portal.mixin hierarchy has no shareable "
            "reference, so the field must come back empty rather than raise",
        )
        self.assertFalse(values["share_link"])

    def test_unknown_model_does_not_raise(self):
        """A stale/unknown ``res_model`` must degrade, not raise."""
        wizard = self._wizard_on("no.such.model", 1)
        values = wizard.read(["resource_ref", "share_link"])[0]
        self.assertFalse(values["resource_ref"])
        self.assertFalse(values["share_link"])

    def test_missing_res_id_does_not_raise(self):
        """No target id: the reference is simply empty."""
        wizard = self._wizard_on("res.partner", 0)
        self.assertFalse(wizard.resource_ref)
        self.assertFalse(wizard.share_link)

    def test_sending_to_a_non_portal_target_is_refused_cleanly(self):
        """``action_send_mail`` must not post against an unshareable record.

        It used to reach ``self.resource_ref`` directly, so the same
        ``ValueError`` surfaced from the Send button. Nothing is shareable here,
        so nothing must be sent.
        """
        wizard = self._wizard_on("res.partner", self.non_portal_record.id)
        messages_before = self.env["mail.message"].search_count([])
        with self.assertRaises(UserError):
            wizard.action_send_mail()
        self.assertEqual(
            self.env["mail.message"].search_count([]),
            messages_before,
            "no share mail may be posted for an unshareable target",
        )

    def test_default_get_from_a_non_portal_active_model(self):
        """The UI entry point seeds res_model from the context, unchecked."""
        wizard = (
            self.env["portal.share"]
            .with_context(
                active_model="res.partner", active_id=self.non_portal_record.id
            )
            .create({"partner_ids": [(6, 0, self.recipient.ids)]})
        )
        self.assertEqual(wizard.res_model, "res.partner")
        # Must be readable -- this is the exact sequence the Share dialog runs.
        self.assertFalse(wizard.read(["resource_ref"])[0]["resource_ref"])
