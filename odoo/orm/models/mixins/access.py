import functools
import logging
import typing
from collections import defaultdict
from operator import itemgetter
from typing import Self

from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import unquote
from odoo.tools.translate import LazyTranslate, _

from ... import decorators as api
from ...domain import Domain
from ...helpers import to_record_ids
from ...primitives import NO_ACCESS
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator

    from ...fields import Field

_lt = LazyTranslate("base")

_logger = logging.getLogger("odoo.models")


class AccessMixin(_ModelStubs):
    __slots__ = ()

    def _has_field_access(
        self, field: Field, operation: typing.Literal["read", "write"]
    ) -> bool:
        if not field.groups or self.env.su:
            return True
        if field.groups == NO_ACCESS:
            return False
        return self.env.user.has_groups(field.groups)

    @api.model
    def _check_field_access(
        self, field: Field, operation: typing.Literal["read", "write"]
    ) -> None:
        if self._has_field_access(field, operation):
            return

        _logger.info(
            "Access Denied by ACLs for operation: %s, uid: %s, model: %s, field: %s",
            operation,
            self.env.uid,
            self._name,
            field.name,
        )

        description = self.env["ir.model"]._get(self._name).name

        error_msg = _(
            'You do not have enough rights to access the field "%(field)s"'
            " on %(document_kind)s (%(document_model)s). "
            "Please contact your system administrator."
            "\n\nOperation: %(operation)s",
            field=field.name,
            document_kind=description,
            document_model=self._name,
            operation=operation,
        )

        if self.env.user._has_group("base.group_no_one"):
            if field.groups == NO_ACCESS:
                allowed_groups_msg = _("always forbidden")
            elif not field.groups:
                allowed_groups_msg = _("custom field access rules")
            else:
                groups_list = []
                missing_xmlids = []
                for xmlid in field.groups.split(","):
                    group = self.env.ref(xmlid.strip(), raise_if_not_found=False)
                    if group is not None and group._name == "res.groups":
                        groups_list.append(group)
                    else:
                        missing_xmlids.append(xmlid.strip())
                groups = self.env["res.groups"].union(*groups_list).sorted("id")
                allowed_groups_msg = _(
                    "allowed for groups %s",
                    ", ".join([repr(g.display_name) for g in groups] + missing_xmlids),
                )
            error_msg += _(
                "\nUser: %(user)s\nGroups: %(allowed_groups_msg)s",
                user=self.env.uid,
                allowed_groups_msg=allowed_groups_msg,
            )

        raise AccessError(error_msg)

    @api.model
    @api.deprecated(
        "Deprecated since 19.0, use `_check_field_access` on models."
        " To get the list of allowed fields, use `fields_get`.",
    )
    def check_field_access_rights(
        self,
        operation: typing.Literal["read", "write"],
        field_names: list[str] | None,
    ) -> list[str]:
        if self.env.su:
            return field_names or list(self._fields)

        if not field_names:
            return [
                field_name
                for field_name, field in self._fields.items()
                if self._has_field_access(field, operation)
            ]

        for field_name in field_names:
            field = self._fields.get(field_name)
            if field is None:
                continue
            self._check_field_access(field, operation)
        return field_names

    def check_access(self, operation: str) -> None:
        if not self.env.su and (result := self._check_access(operation)):
            raise result[1]()  # noqa: RSE102

    def has_access(self, operation: str) -> bool:
        return self.env.su or not self._check_access(operation)

    def _filtered_access(self, operation: str) -> Self:
        if self and not self.env.su and (result := self._check_access(operation)):
            return self - result[0]
        return self

    def _check_access(self, operation: str) -> tuple[Self, Callable] | None:
        Access = self.env["ir.model.access"]
        if not Access.check(self._name, operation, raise_exception=False):
            return self, functools.partial(
                Access._prepare_access_error, self._name, operation
            )

        real_self = self.browse(id_ for id_ in self._ids if id_)
        if real_self:
            Rule = self.env["ir.rule"]
            domain = Rule._compute_domain(self._name, operation)
            if domain and (
                forbidden := real_self
                - real_self.sudo()
                .with_context(active_test=False)
                .filtered_domain(domain)
            ):
                return forbidden, functools.partial(
                    Rule._prepare_access_error, operation, forbidden
                )

        return None

    @api.model
    @api.deprecated(
        "check_access_rights() is deprecated since 18.0; use check_access() instead."
    )
    def check_access_rights(
        self, operation: str, raise_exception: bool = True
    ) -> bool | None:
        if raise_exception:
            self.browse().check_access(operation)
            return True
        return self.browse().has_access(operation)

    @api.deprecated(
        "check_access_rule() is deprecated since 18.0; use check_access() instead."
    )
    def check_access_rule(self, operation: str) -> None:
        self.check_access(operation)

    def _check_company_domain(self, companies) -> Domain:
        if not companies:
            return Domain("company_id", "=", False)
        if isinstance(companies, unquote):
            return Domain("company_id", "in", unquote(f"{companies} + [False]"))
        return Domain("company_id", "in", to_record_ids(companies) + [False])

    def _check_company_candidates(
        self, regular_fields: list[str], property_fields: list[str]
    ) -> dict[tuple, list[tuple]]:
        groups: dict[tuple, list[tuple]] = defaultdict(list)
        property_company = self.env.company
        width = len(regular_fields) + len(property_fields)
        scopes = [(regular_fields, None), (property_fields, property_company)]

        for record_index, record_su in enumerate(self.sudo()):
            record = record_su.sudo(self.env.su)
            offset = 0
            for names, fixed_companies in scopes:
                if fixed_companies is None and names:
                    companies = (
                        record
                        if self._name == "res.company"
                        else record.company_id
                        if "company_id" in self
                        else record.company_ids
                    )
                else:
                    companies = fixed_companies
                for position, name in enumerate(names):
                    corecords = record_su[name]
                    if corecords:
                        groups[(name, tuple(companies.ids))].append(
                            (
                                record_index * width + offset + position,
                                record,
                                corecords,
                                companies,
                            )
                        )
                offset += len(names)
        return groups

    def _check_company_violations(
        self, groups: dict[tuple, list[tuple]]
    ) -> Iterator[tuple[int, Self, str, Self]]:
        for (name, _companies_ids), entries in groups.items():
            companies = entries[0][3]
            comodel = entries[0][2].browse()
            all_corecords = comodel.union(*(entry[2] for entry in entries))
            domain = all_corecords._check_company_domain(companies)
            if not domain:
                continue
            allowed = set(
                all_corecords.with_context(active_test=False)
                .filtered_domain(domain)
                ._ids
            )
            for rank, record, corecords, _companies in entries:
                if not allowed.issuperset(corecords._ids):
                    yield rank, record, name, corecords

    def _check_company(self, fnames: Collection[str] | None = None) -> None:
        if fnames is None or "company_id" in fnames or "company_ids" in fnames:
            fnames = self._fields

        regular_fields = []
        property_fields = []
        for name in fnames:
            field = self._fields[name]
            if field.relational and field.check_company:
                if not field.company_dependent:
                    regular_fields.append(name)
                else:
                    property_fields.append(name)

        if not (regular_fields or property_fields):
            return

        if regular_fields and not (
            self._name == "res.company" or "company_id" in self or "company_ids" in self
        ):
            _logger.warning(
                "Skipping a company check for model %s. Its fields %s "
                "are set as company-dependent, but the model doesn't "
                "have a `company_id` or `company_ids` field!",
                self._name,
                regular_fields,
            )
            return

        candidates = self._check_company_candidates(regular_fields, property_fields)
        inconsistencies = [
            (record, name, corecords)
            for _rank, record, name, corecords in sorted(
                self._check_company_violations(candidates), key=itemgetter(0)
            )
        ]

        if inconsistencies:
            lines = [_("Uh-oh! You've got some company inconsistencies here:")]
            company_msg = _lt(
                "- Record is company \u201c%(company)s\u201d while \u201c%(field)s\u201d (%(fname)s: %(values)s) belongs to another company."
            )
            record_msg = _lt(
                "- \u201c%(record)s\u201d belongs to company \u201c%(company)s\u201d while \u201c%(field)s\u201d (%(fname)s: %(values)s) belongs to another company."
            )
            root_company_msg = _lt(
                "- Only a root company can be set on \u201c%(record)s\u201d. Currently set to \u201c%(company)s\u201d"
            )
            for record, name, corecords in inconsistencies[:5]:
                if record._name == "res.company":
                    msg, companies = company_msg, record
                elif record == corecords and name == "company_id":
                    msg, companies = root_company_msg, record.company_id
                else:
                    msg = record_msg
                    companies = (
                        record.company_id
                        if "company_id" in record
                        else record.company_ids
                    )
                field = self.env["ir.model.fields"]._get(self._name, name)
                lines.append(
                    str(msg)
                    % {
                        "record": record.display_name,
                        "company": ", ".join(
                            company.display_name for company in companies
                        ),
                        "field": field.field_description,
                        "fname": field.name,
                        "values": ", ".join(
                            repr(rec.display_name) for rec in corecords
                        ),
                    }
                )
            lines.append(_("To avoid a mess, no company crossover is allowed!"))
            raise UserError("\n".join(lines))
