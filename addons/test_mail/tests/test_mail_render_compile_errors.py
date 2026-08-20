"""A template QWeb cannot compile is refused by the file's error policy.

`_has_unsafe_expression_template_qweb` runs `ir.qweb._generate_code` to find out
whether a template holds anything an evaluator would have to run. It caught
`PermissionError` -- the answer "yes, unsafe" -- and nothing else, so any *other*
failure of the compiler escaped the predicate. It escapes it from outside the
`try` in `_render_template_qweb`, which means it also escapes `_check_render_error`,
the single error policy the module owns: the caller saw a bare `ValueError` where
every other broken template yields a `UserError` naming the template and the model.

The trigger is a parser mismatch, not a contrived input: `html.fragment_fromstring`
is the permissive HTML parser and accepts attribute names `etree.Element` rejects,
so `<p t-out="object.name" a&#34;b="1"/>` parses here and dies in QWeb's codegen
with `ValueError: Invalid attribute name 'a&#34;b'`.

`mail.template._compile_dynamic_fields` wraps the same `_generate_code` call in
`except (UserError, ValueError, SyntaxError)`, so an administrator saving such a
body got the friendly `ValidationError` all along. The mixin's copy did not, which
is why the outcome depended on who was saving: a member of the template-editor
group short-circuits `_check_access_right_dynamic_template` and reached that
`ValidationError`; everyone else reached the predicate and got the traceback.
"""

from markupsafe import Markup

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged, users

from odoo.addons.mail.tests import common

#: Parses as an element carrying `t-out` plus an attribute named `a&#34;b`.
UNCOMPILABLE = '<p t-out="object.name" a&#34;b="1"/>'


@tagged("mail_render", "post_install", "-at_install")
class TestUncompilableTemplate(common.MailCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = "mail.test.track"
        cls.record = cls.env[cls.model].create(
            {"name": "Rec", "email_from": "rec@test.example.com"}
        )
        cls.plain_user = cls.env["res.users"].create(
            {
                "name": "Plain",
                "login": "render_compile_plain",
                "email": "plain@test.example.com",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def test_the_predicate_answers_unsafe_rather_than_raising(self):
        """Cannot compile is cannot establish safe, so the answer is "unsafe"."""
        self.assertTrue(
            self.env["mixin.mail.render"]._has_unsafe_expression_template_qweb(
                UNCOMPILABLE, self.model
            )
        )

    def test_rendering_one_reports_it_as_a_render_failure(self):
        """The bare `ValueError` used to reach the caller from here."""
        with self.assertRaises(UserError):
            self.env["mixin.mail.render"]._render_template(
                UNCOMPILABLE, self.model, [self.record.id], engine="qweb"
            )

    def test_an_editor_may_not_save_one(self):
        with self.assertRaises(ValidationError):
            self.env["mail.template"].create(
                {
                    "name": "uncompilable",
                    "model_id": self.env["ir.model"]._get(self.model).id,
                    "body_html": Markup(UNCOMPILABLE),
                }
            )

    @users("render_compile_plain")
    def test_a_non_editor_may_not_save_one_either(self):
        """Same input, same refusal shape -- a domain error, not a traceback.

        The two users still get *different* domain errors, because they are
        refused by different guards: the editor by `mail.template._check_rendering`,
        which knows the body will not compile, and the non-editor by
        `_check_access_right_dynamic_template`, which only knows the placeholders
        were never established as safe. Both refuse the save, which is what
        fail-closed means here.
        """
        with self.assertRaises((AccessError, ValidationError)):
            self.env["mail.template"].create(
                {
                    "name": "uncompilable",
                    "model_id": self.env["ir.model"]._get(self.model).id,
                    "body_html": Markup(UNCOMPILABLE),
                }
            )
