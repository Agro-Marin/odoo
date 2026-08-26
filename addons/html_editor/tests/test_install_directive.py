from odoo.tests.common import TransactionCase


class TestInstallDirectiveIsDecidedPerUser(TransactionCase):
    """`t-install` must decide who sees it at render time, not at compile time.

    `_generate_code_cached` is an ormcache keyed on
    `(ref, _template_cache_signature())`, and that signature carries no uid.
    Reading `self.env.user.has_group('base.group_system')` while compiling
    therefore let whichever user warmed the cache decide for everyone: with an
    administrator first a plain internal user was served the module's name, id
    and display name; with a plain user first the administrator never saw the
    placeholder. Both orders are asserted, because a fix that only reorders the
    compile would pass one of them.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module = cls.env["ir.module.module"].search(
            [("state", "!=", "installed")], limit=1
        )
        if not module:
            cls.skipTest(cls, "no uninstalled module to advertise")
        cls.module = module
        cls.view = cls.env["ir.ui.view"].create(
            {
                "name": "install directive probe",
                "type": "qweb",
                "key": "html_editor.install_probe",
                "arch_db": (
                    '<t t-name="html_editor.install_probe"><div>'
                    f'<t t-install="{module.name}" string="Snip"/>'
                    "</div></t>"
                ),
            }
        )
        cls.env["ir.model.data"].create(
            {
                "module": "html_editor",
                "name": "install_probe",
                "model": "ir.ui.view",
                "res_id": cls.view.id,
            }
        )
        cls.system = cls.env.ref("base.user_root")
        cls.internal = cls.env["res.users"].create(
            {
                "login": "install_directive_probe",
                "name": "install directive probe",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def _sees_placeholder(self, user):
        rendered = str(self.env["ir.qweb"].with_user(user)._render(self.view.id))
        return 'data-oe-type="snippet"' in rendered

    def test_the_first_renderer_does_not_decide_for_the_second(self):
        self.assertTrue(self.system.has_group("base.group_system"))
        self.assertFalse(self.internal.has_group("base.group_system"))

        for first, second in (
            (self.system, self.internal),
            (self.internal, self.system),
        ):
            with self.subTest(first=first.login):
                self.env.registry.clear_cache("templates")
                self._sees_placeholder(first)
                self.assertTrue(
                    self._sees_placeholder(self.system),
                    "a system user lost the placeholder to a warm cache",
                )
                self.assertFalse(
                    self._sees_placeholder(self.internal),
                    "a non-system user was served the module id and name",
                )
                del second
