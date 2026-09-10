from odoo.tests import TransactionCase


class TestActivityPlanTemplateResponsibleOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = cls.env["mail.activity.plan"].create(
            {"name": "Plan", "res_model": "res.partner"}
        )
        cls.type_with_user = cls.env["mail.activity.type"].create(
            {"name": "Call the customer", "default_user_id": cls.env.user.id}
        )
        cls.type_without_user = cls.env["mail.activity.type"].create(
            {"name": "Send the brochure"}
        )

    def _create_template(self, **values):
        return self.env["mail.activity.plan.template"].create(
            {"plan_id": self.plan.id, **values}
        )

    def test_a_type_with_a_default_user_assigns_that_user(self):
        template = self._create_template(activity_type_id=self.type_with_user.id)

        self.assertEqual(template.responsible_type, "other")
        self.assertEqual(template.responsible_id, self.env.user)

    def test_a_type_without_a_default_user_asks_at_launch(self):
        template = self._create_template(activity_type_id=self.type_without_user.id)

        self.assertEqual(template.responsible_type, "on_demand")
        self.assertFalse(template.responsible_id)

    def test_an_explicit_ask_at_launch_wins_over_the_type(self):
        template = self._create_template(
            activity_type_id=self.type_with_user.id, responsible_type="on_demand"
        )

        self.assertEqual(template.responsible_type, "on_demand")
        self.assertFalse(template.responsible_id)
