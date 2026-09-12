import ast
import logging

from odoo import api, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

from . import approval_trace as trace

_logger = logging.getLogger(__name__)


class MixinApprovalDomain(models.AbstractModel):
    _name = "mixin.approval.domain"
    _description = "Approval Subject Domain"

    def _domain_source_field(self) -> str:
        raise NotImplementedError

    def _parse_domain(self, field_name: str | None = None) -> Domain | None:
        self.check_singleton()
        field_name = field_name or self._domain_source_field()
        raw = self[field_name]
        try:
            return Domain(ast.literal_eval(raw or "[]"))
        except ValueError, SyntaxError, TypeError:
            trace.DEGRADED.note(
                "domain_unparseable", record=self, field=field_name, raw=raw
            )
            return None

    def _parse_domain_or_warn(self, field_name: str | None = None) -> Domain | None:
        self.check_singleton()
        field_name = field_name or self._domain_source_field()
        domain = self._parse_domain(field_name)
        if domain is None:
            trace.REFUSAL.event(
                "unparseable_domain",
                record=self,
                field=field_name,
            )
            _logger.warning(
                "%s %s: unparseable domain %r in %s, treated as no match.",
                self._name,
                self.id,
                self[field_name],
                field_name,
            )
        return domain

    def _check_domain_against_model(self, model, field_name: str | None = None) -> None:
        self.check_singleton()
        field_name = field_name or self._domain_source_field()
        domain = self._parse_domain(field_name)
        if domain is None:
            trace.REFUSAL.event("domain_not_a_literal", record=self, field=field_name)
            raise ValidationError(
                self.env._(
                    "%(name)s has a source domain that is not a valid Python "
                    "literal: %(domain)s",
                    name=self.display_name,
                    domain=self[field_name],
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
                trace.REFUSAL.event(
                    "unknown_field_path",
                    record=self,
                    path=field_path,
                    on=current._name,
                    part=part,
                )
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
