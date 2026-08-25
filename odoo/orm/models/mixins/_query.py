import logging
import typing
from collections import defaultdict
from typing import Self

from odoo.exceptions import AccessError, UserError
from odoo.libs.profiling import _OrmProfile
from odoo.tools import SQL, Query, ormcache, partition
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

    @api.model
    @ormcache("field_name", "self.env.su", "self.env.user._get_group_ids()")
    def _is_field_sortable(self, field_name: str) -> bool:
        """Whether this user may order on `field_name`.

        Answering it means composing the ORDER BY term, which for a related or
        delegated field walks the relation and builds a JOIN. `fields_get`
        asks for every field it describes and a search view asks for every
        field on the model -- 160 on res.users, 102 of them delegated to
        res.partner -- so the same JOINs were composed on every view load.

        The answer moves with the registry and with field access, never with
        the record, so it is keyed on the group set: measured over four models
        and three kinds of user, only group membership ever changed it.
        `ir.model.fields` and `ir.model.access` both clear the `stable` cache,
        which covers this one.
        """
        try:
            query = self._as_query(ordered=False)
            term = self._order_field_to_sql(
                self._table, field_name, SQL.EMPTY, SQL.EMPTY, query
            )
        except ValueError, AccessError, NotImplementedError:
            return False
        return bool(term)

    @api.model
    @ormcache("field_name", "self.env.su", "self.env.user._get_group_ids()")
    def _is_field_groupable(self, field_name: str) -> bool:
        """Whether this user may group by `field_name`. See `_is_field_sortable`."""
        field = self._fields[field_name]
        groupby = field_name if not field.is_temporal else f"{field_name}:month"
        try:
            query = self._as_query(ordered=False)
            self._read_group_groupby(self._table, groupby, query)
        except ValueError, AccessError, NotImplementedError:
            return False
        return True

    def _order_field_to_sql(
        self,
        alias: str,
        field_name: str,
        direction: SQL,
        nulls: SQL,
        query: Query,
    ) -> SQL:
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

        if field.is_many2one:
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
        if field.is_boolean:
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

        backend = self.env.backend
        if check_access and not backend.supports_record_rules:
            raise NotImplementedError(
                f"{type(backend).__name__} does not enforce ir.rule record "
                f"rules, so it cannot serve an access-checked search on "
                f"{self._name}. Use a database-backed test tier, or pass "
                f"bypass_access=True if the caller is genuinely trusted."
            )
        return backend.search(
            self, domain, offset, limit, order, check_access=check_access, prof=prof
        )

    def _search_sql(
        self,
        domain: Domain,
        offset: int | None,
        limit: int | None,
        order: str | None,
        *,
        check_access: bool,
        prof: typing.Any = None,
    ) -> Query:
        if prof is None:
            prof = _OrmProfile(_orm_read)
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
            query.order = self._order_to_sql(order, query) or SQL.identifier(
                self._table, "id"
            )

        if limit is not None and limit is not False:
            query.limit = 1 if limit is True else limit
        if offset is not None and offset is not False:
            query.offset = 1 if offset is True else offset

        prof.stop("query")
        prof.report(_orm_read, "_search %s", self._name)
        return query

    def _as_query(self, ordered: bool = True) -> Query:
        return self.env.backend.as_query(self, ordered)

    def _as_query_sql(self, ordered: bool = True) -> Query:
        query = Query(self.env, self._table, self._table_sql)
        query.set_result_ids(self._ids, ordered)
        return query

    def _read_m2m_pairs_sql(
        self, relation: str, column1: str, column2: str, ids: typing.Collection[int]
    ) -> list[tuple[int, int]]:
        sql_id1 = SQL.identifier(relation, column1)
        sql_id2 = SQL.identifier(relation, column2)
        rows = self.env.execute_query(
            SQL(
                "SELECT %s, %s FROM %s WHERE %s = ANY(%s)",
                sql_id1,
                sql_id2,
                SQL.identifier(relation),
                sql_id1,
                list(ids),
            )
        )
        return [(id1, id2) for id1, id2 in rows]

    def _link_m2m_pairs_sql(
        self,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        self.env.cr.execute(
            SQL(
                "INSERT INTO %s (%s, %s) VALUES %s ON CONFLICT DO NOTHING",
                SQL.identifier(relation),
                SQL.identifier(column1),
                SQL.identifier(column2),
                SQL(", ").join(pairs),
            )
        )

    def _unlink_m2m_pairs_sql(
        self,
        relation: str,
        column1: str,
        column2: str,
        pairs: typing.Iterable[tuple[int, int]],
    ) -> None:
        xs_to_ys: dict[frozenset, set] = defaultdict(set)
        y_to_xs: dict[typing.Any, set] = defaultdict(set)
        for x, y in pairs:
            y_to_xs[y].add(x)
        for y, xs in y_to_xs.items():
            xs_to_ys[frozenset(xs)].add(y)
        self.env.cr.execute(
            SQL(
                "DELETE FROM %s WHERE %s",
                SQL.identifier(relation),
                SQL(" OR ").join(
                    SQL(
                        "%s = ANY(%s) AND %s = ANY(%s)",
                        SQL.identifier(column1),
                        list(xs),
                        SQL.identifier(column2),
                        list(ys),
                    )
                    for xs, ys in xs_to_ys.items()
                ),
            )
        )

    def _traverse_related_sql(
        self, alias: str, field: Field, query: Query
    ) -> tuple[typing.Any, Field, str]:
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
            if not path_field.is_many2one:
                raise ValueError(
                    f"Cannot convert {field} (related={field.related}) to SQL because {path_fname} is not a Many2one"
                )
            model, alias = path_field.join(model, alias, query)

        return model, model._fields[last_fname], alias

    def _field_to_sql(
        self, alias: str, field_expr: str, query: Query | None = None
    ) -> SQL:
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
        new_ids, ids = partition(lambda i: isinstance(i, NewId), self._ids)
        if not ids:
            return self
        valid_ids = {*self.env.backend.existing_ids(self, ids), *new_ids}
        return self.browse(i for i in self._ids if i in valid_ids)

    def _existing_ids_sql(self, ids: typing.Iterable[int]) -> set[int]:
        ids = list(ids)
        query = Query(self.env, self._table, self._table_sql)
        query.add_where(SQL("%s = ANY(%s)", SQL.identifier(self._table, "id"), ids))
        return {id_ for [id_] in self.env.execute_query(query.select())}
