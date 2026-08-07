"""SQL query construction: the primitives both reading and searching need.

These eight methods were on :class:`~odoo.orm.models.mixins.search.SearchMixin`,
and they were the whole of the last cycle left in the mixin graph. ``read`` needs
``_search`` / ``_as_query`` / ``_field_to_sql`` / ``exists`` to turn a domain into
rows; ``search`` needs ``_fetch_query`` / ``_determine_fields_to_fetch`` /
``fields_get`` from ``read`` to implement ``search_fetch`` and ``search_read``.
So the two mixins each called into the other and neither could be read in
dependency order (``tooling/architecture/mixin_coupling_check.py``).

The tangle was not really "read vs search" — it was that *query construction* is
a third concern that both build on, with no home of its own. Given one, the
dependency straightens out: ``read`` and ``search`` both sit above this module,
``search`` still sits above ``read``, and nothing points back up.

Membership is not a judgement call: it is the transitive closure, inside
``search.py``, of the four members ``read`` reached for. That closure needs
nothing from ``read`` or ``search`` — only ``_metadata``, ``access``, ``env``
and ``iteration`` — which is why it can be a leaf at all.

``search`` keeps everything that is *searching* rather than query-building:
``search``, ``search_count``, ``search_fetch``, ``search_read``, ``name_search``,
the ``_search_display_name*`` family, and the row locks.
"""

import logging
import typing
from typing import Self

from odoo.exceptions import UserError
from odoo.libs.profiling import _OrmProfile
from odoo.tools import SQL, Query, partition
from odoo.tools.translate import _

from ... import decorators as api
from ..._typing import DomainType
from ...constants import SQL_ORDER_DIR, SQL_ORDER_NULLS
from ...domain import Domain
from ...parsing import parse_field_expr, regex_order
from ...primitives import NewId
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from ...fields.base import Field

_logger = logging.getLogger("odoo.models")
_orm_read = logging.getLogger("odoo.orm.read")


class _QueryMixin(_ModelStubs):
    """Domain-to-SQL construction shared by the read and search paths."""

    __slots__ = ()

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
            # Consult the capability rather than trusting the tier: this returns
            # before the ir.rule block below, so a backend that does NOT enforce
            # record rules must not be handed a rule-checked search silently.
            # Today only the in-memory tier reaches here and it declares False;
            # the assertion is what keeps a future backend from inheriting the
            # bypass by default.
            if check_access and not backend.supports_record_rules:
                raise NotImplementedError(
                    f"{type(backend).__name__} does not enforce ir.rule record "
                    f"rules, so it cannot serve an access-checked search on "
                    f"{self._name}. Use a database-backed test tier, or pass "
                    f"bypass_access=True if the caller is genuinely trusted."
                )
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
