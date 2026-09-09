import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

EXPRESSION_FIELDS = (
    "body_html",
    "subject",
    "email_from",
    "email_to",
    "email_cc",
    "partner_to",
    "reply_to",
    "scheduled_date",
)

OBJECT_CHAIN = re.compile(r"\bobject((?:\.[a-z_][a-z0-9_]*)+)")
MODEL_LITERAL = re.compile(r"""env\[['"]([a-z_][a-z0-9_.]*)['"]\]""")
HASATTR_GUARD = re.compile(r"hasattr\(\s*object\s*,\s*['\"]([a-z_0-9]+)['\"]")
MEMBERSHIP_GUARD = re.compile(r"['\"]([a-z_0-9]+)['\"]\s+in\s+object\b")


@tagged("mail_tools", "-at_install", "post_install")
class TestMailTemplateReferences(TransactionCase):
    def _shipped_templates(self):
        data = self.env["ir.model.data"].search([("model", "=", "mail.template")])
        return (
            self.env["mail.template"]
            .with_context(active_test=False)
            .browse(data.mapped("res_id"))
            .exists()
        )

    def _expressions(self, template):
        return [str(template[name] or "") for name in EXPRESSION_FIELDS]

    def _broken_hop(self, model, chain):
        for name in chain.strip(".").split("."):
            field = model._fields.get(name)
            if field is None:
                return None if hasattr(type(model), name) else name
            if not field.comodel_name:
                return None
            model = self.env[field.comodel_name]
        return None

    def test_every_shipped_template_names_a_live_model(self):
        broken = []
        for template in self._shipped_templates():
            for body in self._expressions(template):
                broken.extend(
                    f"{template.name} (id {template.id}): env[{name!r}]"
                    for name in sorted(set(MODEL_LITERAL.findall(body)))
                    if name not in self.env
                )
        self.assertFalse(
            broken,
            "mail templates naming a model the registry does not have:\n  "
            + "\n  ".join(broken),
        )

    def test_every_shipped_template_names_a_live_field(self):
        broken = []
        for template in self._shipped_templates():
            model_name = template.model_id.model
            if not model_name or model_name not in self.env:
                continue
            model = self.env[model_name]
            for body in self._expressions(template):
                guarded = set(HASATTR_GUARD.findall(body)) | set(
                    MEMBERSHIP_GUARD.findall(body)
                )
                for chain in sorted(set(OBJECT_CHAIN.findall(body))):
                    name = self._broken_hop(model, chain)
                    if name and name not in guarded:
                        broken.append(
                            f"{template.name} (id {template.id}): "
                            f"object{chain} -- no {name!r}"
                        )
        self.assertFalse(
            broken,
            "mail templates reading a field that does not exist:\n  "
            + "\n  ".join(sorted(set(broken))),
        )

    def test_every_template_model_column_agrees_with_its_model_id(self):
        drifted = [
            f"{template.name} (id {template.id}): "
            f"model={template.model!r} but model_id names "
            f"{template.model_id.model!r}"
            for template in self.env["mail.template"]
            .with_context(active_test=False)
            .search([])
            if template.model != template.model_id.model
        ]
        self.assertFalse(
            drifted,
            "mail templates whose model column never caught up:\n  "
            + "\n  ".join(drifted),
        )
