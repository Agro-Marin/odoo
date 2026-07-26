"""Search and query mixin for BaseModel."""

import contextlib
import logging
import typing
from typing import Self

from odoo.exceptions import LockError, UserError
from odoo.tools import SQL, Query, partition
from odoo.tools.orm_profiler import _OrmProfile
from odoo.tools.translate import _

from ... import decorators as api
from ..._typing import (
    DomainType,
    ValuesType,
)
from ...constants import SQL_ORDER_DIR, SQL_ORDER_NULLS
from ...domain import Domain
from ...parsing import parse_field_expr, regex_order
from ...primitives import COLLECTION_TYPES, NewId
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

    from ...fields import Field

_logger = logging.getLogger("odoo.models")
_orm_read = logging.getLogger("odoo.orm.read")


def _is_unset_name(value: typing.Any) -> bool:
    """Whether *value* spells "no display name" in a domain comparand.

    ``False`` is the canonical spelling the optimizer normalizes onto; ``None``
    is the JSON/RPC one; ``""`` is a Char's ``falsy_value``, which SQL aliases
    with NULL.  ``0`` and other falsy non-strings are *not* null markers — they
    are legitimate names to match against.
    """
    return value is False or value is None or value == ""


class SearchMixin(_ModelStubs):
    """Mixin providing search and query functionality for BaseModel."""

    __slots__ = ()

    @api.model
    @api.readonly
    def search_count(self, domain: DomainType, limit: int | None = None) -> int:
        """Return the number of records in the current model matching
        :ref:`the provided domain <reference/orm/domains>`.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                     list to match all records.
        :param limit: maximum number of record to count (upperbound) (default: all)

        This is a high-level method, which should not be overridden. Its actual
        implementation is done by method :meth:`_search`.
        """
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
        """Search for the records that satisfy the given
        :ref:`search domain <reference/orm/domains>`.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                     list to match all records.
        :param offset: number of results to ignore (default: none)
        :param limit: maximum number of records to return (default: all)
        :param order: sort string
        :returns: at most ``limit`` records matching the search criteria
        :raise AccessError: if user is not allowed to access requested information

        This is a high-level method, which should not be overridden. Its actual
        implementation is done by method :meth:`_search`.
        """
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
        """Search for records satisfying the given
        :ref:`search domain <reference/orm/domains>`, and fetch the given fields
        into the cache. Combines :meth:`search` and :meth:`fetch` in a minimal
        number of SQL queries.

        :param domain: :ref:`A search domain <reference/orm/domains>`. Use an empty
                     list to match all records.
        :param field_names: a collection of field names to fetch, or ``None`` for
            all accessible fields marked with ``prefetch=True``
        :param offset: number of results to ignore (default: none)
        :param limit: maximum number of records to return (default: all)
        :param order: sort string
        :returns: at most ``limit`` records matching the search criteria
        :raise AccessError: if user is not allowed to access requested information
        """
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
        """Return a domain matching records whose display name matches ``value``
        under ``operator``.

        Implements the search on the ``display_name`` field; may be overridden.
        Default implementation searches ``_rec_names_search`` or ``_rec_name``.

        A *match* against a concrete comparand fans out over the search fields as
        a disjunction ("any of the name fields matches"), and a negative operator
        is its De Morgan dual.  A *null* comparand does not follow that reading:
        a record has no display name only when **every** search field is unset,
        so the two aggregators are swapped for that part of the comparand — see
        :meth:`_search_display_name_unset`.  Mixed sets such as
        ``('display_name', 'in', ['Alpha', False])`` are split into their match
        part and their null part, each aggregated its own way, and recombined.
        """
        search_fnames = self._rec_names_search or (
            [self._rec_name] if self._rec_name else []
        )
        search_fnames = [
            fname for fname in search_fnames if not self._rec_names_search_cyclic(fname)
        ]
        if not search_fnames:
            _logger.warning(
                "Cannot search on display_name, no _rec_name or _rec_names_search defined on %s",
                self._name,
            )
            return Domain.TRUE
        if operator.endswith("like") and not value and "=" not in operator:
            return (
                Domain.FALSE if operator in Domain.NEGATIVE_OPERATORS else Domain.TRUE
            )
        if operator in ("<", "<=", ">", ">="):
            # An ordering comparison has exactly one referent: the record's
            # primary name.  Fanning it out over the secondary search fields
            # ORs in `email <= x`, `vat <= x`, ... which only ever *weakens* the
            # condition -- on res.partner `('display_name', '<=', 'M')` matched
            # every row, because some row always has a NULL-or-smaller vat.
            # Neither aggregator is sound here (AND is as arbitrary as OR), so
            # restrict to the leading entry, which is the field display_name is
            # actually built from and reduces to `_rec_name` for the common
            # single-field case.
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
        """Fan a non-null comparand out over ``search_fnames``.

        The match half of :meth:`_search_display_name`: a disjunction over the
        search fields (its De Morgan dual for a negative operator).
        """
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
        """Whether expanding *field_name* would re-enter this model.

        A relational entry contributes ``<path>.display_name``, which the
        optimizer turns into ``<path> any (display_name ...)`` and re-enters on
        the comodel.  If following the comodels' own ``_rec_names_search`` leads
        back here, that expansion never terminates: it nests one level per pass
        until the depth guard fires, and *every* ``display_name`` search on the
        model dies with ``ValueError: Domain nesting too deep`` — including the
        plain ``ilike`` that ``name_search`` issues, so the field becomes
        unsearchable and the message names neither the model nor the entry.

        The obvious spelling is enough to trigger it: ``['name', 'parent_id']``
        on any hierarchical model.  A mutual cycle (``a._rec_names_search =
        ['b_id']`` and ``b._rec_names_search = ['a_id']``) does it too, so this
        walks the graph rather than only comparing against ``self``.

        The cyclic entry is dropped; the remaining ones still search.  The walk
        is over model names with a visited set, and only runs for a relational
        entry, which is rare.
        """
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
        """Resolve a (possibly dotted) ``_rec_names_search`` entry to its last field."""
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
    def _search_display_name_unset(
        self, search_fnames: Sequence[str], negative: bool
    ) -> Domain:
        """Return the domain for "this record has no display name" (or its negation).

        The display name is empty only when *every* search field is empty, so
        this conjoins the per-field null tests — the opposite aggregator from the
        match case.  Without the swap, ``('display_name', '!=', False)`` became
        "all of ``complete_name``/``email``/``ref``/``vat``/… are set" and matched
        almost nothing, while ``filtered_domain`` (which compares the computed
        value) matched every named record.

        An entry ending on a relational field is unset when *any* relation along
        the path is unset, or when the target's display name is empty.  Testing
        only the fully traversed path would silently exclude rows whose relation
        is NULL, since ``any`` never matches those.
        """
        unset = Domain.AND(
            self._search_display_name_unset_field(field_name)
            for field_name in search_fnames
        )
        return ~unset if negative else unset

    @api.model
    def _search_display_name_unset_field(self, field_name: str) -> Domain:
        """Return the domain for "this one ``_rec_names_search`` entry is empty"."""
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
        """Search for records that have a display name matching the given
        ``name`` pattern when compared with the given ``operator``, while also
        matching the optional search domain (``domain``).

        This is used for example to provide suggestions based on a partial
        value for a relational field. Should usually behave as the reverse of
        ``display_name``, but that is not guaranteed.

        This method is equivalent to calling :meth:`~.search` with a search
        domain based on ``display_name`` and mapping id and display_name on
        the resulting search.

        :param name: the name pattern to match
        :param domain: search domain (see :meth:`~.search` for syntax),
                       specifying further restrictions
        :param operator: domain operator for matching ``name``,
                         such as ``'like'`` or ``'='``.
        :param limit: max number of records to return
        :return: list of pairs ``(id, display_name)`` for all matching records.
        """
        domain = Domain("display_name", operator, name) & Domain(domain or Domain.TRUE)
        records = self.search_fetch(domain, ["display_name"], limit=limit)
        return [(record.id, record.display_name) for record in records.sudo()]

    def _check_qorder(self, word: str) -> None:
        if not regex_order.match(word):
            raise UserError(
                _(
                    'Invalid "order" specified (%s).'
                    ' A valid "order" specification is a comma-separated list of valid field names'
                    " (optionally followed by asc/desc for the direction)",
                    word,
                )
            )

    def _order_to_sql(
        self,
        order: str,
        query: Query,
        alias: str | None = None,
        reverse: bool = False,
    ) -> SQL:
        """Return an :class:`SQL` object that represents the given ORDER BY
        clause, without the ORDER BY keyword.  The method also checks whether
        the fields in the order are accessible for reading.
        """
        order = order or self._order
        if not order:
            return SQL.EMPTY
        self._check_qorder(order)

        alias = alias or self._table

        terms = []
        for order_part in order.split(","):
            order_match = regex_order.match(order_part)
            if order_match is None:
                raise RuntimeError(
                    f"Order part {order_part!r} did not match regex_order "
                    f"despite passing _check_qorder({order!r})"
                )
            field_name = order_match["field"]

            direction = (order_match["direction"] or "").upper()
            nulls = (order_match["nulls"] or "").upper()
            if reverse:
                direction = "ASC" if direction == "DESC" else "DESC"
                if nulls:
                    nulls = "NULLS LAST" if nulls == "NULLS FIRST" else "NULLS FIRST"

            sql_direction = SQL_ORDER_DIR.get(direction, SQL.EMPTY)
            sql_nulls = SQL_ORDER_NULLS.get(nulls, SQL.EMPTY)

            if property_name := order_match["property"]:
                field_name = f"{field_name}.{property_name}"
            term = self._order_field_to_sql(
                alias, field_name, sql_direction, sql_nulls, query
            )
            if term:
                terms.append(term)

        return SQL(", ").join(terms)

    def _order_field_to_sql(
        self,
        alias: str,
        field_name: str,
        direction: SQL,
        nulls: SQL,
        query: Query,
    ) -> SQL:
        """Return an :class:`SQL` object that represents the ordering by the
        given field.  The method also checks whether the field is accessible for
        reading.

        A term the user may not read is **dropped** (empty result), not
        refused.  Sequencing rows on a value the caller cannot see leaks it --
        weakly, as relative order, but ``limit``/``offset`` walks that order
        out record by record -- so the term must not reach the SQL.  Raising
        instead is not an option here: this runs for the model's own
        ``_order`` on a model-level (empty) recordset, and
        ``_has_field_access`` may be record-sensitive (``res.users`` grants
        ``SELF_READABLE_FIELDS`` only when ``self._origin == self.env.user``),
        so an empty recordset fails closed and a user could no longer sort, or
        open the preferences form for, their own record.  Dropping keeps those
        flows working and still exposes nothing; :meth:`_search` restores a
        deterministic order when this leaves nothing to sort by.

        :param direction: one of ``SQL("ASC")``, ``SQL("DESC")``, ``SQL()``
        :param nulls: one of ``SQL("NULLS FIRST")``, ``SQL("NULLS LAST")``, ``SQL()``
        """
        fname, property_name = parse_field_expr(field_name)
        field = self._fields.get(fname)
        if not field:
            raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

        if not self._has_field_access(field, "read"):
            _logger.debug(
                "Ignoring ORDER BY %s.%s: not readable by user %s",
                self._name,
                field_name,
                self.env.uid,
            )
            return SQL.EMPTY

        if field.type == "many2one":
            seen = self.env.context.get("__m2o_order_seen", ())
            if field in seen:
                return SQL.EMPTY
            self = self.with_context(__m2o_order_seen=frozenset((field, *seen)))

            comodel = self.env[field.comodel_name]
            if property_name == "id":
                coorder = "id"
                sql_field = self._field_to_sql(alias, fname, query)
            else:
                coorder = comodel._order
                sql_field = self._field_to_sql(alias, field_name, query)

            if coorder == "id":
                if query._any_value_orderby:
                    sql_field = SQL("ANY_VALUE(%s)", sql_field)
                elif query._collect_order_groupby:
                    query._order_groupby.append(sql_field)
                return SQL("%s %s %s", sql_field, direction, nulls)

            terms = []
            if nulls.code == "NULLS FIRST":
                terms.append(SQL("%s IS NOT NULL", sql_field))
            elif nulls.code == "NULLS LAST":
                terms.append(SQL("%s IS NULL", sql_field))

            _comodel, coalias = field.join(self, alias, query)

            reverse = direction.code == "DESC"
            term = comodel._order_to_sql(coorder, query, alias=coalias, reverse=reverse)
            if term:
                terms.append(term)
            return SQL(", ").join(terms)

        sql_field = self._field_to_sql(alias, field_name, query)
        if field.type == "boolean":
            sql_field = SQL("COALESCE(%s, FALSE)", sql_field)

        if query._any_value_orderby:
            sql_field = SQL("ANY_VALUE(%s)", sql_field)
        elif query._collect_order_groupby:
            query._order_groupby.append(sql_field)

        return SQL("%s %s %s", sql_field, direction, nulls)

    @api.model
    def _search(
        self,
        domain: DomainType,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        *,
        active_test: bool = True,
        bypass_access: bool = False,
    ) -> Query:
        """Private implementation of :meth:`search`.

        No default order is applied when called without ``order``.

        :return: a :class:`Query` representing the matching records

        May be overridden to modify the domain or post-filter the query. Beware:
        the returned query is not executed by default (it can be injected into a
        domain to generate sub-queries), so post-filtering may hurt performance.

        :param active_test: whether to filter only active records
        :param bypass_access: whether to skip model permission and record-rule
            checks
        """
        prof = _OrmProfile(_orm_read)

        check_access = not (self.env.su or bypass_access)
        if check_access:
            self.browse().check_access("read")
        prof.mark("acl")

        domain = Domain(domain)
        if (
            self._active_name
            and active_test
            and self.env.context.get("active_test", True)
            and not any(
                leaf.field_expr == self._active_name
                for leaf in domain.iter_conditions()
            )
        ):
            domain &= Domain(self._active_name, "=", True)

        domain = domain.optimize_full(self)
        if domain.is_false():
            return self.browse()._as_query()

        if (backend := self.env.backend) is not None:
            return backend.search(self, domain, offset, limit, order)

        query = Query(self.env, self._table, self._table_sql)
        if not domain.is_true():
            query.add_where(domain._to_sql(self, self._table, query))
        prof.mark("domain")

        if check_access:
            self_sudo = self.sudo().with_context(active_test=False)
            sec_domain = self.env["ir.rule"]._compute_domain(self._name, "read")
            sec_domain = sec_domain.optimize_full(self_sudo)
            if sec_domain.is_false():
                return self.browse()._as_query()
            if not sec_domain.is_true():
                query.add_where(sec_domain._to_sql(self_sudo, self._table, query))
        prof.mark("rules")

        if order:
            # Every term may be dropped -- unreadable fields
            # (:meth:`_order_field_to_sql`) or a many2one ordering cycle.  An
            # unordered query makes limit/offset pagination repeat and skip
            # rows, so fall back to the primary key rather than to whatever
            # the database happens to return.  Only here: ``_order_to_sql``
            # also serves read_group, where a bare id would not be in the
            # GROUP BY.
            query.order = self._order_to_sql(order, query) or SQL.identifier(
                self._table, "id"
            )

        if limit is not None and limit is not False:
            query.limit = 1 if limit is True else limit
        if offset is not None and offset is not False:
            query.offset = 1 if offset is True else offset

        prof.stop()
        if prof.debug:
            _orm_read.debug(
                "[%.3f ms] _search %s | acl=%.1f domain=%.1f rules=%.1f query=%.1f",
                prof.elapsed * 1000,
                self._name,
                prof.ms("start", "acl"),
                prof.ms("acl", "domain"),
                prof.ms("domain", "rules"),
                prof.ms("rules", "end"),
            )
        return query

    def _as_query(self, ordered: bool = True) -> Query:
        """Return a :class:`Query` corresponding to the recordset ``self``.

        :param ordered: whether the recordset order must be enforced by the query
        """
        if (backend := self.env.backend) is not None:
            return backend.as_query(self, ordered)
        query = Query(self.env, self._table, self._table_sql)
        query.set_result_ids(self._ids, ordered)
        return query

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
        """Perform a :meth:`search_fetch` followed by a :meth:`_read_format`.

        See :meth:`search` and :meth:`read` for the ``domain``, ``fields``,
        ``offset``, ``limit`` and ``order`` parameters; all default to no
        restriction.

        :param read_kwargs: forwarded to ``read(..., **read_kwargs)``, e.g.
            ``load=''`` to avoid computing display_name
        :return: list of dictionaries containing the requested fields
        """
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

    def _traverse_related_sql(
        self, alias: str, field: Field, query: Query
    ) -> tuple[typing.Any, Field, str]:
        """Traverse the related `field` and add needed join to the `query`.

        :returns: tuple ``(model, field, alias)``, where ``field`` is the last
            field in the sequence, ``model`` is that field's model, and
            ``alias`` is the model's table alias
        """
        if not (field.related and not field.store):
            raise ValueError(
                f"_traverse_related_sql expects a non-stored related field, got {field!r}"
            )
        if not (self.env.su or field.compute_sudo or field.inherited):
            raise ValueError(
                f"Cannot convert {field} to SQL because it is not a sudoed related or inherited field"
            )

        model = self.sudo(self.env.su or field.compute_sudo)
        *path_fnames, last_fname = field.related.split(".")
        for path_fname in path_fnames:
            path_field = model._fields[path_fname]
            if path_field.type != "many2one":
                raise ValueError(
                    f"Cannot convert {field} (related={field.related}) to SQL because {path_fname} is not a Many2one"
                )
            model, alias = path_field.join(model, alias, query)

        return model, model._fields[last_fname], alias

    def _field_to_sql(
        self, alias: str, field_expr: str, query: Query | None = None
    ) -> SQL:
        """Return an :class:`SQL` object that represents the value of the given
        field from the given table alias, in the context of the given query.
        The method also checks that the field is accessible for reading.

        The query object is necessary for inherited fields, many2one fields and
        properties fields, where joins are added to the query.

        A non-stored *related* field is resolved by recursing onto its target,
        so the access check below applies to the target, never to the related
        field's own ``groups``.  Do not "fix" that by checking here first: this
        runs for ORDER BY too, on a **model-level (empty) recordset**, and
        ``_has_field_access`` may be record-sensitive -- ``res.users`` grants
        ``SELF_READABLE_FIELDS`` only when ``self._origin == self.env.user``, so
        an empty recordset fails closed and a user can no longer sort, or open
        the preferences form for, their own record.  Disclosure is blocked at
        the entry points that actually return values instead: domain conditions
        (``DomainCondition._optimize_step``) and read_group
        (``_read_group_select`` / ``_read_group_groupby``).
        """
        fname, property_name = parse_field_expr(field_expr)
        field = self._fields.get(fname)
        if not field:
            raise ValueError(f"Invalid field {fname!r} on model {self._name!r}")

        if field.related and not field.store:
            if query is None:
                raise ValueError(
                    f"query is required to convert related field {field} to SQL"
                )
            model, field, alias = self._traverse_related_sql(alias, field, query)
            related_expr = (
                field.name if not property_name else f"{field.name}.{property_name}"
            )
            return model._field_to_sql(alias, related_expr, query)

        self._check_field_access(field, "read")

        sql = field.to_sql(self, alias)
        if property_name:
            if query is None:
                raise ValueError(
                    f"query is required to convert property field expression"
                    f" {field_expr!r} to SQL"
                )
            sql = field.property_to_sql(sql, property_name, self, alias, query)
        return sql

    @api.private
    def exists(self) -> Self:
        """The subset of records in ``self`` that exist.
        It can be used as a test on records::

            if record.exists():
                ...

        By convention, new records are returned as existing.
        """
        new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
        if not ids:
            return self
        if (backend := self.env.backend) is not None:
            valid_ids = {*backend.existing_ids(self, ids), *new_ids}
            return self.browse(i for i in self._ids if i in valid_ids)
        query = Query(self.env, self._table, self._table_sql)
        query.add_where(
            SQL("%s = ANY(%s)", SQL.identifier(self._table, "id"), list(ids))
        )
        real_ids = (id_ for [id_] in self.env.execute_query(query.select()))
        valid_ids = {*real_ids, *new_ids}
        return self.browse(i for i in self._ids if i in valid_ids)

    @api.private
    def lock_for_update(self, *, allow_referencing: bool = False) -> None:
        """Grab an exclusive write-lock to the rows with the given ids.

        This avoids blocking processing on the records due to concurrent
        modifications. If all records couldn't be locked, a `LockError`
        exception is raised.

        :param allow_referencing: Acquire a row lock which allows for other
            transactions to reference this record. Use only when modifying
            values that are not identifiers.
        :raises: ``LockError`` when some records could not be locked
        """
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
        """Grab an exclusive write-lock on some rows with the given ids.

        Skip locked records and browse the records that could be locked.

        :param allow_referencing: Acquire a row lock which allows for other
            transactions to reference this record. Use only when modifying
            values that are not identifiers.
        :param limit: The maximum number of rows to lock
        :return: The recordset of locked records
        """
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
