"""`hasattr(object, 'x') and object.x` names a field an optional module adds.

`mail.template._find_unknown_object_attribute` refused every `object.<name>` the
model lacked, guard or no guard, so a template copied through Python -- where
`install_mode` is not set and `_check_rendering` runs -- was refused for the very
expression `account`'s own invoice template ships (`timesheet_count`, a field only
`sale_timesheet` adds). `l10n_co_dian` copies that template and could not install
without `sale_timesheet`.
"""

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
