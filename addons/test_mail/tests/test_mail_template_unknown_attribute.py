from markupsafe import Markup

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.mail.tests import common


@tagged("mail_render", "post_install", "-at_install")
class TestUnknownObjectAttribute(common.MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_id = cls.env["ir.model"]._get("mail.test.track").id

    def _create(self, body):
        return self.env["mail.template"].create(
            {"name": "probe", "model_id": self.model_id, "body_html": Markup(body)}
        )

    def test_an_unguarded_unknown_attribute_is_refused(self):
        with self.assertRaises(ValidationError):
            self._create('<p t-out="object.no_such_field"/>')

    def test_a_hasattr_guarded_unknown_attribute_is_accepted(self):
        template = self._create(
            "<t t-if=\"hasattr(object, 'no_such_field') and object.no_such_field\">"
            '<p t-out="object.no_such_field"/></t>'
        )
        self.assertTrue(template.exists())

    def test_the_guard_covers_only_the_name_it_names(self):
        with self.assertRaises(ValidationError):
            self._create(
                "<t t-if=\"hasattr(object, 'no_such_field')\">"
                '<p t-out="object.other_missing_field"/></t>'
            )

    def test_a_guard_on_a_nested_chain_is_honoured(self):
        template = self._create(
            "<t t-if=\"hasattr(object.create_uid, 'no_such_field')\">"
            '<p t-out="object.create_uid.no_such_field"/></t>'
        )
        self.assertTrue(template.exists())
