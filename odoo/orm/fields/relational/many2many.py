import itertools
import logging
import typing
from collections import defaultdict
from collections.abc import (
    Sequence,
)
from typing import override

from odoo.exceptions import AccessError
from odoo.tools import SQL, OrderedSet, Query, sql, unique
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
        Registry,
    )
    from ...models import BaseModel

    OnDelete = typing.Literal["cascade", "set null", "restrict"]

_schema = logging.getLogger("odoo.schema")


class Many2many(_RelationalMulti):
    """Many2many field; the value of such a field is the recordset.

    :param str comodel_name: name of the target model (string)
        mandatory except in the case of related or extended fields

    :param str relation: optional name of the table that stores the relation in
        the database

    :param str column1: optional name of the column referring to "these" records
        in the table ``relation``

    :param str column2: optional name of the column referring to "those" records
        in the table ``relation``

    The attributes ``relation``, ``column1`` and ``column2`` are optional.
    If not given, names are automatically generated from model names,
    provided ``model_name`` and ``comodel_name`` are different!

    Having several fields with implicit relation parameters on a given model
    with the same comodel is not accepted by the ORM, since those fields would
    use the same table. The ORM prevents two many2many fields from using the
    same relation parameters, except if

    - both fields use the same model, comodel, and relation parameters are
      explicit; or

    - at least one field belongs to a model with ``_auto = False``.

    :param domain: an optional domain to set on candidate values on the
        client side (domain or a python expression that will be evaluated
        to provide domain)

    :param dict context: an optional context to use on the client side when
        handling that field

    :param bool check_company: Mark the field to be verified in
        :meth:`~odoo.models.Model._check_company`. Add a default company
        domain depending on the field attributes.

    """

    type = "many2many"

    _explicit: bool = True  # whether schema is explicitly given
    relation: str | None = None  # name of table
    column1: str | None = None  # column of table referring to model
    column2: str | None = None  # column of table referring to comodel
    ondelete: OnDelete | None = "cascade"  # optional ondelete for the column2 fkey

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

    @override
    def setup_nonrelated(self, model: BaseModel) -> None:
        super().setup_nonrelated(model)
        # only 'cascade'/'restrict' make sense for m2m; reject anything else
        if self.ondelete not in ("cascade", "restrict"):
            raise ValueError(
                f"The m2m field {self.name} of model {model._name} declares its ondelete policy "
                f"as being {self.ondelete!r}. Only 'restrict' and 'cascade' make sense."
            )
        if self.store:
            if not (self.relation and self.column1 and self.column2):
                if not self.relation:
                    self._explicit = False
                # table name is based on the stable alphabetical order of tables
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
            # check validity of table name
            check_pg_name(self.relation)
        else:
            self.relation = self.column1 = self.column2 = None

        if self.relation:
            # check whether other fields use the same schema
            fields = model.pool.many2many_relations[
                self.relation, self.column1, self.column2
            ]
            for mname, fname in fields:
                field = model.pool[mname]._fields[fname]
                if (
                    (field is self)
                    or (  # same model: relation parameters must be explicit
                        self.model_name == field.model_name
                        and self.comodel_name == field.comodel_name
                        and self._explicit
                        and field._explicit
                    )
                    or (  # different models: one model must be _auto=False
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
            # retrieve inverse fields, and link them in field_inverses
            for mname, fname in registry.many2many_relations[
                self.relation, self.column2, self.column1
            ]:
                field = registry[mname]._fields[fname]
                inverses.add(self, field)
                inverses.add(field, self)

    @override
    def update_db(
        self, model: BaseModel, columns: dict[str, dict[str, typing.Any]]
    ) -> bool:
        cr = model.env.cr
        # Do not reflect relations for custom fields, as they do not belong to a
        # module. They are automatically removed when dropping the corresponding
        # 'ir.model.field'.
        if not self.manual:
            model.pool.post_init(
                model.env["ir.model.relation"]._reflect_relation,
                model,
                self.relation,
                self._module,
            )
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
        # relation table already existed: nothing created, no recompute needed
        # (base contract: True == field must be recomputed on existing rows)
        return False

    def update_db_foreign_keys(self, model: BaseModel) -> None:
        """Add the foreign keys corresponding to the field's relation table."""
        comodel = model.env[self.comodel_name]
        if model._is_an_ordinary_table():
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
        if comodel._is_an_ordinary_table():
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
        context = {"active_test": False}
        context.update(self.context)
        comodel = records.env[self.comodel_name].with_context(**context)

        # bypass access during search when _search is overridden, to avoid
        # filtering all comodel records before joining
        filter_access = self.bypass_search_access and is_search_overridden(
            type(comodel)
        )

        # make the query for the lines
        domain = self.get_comodel_domain(records)
        try:
            query = comodel._search(
                domain, order=comodel._order, bypass_access=filter_access
            )
        except AccessError as e:
            raise AccessError(
                records.env._("Failed to read field %s", self) + "\n" + str(e)
            ) from e

        # retrieve pairs (record, line) and group by record
        group = defaultdict(list)
        if (backend := records.env.backend) is not None:
            # In-memory tier: raw pairs come from the backend's pair store; the
            # (backend-served) comodel query above replaces the SQL JOIN — it
            # drops dead/filtered corecord ids and dictates the ordering.
            position = {
                id2: index for index, id2 in enumerate(query.get_result_ids())
            }
            pairs = backend.read_m2m_pairs(
                records, self.relation, self.column1, self.column2, records.ids
            )
            for id1, id2 in pairs:
                if id2 in position:
                    group[id1].append(id2)
            for ids2 in group.values():
                ids2.sort(key=position.__getitem__)
        else:
            # join with many2many relation table
            sql_id1 = SQL.identifier(self.relation, self.column1)
            sql_id2 = SQL.identifier(self.relation, self.column2)
            query.add_join(
                "JOIN",
                self.relation,
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

        # filter using record rules
        if filter_access and group:
            corecord_ids = OrderedSet(id_ for ids in group.values() for id_ in ids)
            accessible_corecords = comodel.browse(corecord_ids)._filtered_access("read")
            if len(accessible_corecords) < len(corecord_ids):
                # some records are inaccessible, remove them from groups
                corecord_ids = set(accessible_corecords._ids)
                for id1, ids in group.items():
                    group[id1] = [id_ for id_ in ids if id_ in corecord_ids]

        # store result in cache
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
        """Persist and propagate the change from *old_relation* to *new_relation*.

        Shared tail of :meth:`write_real` and :meth:`write_new`: refresh self's
        cache, add/remove the ``(record, corecord)`` pairs (writing the relation
        table only when *store*), keep inverse-field caches in sync, and notify
        dependents on the affected corecords. *records* are the (real or new)
        records whose relation changed; ``*_relation`` map each record id to its
        ``OrderedSet`` of corecord ids.
        """
        # update the cache of self
        for record in records:
            self._update_cache(record, tuple(new_relation[record.id]))

        # determine the corecords for which the relation has changed
        modified_corecord_ids = set()

        # process pairs to add (beware of duplicates)
        pairs = [
            (x, y) for x, ys in new_relation.items() for y in ys - old_relation[x]
        ]
        if pairs:
            if store:
                if (backend := records.env.backend) is not None:
                    backend.link_m2m_pairs(
                        records, self.relation, self.column1, self.column2, pairs
                    )
                else:
                    records.env.cr.execute(
                        SQL(
                            "INSERT INTO %s (%s, %s) VALUES %s ON CONFLICT DO NOTHING",
                            SQL.identifier(self.relation),
                            SQL.identifier(self.column1),
                            SQL.identifier(self.column2),
                            SQL(", ").join(pairs),
                        )
                    )

            # update the cache of inverse fields. OrderedSet (not set) keeps the
            # inverse cache deterministic, matching the real-record path.
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

        # process pairs to remove
        pairs = [
            (x, y) for x, ys in old_relation.items() for y in ys - new_relation[x]
        ]
        if pairs:
            y_to_xs = defaultdict(set)
            for x, y in pairs:
                y_to_xs[y].add(x)
                modified_corecord_ids.add(y)

            if store:
                if (backend := records.env.backend) is not None:
                    backend.unlink_m2m_pairs(
                        records, self.relation, self.column1, self.column2, pairs
                    )
                else:
                    # express pairs as the union of cartesian products:
                    #    pairs = [(1, 11), (1, 12), (1, 13), (2, 11), (2, 12), (2, 14)]
                    # -> y_to_xs = {11: {1, 2}, 12: {1, 2}, 13: {1}, 14: {2}}
                    # -> xs_to_ys = {{1, 2}: {11, 12}, {2}: {14}, {1}: {13}}
                    xs_to_ys = defaultdict(set)
                    for y, xs in y_to_xs.items():
                        xs_to_ys[frozenset(xs)].add(y)
                    # delete the rows where (id1 IN xs AND id2 IN ys) OR ...
                    records.env.cr.execute(
                        SQL(
                            "DELETE FROM %s WHERE %s",
                            SQL.identifier(self.relation),
                            SQL(" OR ").join(
                                SQL(
                                    "%s = ANY(%s) AND %s = ANY(%s)",
                                    SQL.identifier(self.column1),
                                    list(xs),
                                    SQL.identifier(self.column2),
                                    list(ys),
                                )
                                for xs, ys in xs_to_ys.items()
                            ),
                        )
                    )

            # update the cache of inverse fields
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
            # trigger the recomputation of fields that depend on the inverse
            # fields of self on the modified corecords
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
        # records_commands_list = [(records, commands), ...]
        if not records_commands_list:
            return

        model = records_commands_list[0][0].browse()
        comodel = model.env[self.comodel_name].with_context(**self.context)
        comodel = self._check_sudo_commands(comodel)

        # determine old and new relation {x: ys}
        ids = OrderedSet(rid for recs, cs in records_commands_list for rid in recs.ids)
        records = model.browse(ids)

        if self.store:
            # on a cache miss `record[self.name]` runs 2 queries (access-rule
            # check + data fetch); `self.read` skips the access-rule query.
            missing_ids = tuple(self._cache_missing_ids(records))
            if missing_ids:
                self.read(records.browse(missing_ids))

        # determine new relation {x: ys}.
        # Read with active_test=False so archived links are part of the delta:
        # a SET/CLEAR must be able to remove archived links too (the cache holds
        # all ids; convert_to_record otherwise filters inactive on read). Mirrors
        # _RelationalMulti.convert_to_write's current-value read.
        old_relation = {
            record.id: OrderedSet(record[self.name]._ids)
            for record in records.with_context(active_test=False)
        }
        new_relation = {x: OrderedSet(ys) for x, ys in old_relation.items()}

        # operations on new relation
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
            # the pairs (x, y) have been cascade-deleted from relation
            for ys1 in old_relation.values():
                ys1 -= ys
            for ys1 in new_relation.values():
                ys1 -= ys

        for recs, commands in records_commands_list:
            to_create = []  # line vals to create
            to_delete = []  # line ids to delete
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
                        # new lines must no longer be linked to records
                        to_create = [
                            (set(ids) - set(recs._ids), vals)
                            for (ids, vals) in to_create
                        ]
                        relation_set(
                            recs._ids,
                            command[2] if command[0] == Command.SET else (),
                        )

            if to_create:
                # create lines in batch, and link them
                lines = comodel.create([vals for ids, vals in to_create])
                for line, (ids, _vals) in zip(lines, to_create, strict=True):
                    relation_add(ids, line.id)

            if to_delete:
                # delete lines in batch
                comodel.browse(to_delete).unlink()
                relation_delete(to_delete)

        # check comodel access of added records
        # we check the su flag of the environment of records, because su may be
        # disabled on the comodel
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
        """Update self on new records."""
        if not records_commands_list:
            return

        model = records_commands_list[0][0].browse()
        comodel = model.env[self.comodel_name].with_context(**self.context)
        comodel = self._check_sudo_commands(comodel)

        def new(id_):
            return id_ and NewId(id_)

        # determine old and new relation {x: ys}
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
                # Each command applies only to the records of its own pair
                # (recs), not to every record in the batch -- mirrors write_real
                # and One2many.write_new. Using new_relation.values() here would
                # cross-contaminate: record A's LINK/CREATE would also land on
                # record B when a single write_new call carries multiple pairs.
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
                        # new lines must no longer be linked to records
                        line_ids = command[2] if command[0] == Command.SET else ()
                        line_ids = OrderedSet(new(line_id) for line_id in line_ids)
                        for id_ in recs._ids:
                            new_relation[id_] = OrderedSet(line_ids)

        if new_relation == old_relation:
            return

        records = model.browse(old_relation)
        # new records: no relation-table writes (store=False), but inverse-field
        # caches and dependents are kept in sync exactly as for real records.
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
        rel_table, rel_id1, rel_id2 = self.relation, self.column1, self.column2
        rel_alias = query.make_alias(alias, self.name)
        if not coquery.where_clause:
            # no constraints on the comodel query: existence in the relation
            # table alone decides the match (same NOT sense as the branch below)
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
