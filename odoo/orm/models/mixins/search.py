import contextlib
import logging
import typing
from typing import Self

from odoo.exceptions import UserError
from odoo.libs.profiling import _n1_enabled, _OrmProfile

from ... import decorators as api
from ..._typing import (
    DomainType,
    ValuesType,
)
from ...domain import Domain
from ...primitives import COLLECTION_TYPES
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

    from ...fields import Field

_logger = logging.getLogger("odoo.models")
_orm_read = logging.getLogger("odoo.orm.read")


def _is_unset_name(value: typing.Any) -> bool:
    return value is False or value is None or value == ""


class SearchMixin(_ModelStubs):
    __slots__ = ()

    @api.model
    @api.readonly
    def search_count(self, domain: DomainType, limit: int | None = None) -> int:
        prof = _OrmProfile(_orm_read)

        query = self._search(domain, limit=limit)
        count = len(query)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record("search", self._name, count, frozenset())

        prof.stop()
        prof.report(
            _orm_read,
            "search_count %s: domain=%s, limit=%s -> %d",
            self._name,
            str(domain)[:200],
            limit,
            count,
        )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record("search", self._name, count, prof.elapsed)

        return count

    @api.model
    @api.readonly
    def search(
        self,
        domain: DomainType,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> Self:
        return self.search_fetch(domain, [], offset=offset, limit=limit, order=order)

    @api.model
    @api.private
    @api.readonly
    def search_fetch(
        self,
        domain: DomainType,
        field_names: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> Self:
        prof = _OrmProfile(_orm_read)

        query = self._search(
            domain, offset=offset, limit=limit, order=order or self._order
        )
        prof.mark("search")

        if query.is_empty():
            if not self.env.su:
                self._determine_fields_to_fetch(field_names)
            prof.stop("fields")
            prof.report(
                _orm_read,
                "search_fetch %s: domain=%s -> 0 records (empty query)",
                self._name,
                str(domain)[:200],
            )
            if prof.agg and (p := self.env.transaction._orm_profiler):
                p.record("search", self._name, 0, prof.elapsed)
            if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
                tracker.record("search", self._name, 0, frozenset(field_names or ()))
            return self.browse()

        fields_to_fetch = self._determine_fields_to_fetch(field_names)
        prof.mark("fields")

        result = self._fetch_query(query, fields_to_fetch)

        if _n1_enabled and (tracker := self.env.transaction._n1_tracker):
            tracker.record(
                "search", self._name, len(result), frozenset(field_names or ())
            )

        prof.stop("fetch")
        prof.report(
            _orm_read,
            "search_fetch %s: domain=%s, offset=%d, limit=%s -> %d records",
            self._name,
            str(domain)[:200],
            offset,
            limit,
            len(result),
        )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record("search", self._name, len(result), prof.elapsed)

        return result

    @api.model
    def _search_display_name(self, operator: str, value: typing.Any) -> DomainType:
        search_fnames = self._rec_names_search or (
            [self._rec_name] if self._rec_name else []
        )
        if search_fnames:
            usable = [
                fname
                for fname in search_fnames
                if not self._is_rec_names_search_cyclic(fname)
            ]
            if not usable:
                # a cycle is a configuration defect; degrading to the
                # unsearchable fallback would return Domain.TRUE and turn a
                # previously restricting search into "match everything"
                raise UserError(
                    self.env._(
                        "Cannot search %(model)s by name: every entry of its "
                        "_rec_names_search (%(entries)s) recurses back into "
                        "%(model)s",
                        model=self._name,
                        entries=", ".join(search_fnames),
                    )
                )
            if len(usable) != len(search_fnames):
                _logger.warning(
                    "Dropping cyclic _rec_names_search entries %s on %s",
                    [f for f in search_fnames if f not in usable],
                    self._name,
                )
            search_fnames = usable
        if not search_fnames:
            return self._search_display_name_unsearchable(operator, value)
        if operator.endswith("like") and not value and "=" not in operator:
            return (
                Domain.FALSE if operator in Domain.NEGATIVE_OPERATORS else Domain.TRUE
            )
        if operator in ("<", "<=", ">", ">="):
            search_fnames = search_fnames[:1]

        negative = operator in Domain.NEGATIVE_OPERATORS
        aggregator = Domain.AND if negative else Domain.OR

        if operator in ("in", "not in", "=", "!="):
            values = list(value) if isinstance(value, COLLECTION_TYPES) else [value]
            match_values = [v for v in values if not _is_unset_name(v)]
            if len(match_values) != len(values):
                parts = [self._search_display_name_unset(search_fnames, negative)]
                if match_values:
                    parts.insert(
                        0,
                        self._search_display_name_match(
                            operator, match_values, search_fnames
                        ),
                    )
                return aggregator(parts)

        return self._search_display_name_match(operator, value, search_fnames)

    @api.model
    def _search_display_name_match(
        self, operator: str, value: typing.Any, search_fnames: Sequence[str]
    ) -> Domain:
        aggregator = Domain.AND if operator in Domain.NEGATIVE_OPERATORS else Domain.OR
        domains = []
        for field_name in search_fnames:
            field = self._rec_names_search_field(field_name)
            if field.relational:
                domains.append([(field_name + ".display_name", operator, value)])
            elif operator.endswith("like"):
                domains.append([(field_name, operator, value)])
            elif isinstance(value, COLLECTION_TYPES):
                typed_value = []
                for v in value:
                    with contextlib.suppress(ValueError, TypeError):
                        typed_value.append(field.convert_to_write(v, self))
                domains.append([(field_name, operator, typed_value)])
            else:
                with contextlib.suppress(ValueError, TypeError):
                    typed_value = field.convert_to_write(value, self)
                    domains.append([(field_name, operator, typed_value)])
        return aggregator(domains)

    @api.model
    def _is_rec_names_search_cyclic(self, field_name: str) -> bool:
        field = self._rec_names_search_field(field_name)
        if not field.relational or not field.comodel_name:
            return False
        seen = {self._name}
        pending = [field.comodel_name]
        while pending:
            model_name = pending.pop()
            if model_name == self._name:
                return True
            if model_name in seen or model_name not in self.env:
                continue
            seen.add(model_name)
            comodel = self.env[model_name]
            entries = comodel._rec_names_search or (
                [comodel._rec_name] if comodel._rec_name else []
            )
            for entry in entries:
                try:
                    next_field = comodel._rec_names_search_field(entry)
                except KeyError, ValueError:
                    continue
                if next_field.relational and next_field.comodel_name:
                    pending.append(next_field.comodel_name)
        return False

    @api.model
    def _rec_names_search_field(self, field_name: str) -> Field:
        model: typing.Any = self
        segments = field_name.split(".")
        for i, fname in enumerate(segments):
            if model is None:
                raise ValueError(
                    f"Invalid _rec_names_search entry {field_name!r} on "
                    f"{self._name!r}: segment {segments[i - 1]!r} is "
                    f"non-relational and cannot be traversed further"
                )
            field = model._fields[fname]
            model = self.env.get(field.comodel_name or "") if field.relational else None
        return field

    @api.model
    def _search_display_name_unsearchable(
        self, operator: str, value: typing.Any
    ) -> DomainType:
        field = self._fields["display_name"]
        if field.is_column:
            return Domain(field.name, operator, value)
        _logger.warning(
            "Cannot search on display_name, no _rec_name or _rec_names_search "
            "defined on %s; the condition does not restrict",
            self._name,
        )
        return Domain.TRUE

    @api.model
    def _search_display_name_unset(
        self, search_fnames: Sequence[str], negative: bool
    ) -> Domain:
        unset = Domain.AND(
            self._search_display_name_unset_field(field_name)
            for field_name in search_fnames
        )
        return ~unset if negative else unset

    @api.model
    def _search_display_name_unset_field(self, field_name: str) -> Domain:
        if not self._rec_names_search_field(field_name).relational:
            return Domain(field_name, "=", False)
        segments = field_name.split(".")
        prefixes = [".".join(segments[: i + 1]) for i in range(len(segments))]
        return Domain.OR(
            [
                *(Domain(prefix, "=", False) for prefix in prefixes),
                Domain(field_name + ".display_name", "=", False),
            ]
        )

    @api.model
    @api.readonly
    def name_search(
        self,
        name: str = "",
        domain: DomainType | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        domain = Domain("display_name", operator, name) & Domain(domain or Domain.TRUE)
        records = self.search_fetch(domain, ["display_name"], limit=limit)
        return [(record.id, record.display_name or "") for record in records.sudo()]

    @api.model
    @api.readonly
    def search_read(
        self,
        domain: DomainType | None = None,
        fields: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        **read_kwargs,
    ) -> list[ValuesType]:
        if not fields:
            fields = list(self.fields_get(attributes=()))
        records = self.search_fetch(
            domain or [], fields, offset=offset, limit=limit, order=order
        )

        if "active_test" in self.env.context:
            context = dict(self.env.context)
            del context["active_test"]
            records = records.with_context(context)

        return records._read_format(fnames=fields, **read_kwargs)

    @api.private
    def lock_for_update(self, *, allow_referencing: bool = False) -> None:
        self.env.backend.lock_for_update(self, allow_referencing=allow_referencing)

    @api.private
    def try_lock_for_update(
        self, *, allow_referencing: bool = False, limit: int | None = None
    ) -> Self:
        return self.env.backend.try_lock_for_update(
            self, allow_referencing=allow_referencing, limit=limit
        )
