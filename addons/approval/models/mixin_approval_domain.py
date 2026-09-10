import ast
import logging

from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class MixinApprovalDomain(models.AbstractModel):
    """Shared parsing and configuration-time checking of a subject domain.

    Both `approval.rule` and `approval.binding` let a user write a domain that
    is evaluated against a source document rather than against the request.
    A domain naming a field nobody has never matches, and a rule or binding
    that never matches reads as "approval was not required" rather than as a
    broken configuration — so the paths are walked against the registry when
    the record is saved, not when a decision depends on them.
    """

    _name = "mixin.approval.domain"
    _description = "Approval Subject Domain"

    def _domain_source_field(self) -> str:
        """Name of the Char field on the concrete model holding the domain."""
        raise NotImplementedError

    def _parse_domain(self) -> Domain | None:
        self.check_singleton()
        raw = self[self._domain_source_field()]
        try:
            return Domain(ast.literal_eval(raw or "[]"))
        except ValueError, SyntaxError, TypeError:
            return None

    def _parse_domain_or_warn(self) -> Domain | None:
        self.check_singleton()
        domain = self._parse_domain()
        if domain is None:
            _logger.warning(
                "%s %s: unparseable subject domain %r, treated as no match.",
                self._name,
                self.id,
                self[self._domain_source_field()],
            )
        return domain

    def _check_domain_against_model(self, model) -> None:
        self.check_singleton()
        domain = self._parse_domain()
        if domain is None:
            raise ValidationError(
                self.env._(
                    "%(name)s has a source domain that is not a valid Python "
                    "literal: %(domain)s",
                    name=self.display_name,
                    domain=self[self._domain_source_field()],
                ),
            )
        for field_path in self._domain_field_paths(domain):
            self._check_field_path(model, field_path)

    def _check_field_path(self, model, field_path: str) -> None:
        self.check_singleton()
        current = model
        for part in field_path.split("."):
            field = current._fields.get(part)
            if field is None:
                raise ValidationError(
                    self.env._(
                        "%(name)s reads %(path)s, but %(model)s has no field %(part)s.",
                        name=self.display_name,
                        path=field_path,
                        model=current._name,
                        part=part,
                    ),
                )
            if not field.relational:
                break
            current = self.env[field.comodel_name]

    @api.model
    def _domain_field_paths(self, domain) -> set[str]:
        return {condition.field_expr for condition in domain.iter_conditions()}
