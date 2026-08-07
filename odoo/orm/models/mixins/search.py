import contextlib
import logging
import typing
from typing import Self

from odoo.exceptions import LockError
from odoo.libs.profiling import _OrmProfile
from odoo.tools import SQL, Query, partition

from ... import decorators as api
from ..._typing import (
    DomainType,
    ValuesType,
)
from ...domain import Domain
from ...primitives import COLLECTION_TYPES, NewId
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

        prof.stop()
        if prof.debug:
            _orm_read.debug(
                "[%.3f ms] search_count %s: domain=%s, limit=%s -> %d",
                prof.elapsed * 1000,
                self._name,
                str(domain)[:200],
                limit,
                count,
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_search(self._name, count, prof.elapsed)

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
            prof.stop()
            if prof.debug:
                _orm_read.debug(
                    "[%.3f ms] search_fetch %s: domain=%s -> 0 records (empty query)"
                    " | search=%.1f",
                    prof.elapsed * 1000,
                    self._name,
                    str(domain)[:200],
                    prof.ms("start", "search"),
                )
            if prof.agg and (p := self.env.transaction._orm_profiler):
                p.record_search(self._name, 0, prof.elapsed)
            return self.browse()

        fields_to_fetch = self._determine_fields_to_fetch(field_names)
        prof.mark("fields")

        result = self._fetch_query(query, fields_to_fetch)

        prof.stop()
        if prof.debug:
            _orm_read.debug(
                "[%.3f ms] search_fetch %s: domain=%s, offset=%d, limit=%s -> %d records"
                " | search=%.1f fields=%.1f fetch=%.1f",
                prof.elapsed * 1000,
                self._name,
                str(domain)[:200],
                offset,
                limit,
                len(result),
                prof.ms("start", "search"),
                prof.ms("search", "fields"),
                prof.ms("fields", "end"),
            )
        if prof.agg and (p := self.env.transaction._orm_profiler):
            p.record_search(self._name, len(result), prof.elapsed)

        return result

    @api.model
    def _search_display_name(self, operator: str, value: typing.Any) -> DomainType:
        search_fnames = self._rec_names_search or (
            [self._rec_name] if self._rec_name else []
        )
        search_fnames = [
            fname for fname in search_fnames if not self._rec_names_search_cyclic(fname)
        ]
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
    def _rec_names_search_cyclic(self, field_name: str) -> bool:
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
        model = self
        segments = field_name.split(".")
        for i, fname in enumerate(segments):
            if model is None:
                raise ValueError(
                    f"Invalid _rec_names_search entry {field_name!r} on "
                    f"{self._name!r}: segment {segments[i - 1]!r} is "
                    f"non-relational and cannot be traversed further"
                )
            field = model._fields[fname]
            model = self.env.get(field.comodel_name) if field.relational else None
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
        return [(record.id, record.display_name) for record in records.sudo()]

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
        if (backend := self.env.backend) is not None:
            backend.lock_for_update(self, allow_referencing=allow_referencing)
            return
        ids = {id_ for id_ in self._ids if id_}
        if not ids:
            return
        query = Query(self.env, self._table, self._table_sql)
        query.add_where(
            SQL("%s = ANY(%s)", SQL.identifier(self._table, "id"), list(ids))
        )
        if allow_referencing:
            lock_sql = SQL("FOR NO KEY UPDATE SKIP LOCKED")
        else:
            lock_sql = SQL("FOR UPDATE SKIP LOCKED")
        rows = self.env.execute_query(SQL("%s %s", query.select(), lock_sql))
        if len(rows) != len(ids):
            raise LockError(self.env._("Cannot grab a lock on records"))

    @api.private
    def try_lock_for_update(
        self, *, allow_referencing: bool = False, limit: int | None = None
    ) -> Self:
        if (backend := self.env.backend) is not None:
            return backend.try_lock_for_update(
                self, allow_referencing=allow_referencing, limit=limit
            )
        new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
        if limit is not None and len(new_ids) >= limit:
            return self.browse(new_ids[:limit])
        if not ids:
            return self
        if limit is not None:
            query = self.browse(ids)._as_query(ordered=True)
            query.limit = limit - len(new_ids)
        else:
            query = Query(self.env, self._table, self._table_sql)
            query.add_where(
                SQL("%s = ANY(%s)", SQL.identifier(self._table, "id"), list(ids))
            )
        if allow_referencing:
            lock_sql = SQL("FOR NO KEY UPDATE SKIP LOCKED")
        else:
            lock_sql = SQL("FOR UPDATE SKIP LOCKED")
        sql = SQL("%s %s", query.select(), lock_sql)
        real_ids = (id_ for [id_] in self.env.execute_query(sql))
        valid_ids = {*real_ids, *new_ids}
        return self.browse(i for i in self._ids if i in valid_ids)
