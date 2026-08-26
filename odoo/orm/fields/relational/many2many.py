import itertools
import logging
import typing
from collections import defaultdict
from collections.abc import (
    Sequence,
)
from typing import override

from odoo.db import schema as sql
from odoo.exceptions import AccessError
from odoo.tools import SQL, OrderedSet, Query, unique
from odoo.tools.misc import SENTINEL, Sentinel

from ..._recordset import is_search_overridden
from ...primitives import Command, NewId
from ...validation import check_pg_name
from ..base import Field
from ._base import _RelationalMulti

if typing.TYPE_CHECKING:
    from odoo.tools.misc import Collector

    from ..._typing import (
        CommandValue,
        ModelLike,
        Registry,
    )
    from ...models import BaseModel

    OnDelete = typing.Literal["cascade", "set null", "restrict"]

_schema = logging.getLogger("odoo.schema")


class Many2many(_RelationalMulti):
    type = "many2many"
    is_many2many = True

    _explicit: bool = True
    relation: str | None = None
    column1: str | None = None
    column2: str | None = None
    ondelete: OnDelete | None = "cascade"

    def __init__(
        self,
        comodel_name: str | Sentinel = SENTINEL,
        relation: str | Sentinel = SENTINEL,
        column1: str | Sentinel = SENTINEL,
        column2: str | Sentinel = SENTINEL,
        string: str | Sentinel = SENTINEL,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(
            comodel_name=comodel_name,
            relation=relation,
            column1=column1,
            column2=column2,
            string=string,
            **kwargs,
        )

    def _relation_columns(self) -> tuple[str, str, str]:
        relation, column1, column2 = self.relation, self.column1, self.column2
        assert relation and column1 and column2, (
            f"{self}: row I/O before setup resolved the relation table"
        )
        return relation, column1, column2

    @override
    def setup_nonrelated(self, model: BaseModel) -> None:
        super().setup_nonrelated(model)
        if self.ondelete not in ("cascade", "restrict"):
            raise ValueError(
                f"The m2m field {self.name} of model {model._name} declares its ondelete policy "
                f"as being {self.ondelete!r}. Only 'restrict' and 'cascade' make sense."
            )
        if self.store:
            if not (self.relation and self.column1 and self.column2):
                if not self.relation:
                    self._explicit = False
                comodel = model.env[self.comodel_name]
                if not self.relation:
                    tables = sorted([model._table, comodel._table])
                    assert tables[0] != tables[1], (
                        f"{self}: Implicit/canonical naming of many2many relationship "
                        "table is not possible when source and destination models "
                        "are the same"
                    )
                    self.relation = f"{tables[0]}_{tables[1]}_rel"
                if not self.column1:
                    self.column1 = f"{model._table}_id"
                if not self.column2:
                    self.column2 = f"{comodel._table}_id"
            check_pg_name(self.relation)
        else:
            self.relation = self.column1 = self.column2 = None

        if self.relation:
            fields = model.pool.many2many_relations[
                self.relation, self.column1, self.column2
            ]
            for mname, fname in fields:
                field = model.pool[mname]._fields[fname]
                if (
                    (field is self)
                    or (
                        self.model_name == field.model_name
                        and self.comodel_name == field.comodel_name
                        and self._explicit
                        and field._explicit
                    )
                    or (
                        self.model_name != field.model_name
                        and not (model._auto and model.env[field.model_name]._auto)
                    )
                ):
                    continue
                raise TypeError(
                    f"Many2many fields {self} and {field} use the same table and columns"
                )
            fields.add((self.model_name, self.name))

    @override
    def setup_inverses(
        self, registry: Registry, inverses: Collector[Field, Field]
    ) -> None:
        if self.relation:
            for mname, fname in registry.many2many_relations[
                self.relation, self.column2, self.column1
            ]:
                field = registry[mname]._fields[fname]
                inverses.add(self, field)
                inverses.add(field, self)

    @override
    def update_db(
        self, model: ModelLike, columns: dict[str, dict[str, typing.Any]]
    ) -> bool:
        cr = model.env.cr
        if not self.manual:
            model.pool.add_relation_reflection(model._name, self.relation, self._module)
        comodel = model.env[self.comodel_name]
        if not sql.table_exists(cr, self.relation):
            cr.execute(
                SQL(
                    """ CREATE TABLE %(rel)s (%(id1)s INTEGER NOT NULL,
                                          %(id2)s INTEGER NOT NULL,
                                          PRIMARY KEY(%(id1)s, %(id2)s));
                    COMMENT ON TABLE %(rel)s IS %(comment)s;
                    CREATE INDEX ON %(rel)s (%(id2)s, %(id1)s); """,
                    rel=SQL.identifier(self.relation),
                    id1=SQL.identifier(self.column1),
                    id2=SQL.identifier(self.column2),
                    comment=f"RELATION BETWEEN {model._table} AND {comodel._table}",
                )
            )
            _schema.debug(
                "Create table %r: m2m relation between %r and %r",
                self.relation,
                model._table,
                comodel._table,
            )
            model.pool.post_init(self.update_db_foreign_keys, model)
            return True

        model.pool.post_init(self.update_db_foreign_keys, model)
        return False

    def update_db_foreign_keys(self, model: BaseModel) -> None:
        comodel = model.env[self.comodel_name]
        if model._is_an_ordinary_table() and not model._is_table_inheritance_root():
            model.pool.add_foreign_key(
                self.relation,
                self.column1,
                model._table,
                "id",
                "cascade",
                model,
                self._module,
                force=False,
            )
        if comodel._is_an_ordinary_table() and not comodel._is_table_inheritance_root():
            model.pool.add_foreign_key(
                self.relation,
                self.column2,
                comodel._table,
                "id",
                self.ondelete,
                model,
                self._module,
            )

    @override
    def read(self, records: BaseModel) -> None:
        comodel = records.env[self.comodel_name].with_context(
            **self._get_read_context()
        )

        filter_access = self.bypass_search_access and is_search_overridden(
            type(comodel)
        )

        domain = self.get_comodel_domain(records)
        try:
            query = comodel._search(
                domain, order=comodel._order, bypass_access=filter_access
            )
        except AccessError as e:
            raise AccessError(
                records.env._("Failed to read field %s", self) + "\n" + str(e)
            ) from e

        group = defaultdict(list)
        relation, column1, column2 = self._relation_columns()
        backend = records.env.backend
        if not backend.supports_joined_m2m_read:
            position = {id2: index for index, id2 in enumerate(query.get_result_ids())}
            pairs = backend.read_m2m_pairs(
                records, relation, column1, column2, records.ids
            )
            for id1, id2 in pairs:
                if id2 in position:
                    group[id1].append(id2)
            for ids2 in group.values():
                ids2.sort(key=position.__getitem__)
        else:
            sql_id1 = SQL.identifier(relation, column1)
            sql_id2 = SQL.identifier(relation, column2)
            query.add_join(
                "JOIN",
                relation,
                None,
                SQL(
                    "%s = %s",
                    sql_id2,
                    SQL.identifier(comodel._table, "id"),
                ),
            )
            query.add_where(SQL("%s = ANY(%s)", sql_id1, list(records.ids)))
            for id1, id2 in records.env.execute_query(query.select(sql_id1, sql_id2)):
                group[id1].append(id2)

        if filter_access and group:
            corecord_ids = OrderedSet(id_ for ids in group.values() for id_ in ids)
            accessible_corecords = comodel.browse(corecord_ids)._filtered_access("read")
            if len(accessible_corecords) < len(corecord_ids):
                corecord_ids = set(accessible_corecords._ids)
                for id1, ids in group.items():
                    group[id1] = [id_ for id_ in ids if id_ in corecord_ids]

        values = [tuple(group[id_]) for id_ in records._ids]
        self._insert_cache(records, values)

    def _apply_relation_delta(
        self,
        records: BaseModel,
        comodel: BaseModel,
        old_relation: dict,
        new_relation: dict,
        *,
        store: bool,
    ) -> None:
        for record in records:
            self._update_cache(record, tuple(new_relation[record.id]))

        modified_corecord_ids = set()

        pairs = [(x, y) for x, ys in new_relation.items() for y in ys - old_relation[x]]
        if pairs:
            if store:
                records.env.backend.link_m2m_pairs(
                    records, *self._relation_columns(), pairs
                )

            y_to_xs = defaultdict(OrderedSet)
            for x, y in pairs:
                y_to_xs[y].add(x)
                modified_corecord_ids.add(y)
            for invf in records.pool.field_inverses[self]:
                domain = invf.get_comodel_domain(comodel)
                valid_ids = set(records.filtered_domain(domain)._ids)
                if not valid_ids:
                    continue
                inv_cache = invf._get_cache(comodel.env)
                for y, xs in y_to_xs.items():
                    corecord = comodel.browse((y,))
                    try:
                        ids0 = inv_cache[corecord.id]
                        ids1 = tuple(
                            unique(
                                itertools.chain(ids0, (x for x in xs if x in valid_ids))
                            )
                        )
                        invf._update_cache(corecord, ids1)
                    except KeyError:
                        pass

        pairs = [(x, y) for x, ys in old_relation.items() for y in ys - new_relation[x]]
        if pairs:
            y_to_xs = defaultdict(set)
            for x, y in pairs:
                y_to_xs[y].add(x)
                modified_corecord_ids.add(y)

            if store:
                records.env.backend.unlink_m2m_pairs(
                    records, *self._relation_columns(), pairs
                )

            for invf in records.pool.field_inverses[self]:
                inv_cache = invf._get_cache(comodel.env)
                for y, xs in y_to_xs.items():
                    corecord = comodel.browse((y,))
                    try:
                        ids0 = inv_cache[corecord.id]
                        ids1 = tuple(id_ for id_ in ids0 if id_ not in xs)
                        invf._update_cache(corecord, ids1)
                    except KeyError:
                        pass

        if modified_corecord_ids:
            corecords = comodel.browse(modified_corecord_ids)
            corecords.modified(
                [
                    invf.name
                    for invf in records.pool.field_inverses[self]
                    if invf.model_name == self.comodel_name
                ]
            )

    @override
    def write_real(
        self,
        records_commands_list: Sequence[tuple[BaseModel, list[CommandValue]]],
        create: bool = False,
    ) -> None:
        if not records_commands_list:
            return

        model = records_commands_list[0][0].browse()
        comodel = model.env[self.comodel_name].with_context(**self.context)
        comodel = self._check_sudo_commands(comodel)

        ids = OrderedSet(rid for recs, cs in records_commands_list for rid in recs.ids)
        records = model.browse(ids)

        if self.store:
            missing_ids = tuple(self._cache_missing_ids(records))
            if missing_ids:
                self.read(records.browse(missing_ids))

        old_relation = {
            record.id: OrderedSet(record[self.name]._ids)
            for record in records.with_context(active_test=False)
        }
        new_relation = {x: OrderedSet(ys) for x, ys in old_relation.items()}

        def relation_add(xs, y):
            for x in xs:
                new_relation[x].add(y)

        def relation_remove(xs, y):
            for x in xs:
                new_relation[x].discard(y)

        def relation_set(xs, ys):
            for x in xs:
                new_relation[x] = OrderedSet(ys)

        def relation_delete(ys):
            for ys1 in old_relation.values():
                ys1 -= ys
            for ys1 in new_relation.values():
                ys1 -= ys

        for recs, commands in records_commands_list:
            to_create = []
            to_delete = []
            for command in commands or ():
                if not isinstance(command, (list, tuple)) or not command:
                    continue
                match command[0]:
                    case Command.CREATE:
                        to_create.append((recs._ids, command[2]))
                    case Command.UPDATE:
                        prefetch_ids = recs[self.name]._prefetch_ids
                        comodel.browse(command[1]).with_prefetch(prefetch_ids).write(
                            command[2]
                        )
                    case Command.DELETE:
                        to_delete.append(command[1])
                    case Command.UNLINK:
                        relation_remove(recs._ids, command[1])
                    case Command.LINK:
                        relation_add(recs._ids, command[1])
                    case Command.CLEAR | Command.SET:
                        to_create = [
                            (set(ids) - set(recs._ids), vals)
                            for (ids, vals) in to_create
                        ]
                        relation_set(
                            recs._ids,
                            command[2] if command[0] == Command.SET else (),
                        )

            if to_create:
                lines = comodel.create([vals for ids, vals in to_create])
                for line, (ids, _vals) in zip(lines, to_create, strict=True):
                    relation_add(ids, line.id)

            if to_delete:
                comodel.browse(to_delete).unlink()
                relation_delete(to_delete)

        if not model.env.su:
            try:
                comodel.browse(
                    co_id
                    for rec_id, new_co_ids in new_relation.items()
                    for co_id in new_co_ids - old_relation[rec_id]
                ).check_access("read")
            except AccessError as e:
                raise AccessError(
                    model.env._("Failed to write field %s", self) + "\n" + str(e)
                ) from e

        self._apply_relation_delta(
            records, comodel, old_relation, new_relation, store=self.store
        )

    @override
    def write_new(
        self,
        records_commands_list: Sequence[tuple[BaseModel, list[CommandValue]]],
    ) -> None:
        if not records_commands_list:
            return

        model = records_commands_list[0][0].browse()
        comodel = model.env[self.comodel_name].with_context(**self.context)
        comodel = self._check_sudo_commands(comodel)

        def new(id_):
            return id_ and NewId(id_)

        old_relation = {
            record.id: OrderedSet(record[self.name]._ids)
            for records, _ in records_commands_list
            for record in records
        }
        new_relation = {x: OrderedSet(ys) for x, ys in old_relation.items()}

        for recs, commands in records_commands_list:
            for command in commands:
                if not isinstance(command, (list, tuple)) or not command:
                    continue
                match command[0]:
                    case Command.CREATE:
                        line_id = comodel.new(command[2], ref=command[1]).id
                        for id_ in recs._ids:
                            new_relation[id_].add(line_id)
                    case Command.UPDATE:
                        line_id = new(command[1])
                        comodel.browse([line_id]).update(command[2])
                    case Command.DELETE | Command.UNLINK:
                        line_id = new(command[1])
                        for id_ in recs._ids:
                            new_relation[id_].discard(line_id)
                    case Command.LINK:
                        line_id = new(command[1])
                        for id_ in recs._ids:
                            new_relation[id_].add(line_id)
                    case Command.CLEAR | Command.SET:
                        line_ids = command[2] if command[0] == Command.SET else ()
                        line_ids = OrderedSet(new(line_id) for line_id in line_ids)
                        for id_ in recs._ids:
                            new_relation[id_] = OrderedSet(line_ids)

        if new_relation == old_relation:
            return

        records = model.browse(old_relation)
        self._apply_relation_delta(
            records, comodel, old_relation, new_relation, store=False
        )

    @override
    def _condition_to_sql_relational(
        self,
        model: BaseModel,
        alias: str,
        exists: bool,
        coquery: Query,
        query: Query,
    ) -> SQL:
        if coquery.is_empty():
            return SQL("FALSE") if exists else SQL("TRUE")
        rel_table, rel_id1, rel_id2 = self._relation_columns()
        rel_alias = query.make_alias(alias, self.name)
        if not coquery.where_clause:
            return SQL(
                "%sEXISTS (SELECT 1 FROM %s AS %s WHERE %s = %s)",
                SQL("NOT ") if not exists else SQL.EMPTY,
                SQL.identifier(rel_table),
                SQL.identifier(rel_alias),
                SQL.identifier(rel_alias, rel_id1),
                SQL.identifier(alias, "id"),
            )
        return SQL(
            "%sEXISTS (SELECT 1 FROM %s AS %s WHERE %s = %s AND %s IN %s)",
            SQL("NOT ") if not exists else SQL.EMPTY,
            SQL.identifier(rel_table),
            SQL.identifier(rel_alias),
            SQL.identifier(rel_alias, rel_id1),
            SQL.identifier(alias, "id"),
            SQL.identifier(rel_alias, rel_id2),
            coquery.subselect(),
        )
