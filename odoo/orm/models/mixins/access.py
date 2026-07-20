"""Access control mixin for BaseModel: field- and record-level access checks."""

import functools
import logging
import typing
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
    from collections.abc import Callable

    from ...fields import Field

_lt = LazyTranslate("base")

_logger = logging.getLogger("odoo.models")


class AccessMixin(_ModelStubs):
    """Mixin providing field- and record-level access control."""

    __slots__ = ()

    # Field-level access control

    def _has_field_access(
        self, field: Field, operation: typing.Literal["read", "write"]
    ) -> bool:
        """Return whether the user may access ``field`` for ``operation``.

        Override to customize field access.

        :param field: the field to check
        :param operation: one of ``read``, ``write``
        :return: whether the field is accessible
        """
        if not field.groups or self.env.su:
            return True
        if field.groups == NO_ACCESS:
            return False
        return self.env.user.has_groups(field.groups)

    @api.model
    def _check_field_access(
        self, field: Field, operation: typing.Literal["read", "write"]
    ) -> None:
        """Check the user access rights on the given field.

        :param field: the field to check
        :param operation: one of ``read``, ``write``
        :raise AccessError: if the user is not allowed to access the provided field
        """
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
                groups_list = [self.env.ref(g) for g in field.groups.split(",")]
                groups = self.env["res.groups"].union(*groups_list).sorted("id")
                allowed_groups_msg = _(
                    "allowed for groups %s",
                    ", ".join(repr(g.display_name) for g in groups),
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
        """Check the user access rights on the given fields.

        If `field_names` is not provided, we list accessible fields to the user.
        Otherwise, an error is raised if we try to access a forbidden field.
        Unknown (virtual) fields are ignored.

        :param operation: one of ``read``, ``write`` (field access is group-based,
          so ``create``/``unlink`` have no field-level granularity)
        :param field_names: names of the fields
        :return: provided fields if fields is truthy (or the fields
          readable by the current user).
        :raise AccessError: if the user is not allowed to access
          the provided fields.
        """
        if self.env.su:
            return field_names or list(self._fields)

        if not field_names:
            return [
                field_name
                for field_name, field in self._fields.items()
                if self._has_field_access(field, operation)
            ]

        for field_name in field_names:
            # Unknown (virtual) fields are accessible: nothing is read or written.
            field = self._fields.get(field_name)
            if field is None:
                continue
            self._check_field_access(field, operation)
        return field_names

    # Record-level access control

    def check_access(self, operation: str) -> None:
        """Verify that the current user is allowed to perform ``operation`` on
        all the records in ``self``. The method raises an :class:`AccessError`
        if the operation is forbidden on the model in general, or on any record
        in ``self``.

        In particular, when ``self`` is empty, the method checks whether the
        current user has some permission to perform ``operation`` on the model
        in general::

            # check that user has some minimal permission on the model
            records.browse().check_access(operation)

        """
        if not self.env.su and (result := self._check_access(operation)):
            # result[1] is a factory partial; call it to build the AccessError.
            # Raising the bare partial would TypeError (not a BaseException).
            raise result[1]()  # noqa: RSE102

    def has_access(self, operation: str) -> bool:
        """Return whether the current user is allowed to perform ``operation``
        on all the records in ``self``. The method is fully consistent with
        method :meth:`check_access` but returns a boolean instead.
        """
        return self.env.su or not self._check_access(operation)

    def _filtered_access(self, operation: str) -> Self:
        """Return the subset of ``self`` for which the current user is allowed
        to perform ``operation``. The method is fully equivalent to::

            self.filtered(lambda record: record.has_access(operation))

        """
        if self and not self.env.su and (result := self._check_access(operation)):
            return self - result[0]
        return self

    def _check_access(self, operation: str) -> tuple[Self, Callable] | None:
        """Return ``None`` if the current user may perform ``operation`` on
        ``self``. Otherwise return ``(records, function)`` where ``records`` are
        the forbidden records and ``function`` builds the corresponding exception.

        Two checks run in sequence:

        1. **Model-level ACL** (``ir.model.access``): always runs, even on an
           empty recordset, so ``self.browse().check_access(op)`` checks
           permission before records exist (e.g. at the start of ``create()``).
        2. **Record-level rules** (``ir.rule``): runs only against real ids, via
           :meth:`filtered_domain`. ``NewId`` records always pass: they have no
           row to filter, and their cache (often defaults) is not a meaningful
           permission decision. NewId data access still checks the origin via
           ``Field.__get__`` / ``_fetch_field``.

        Base implementation of :meth:`check_access`, :meth:`has_access` and
        :meth:`_filtered_access`; override to restrict access to ``self``.
        """
        Access = self.env["ir.model.access"]
        if not Access.check(self._name, operation, raise_exception=False):
            return self, functools.partial(
                Access._make_access_error, self._name, operation
            )

        # Rule check applies only to real (truthy) ids; NewIds have no row to
        # filter against (see docstring).
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
                    Rule._make_access_error, operation, forbidden
                )

        return None

    @api.model
    @api.deprecated(
        "check_access_rights() is deprecated since 18.0; use check_access() instead."
    )
    def check_access_rights(
        self, operation: str, raise_exception: bool = True
    ) -> bool | None:
        """Verify that the given operation is allowed for the current user according to ir.model.access.

        :param str operation: one of ``create``, ``read``, ``write``, ``unlink``
        :param bool raise_exception: whether an exception should be raised if operation is forbidden
        :return: whether the operation is allowed
        :rtype: bool | None
        :raise AccessError: if the operation is forbidden and raise_exception is True
        """
        if raise_exception:
            # check_access() returns None (it only raises on denial); this
            # deprecated shim is documented to return a bool, so a non-raising
            # call means "allowed" -> return True.
            self.browse().check_access(operation)
            return True
        return self.browse().has_access(operation)

    @api.deprecated(
        "check_access_rule() is deprecated since 18.0; use check_access() instead."
    )
    def check_access_rule(self, operation: str) -> None:
        """Verify that the given operation is allowed for the current user according to ir.rules.

        :param str operation: one of ``create``, ``read``, ``write``, ``unlink``
        :return: None if the operation is allowed
        :raise UserError: if current ``ir.rules`` do not permit this operation.
        """
        self.check_access(operation)

    # Company consistency checks

    def _check_company_domain(self, companies) -> Domain:
        """Domain to be used for company consistency between records regarding this model.

        :param companies: the allowed companies for the related record
        :type companies: BaseModel or list or tuple or int or unquote
        """
        if not companies:
            return Domain("company_id", "=", False)
        if isinstance(companies, unquote):
            return Domain("company_id", "in", unquote(f"{companies} + [False]"))
        return Domain("company_id", "in", to_record_ids(companies) + [False])

    def _check_company(self, fnames: list[str] | None = None) -> None:
        """Check the companies of the values of the given field names.

        :param fnames: names of relational fields to check
        :type fnames: list[str] | None
        :raises UserError: if the `company_id` of the value of any field is not
            in `[False, self.company_id]` (or `self` if
            :class:`~odoo.addons.base.models.res_company`).

        For :class:`~odoo.addons.base.models.res_users` relational fields,
        verifies record company is in `company_ids` fields.

        User with main company A, having access to company A and B, could be
        assigned or linked to records in company B.
        """
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

        inconsistencies = []
        # Company owning property values; loop-invariant, so resolve once.
        property_company = self.env.company
        for record in self:
            # sudo() is invariant across the field loops; build it once per
            # record instead of re-allocating for every checked field.
            record_su = record.sudo()
            # Part 1: records linked via relation fields must match the origin
            # document's company, i.e. self.account_id.company_id == self.company_id
            if regular_fields:
                if self._name == "res.company":
                    companies = record
                elif "company_id" in self:
                    companies = record.company_id
                elif "company_ids" in self:
                    companies = record.company_ids
                else:
                    # developer diagnostic: %-args, not translated, so logging
                    # stays lazy.
                    _logger.warning(
                        "Skipping a company check for model %s. Its fields %s "
                        "are set as company-dependent, but the model doesn't "
                        "have a `company_id` or `company_ids` field!",
                        self._name,
                        regular_fields,
                    )
                    continue
                for name in regular_fields:
                    corecords = record_su[name]
                    if corecords:
                        domain = corecords._check_company_domain(companies)
                        if domain and corecords != corecords.with_context(
                            active_test=False
                        ).filtered_domain(domain):
                            inconsistencies.append((record, name, corecords))
            # Part 2: for property / company-dependent fields, linked records
            # must match the company owning the property value (self.env.company),
            # i.e. self.property_account_payable_id.company_id == self.env.company
            for name in property_fields:
                corecords = record_su[name]
                if corecords:
                    domain = corecords._check_company_domain(property_company)
                    if domain and corecords != corecords.with_context(
                        active_test=False
                    ).filtered_domain(domain):
                        inconsistencies.append((record, name, corecords))

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
