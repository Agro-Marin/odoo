import ast
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .ir_access import PREDICATE_BINDS as BINDS
from .ir_access import domain_group_tests


class IrAccessPredicate(models.Model):
    _name = "ir.access.predicate"
    _description = "Access Predicate"
    _order = "name"

    name = fields.Char(
        required=True,
        help="How rows name it, module-qualified: approval.approver_of.",
    )
    description = fields.Char(
        translate=True,
        help="What it says in an explanation of access: you are deciding its approval.",
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        ondelete="cascade",
        help="The model it is written for; empty for a predicate any model can use.",
    )
    template = fields.Char(
        help="A domain reading P (the principal: P.user, P.partner, "
        "P.commercial_partner, P.companies, P.employees, P.teams, P.units) and "
        "args (the row's arguments).",
    )
    method = fields.Char(
        help="Instead of a template, a method of the model taking the principal's "
        "binds and the row's arguments and answering a domain; its name starts "
        "with _access_predicate_.",
    )

    _name_unique = models.Constraint("UNIQUE (name)", "A predicate's name is unique.")
    _template_or_method = models.Constraint(
        "CHECK ((template IS NULL) != (method IS NULL))",
        "A predicate is a template or a method, not both.",
    )

    @api.constrains("template", "method", "model_id")
    def _check_definition(self) -> None:
        for predicate in self:
            if predicate.method:
                if not predicate.method.startswith("_access_predicate_"):
                    raise ValidationError(
                        self.env._(
                            "The method of predicate %(name)s must start with "
                            "_access_predicate_.",
                            name=predicate.name,
                        )
                    )
                model_name = predicate.model_id.model
                if not model_name or not callable(
                    getattr(self.env[model_name], predicate.method, None)
                ):
                    raise ValidationError(
                        self.env._(
                            "Predicate %(name)s names %(method)s, which its model "
                            "does not define.",
                            name=predicate.name,
                            method=predicate.method,
                        )
                    )
                continue
            predicate._check_template()

    def _check_template(self) -> None:
        try:
            tree = ast.parse(self.template, mode="eval")
        except SyntaxError as e:
            raise ValidationError(
                self.env._("Predicate %(name)s: %(error)s", name=self.name, error=e)
            ) from None
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        if names - {"P", "args", "True", "False", "None"}:
            raise ValidationError(
                self.env._(
                    "Predicate %(name)s reads %(names)s; a template reads only P "
                    "and args.",
                    name=self.name,
                    names=", ".join(sorted(names - {"P", "args"})),
                )
            )
        read = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "P"
        }
        if read - BINDS:
            raise ValidationError(
                self.env._(
                    "Predicate %(name)s reads P.%(binds)s; the principal offers "
                    "%(offered)s.",
                    name=self.name,
                    binds=", P.".join(sorted(read - BINDS)),
                    offered=", ".join(sorted(BINDS)),
                )
            )
        if tests := domain_group_tests(self.template):
            raise ValidationError(
                self.env._(
                    "Predicate %(name)s tests the user's groups (%(tests)s); "
                    "membership is what an access row's group states.",
                    name=self.name,
                    tests=", ".join(tests),
                )
            )

    def write(self, vals: dict[str, Any]) -> bool:
        result = super().write(vals)
        self.env["ir.access"]._clear_access_caches()
        return result
