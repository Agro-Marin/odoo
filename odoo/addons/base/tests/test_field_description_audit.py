from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestFieldsGetAnswersForEveryModel(TransactionCase):
    def test_fields_get_never_raises_for_a_registered_model(self):
        failures = []
        for model_name in sorted(self.env.registry):
            model = self.env[model_name]
            try:
                model.fields_get()
            except Exception as error:
                failures.append(f"{model_name}: {type(error).__name__}: {error}")
        self.assertEqual(
            failures,
            [],
            "fields_get() is public API and must answer for every registered "
            "model, abstract ones included",
        )


@tagged("post_install", "-at_install")
class TestDescriptionProbesAreBestEffort(TransactionCase):
    def _get_field_not_backed_by_a_column(self, model):
        for field in model._fields.values():
            if not field.is_column:
                return field.name
        self.skipTest(f"{model._name} has no field outside its table")
        return None

    def test_a_model_that_cannot_build_a_query_still_describes_its_fields(self):
        model = self.env["res.partner"]
        fname = self._get_field_not_backed_by_a_column(model)

        def explode(*args, **kwargs):
            raise NotImplementedError("override _get_fields_select()")

        with patch.object(type(model), "_as_query", explode):
            description = model.fields_get(
                [fname], attributes=["sortable", "groupable"]
            )

        self.assertIn(fname, description)
        self.assertFalse(description[fname]["sortable"])
        self.assertFalse(description[fname]["groupable"])

    def test_a_query_that_raises_valueerror_is_answered_the_same_way(self):
        model = self.env["res.partner"]
        fname = self._get_field_not_backed_by_a_column(model)

        def explode(*args, **kwargs):
            raise ValueError("'' invalid for SQL.identifier()")

        with patch.object(type(model), "_as_query", explode):
            description = model.fields_get(
                [fname], attributes=["sortable", "groupable"]
            )

        self.assertFalse(description[fname]["sortable"])
        self.assertFalse(description[fname]["groupable"])
