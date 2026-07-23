import typing
from collections import defaultdict
from collections.abc import (
    Sequence,
)
from operator import attrgetter
from typing import override

from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, OrderedSet, Query, unique
from odoo.tools.misc import SENTINEL, Sentinel

from ...domain import Domain
from ...primitives import SQL_OPERATORS, Command, NewId
from ..base import Field
from ..reference import Many2oneReference
from ._base import _RelationalMulti
from .many2one import Many2one

if typing.TYPE_CHECKING:
    from odoo.tools.misc import Collector

    from ..._typing import (
        CommandValue,
        Environment,
        Registry,
    )
    from ...models import BaseModel


class One2many(_RelationalMulti):
    """One2many field; the value of such a field is the recordset of all the
    records in ``comodel_name`` such that the field ``inverse_name`` is equal to
    the current record.

    :param str comodel_name: name of the target model

    :param str inverse_name: name of the inverse ``Many2one`` field in
        ``comodel_name``

    :param domain: an optional domain to set on candidate values on the
        client side (domain or a python expression that will be evaluated
        to provide domain)

    :param dict context: an optional context to use on the client side when
        handling that field

    :param bool bypass_search_access: whether access rights are bypassed on the
        comodel (default: ``False``)

    The attributes ``comodel_name`` and ``inverse_name`` are mandatory except in
    the case of related fields or field extensions.
    """

    type = "one2many"

    inverse_name: str | None = None  # name of the inverse field
    copy: bool = False  # o2m are not copied by default
    # whether the inverse m2o is computed — resolved once at setup (registry
    # static) so __get__ need not re-look-up the inverse field on every access
    _inverse_is_computed: bool = False

    def __init__(
        self,
        comodel_name: str | Sentinel = SENTINEL,
        inverse_name: str | Sentinel = SENTINEL,
        string: str | Sentinel = SENTINEL,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(
            comodel_name=comodel_name,
            inverse_name=inverse_name,
            string=string,
            **kwargs,
        )

    @override
    def setup_nonrelated(self, model: BaseModel) -> None:
        super().setup_nonrelated(model)
        if self.inverse_name:
            # link self to its inverse field and vice-versa
            comodel = model.env[self.comodel_name]
            try:
                field = comodel._fields[self.inverse_name]
                field.setup(comodel)
            except KeyError:
                raise ValueError(
                    f"{self.inverse_name!r} declared in {self!r} does not exist on {comodel._name!r}."
                ) from None
            self._inverse_is_computed = bool(field.compute)

    @override
    def setup_inverses(
        self, registry: Registry, inverses: Collector[Field, Field]
    ) -> None:
        if self.inverse_name:
            # link self to its inverse field and vice-versa
            invf = registry[self.comodel_name]._fields[self.inverse_name]
            if isinstance(invf, (Many2one, Many2oneReference)):
                # only m2o inverses are invalidated; integer inverses
                # (res_model/res_id pairs) are not supported
                inverses.add(self, invf)
            inverses.add(invf, self)

    _description_relation_field = property(attrgetter("inverse_name"))

    @override
    def update_db(
        self, model: BaseModel, columns: dict[str, dict[str, typing.Any]]
    ) -> None:
        if self.comodel_name in model.env:
            comodel = model.env[self.comodel_name]
            if self.inverse_name not in comodel._fields:
                raise UserError(
                    model.env._(
                        'No inverse field "%(inverse_field)s" found for "%(comodel)s"',
                        inverse_field=self.inverse_name,
                        comodel=self.comodel_name,
                    )
                )

    def _additional_domain(self, env: Environment) -> Domain:
        if self.comodel_name and self.inverse_name:
            comodel = env.registry[self.comodel_name]
            inverse_field = comodel._fields[self.inverse_name]
            if inverse_field.type == "many2one_reference":
                return Domain(inverse_field.model_field, "=", self.model_name)
        return Domain.TRUE

    @override
    def get_comodel_domain(self, model: BaseModel) -> Domain:
        return super().get_comodel_domain(model) & self._additional_domain(model.env)

    @override
    def _internal_description_domain_raw(self, env: Environment) -> str | list:
        domain = super()._internal_description_domain_raw(env)
        additional_domain = self._additional_domain(env)
        if additional_domain.is_true():
            return domain
        return f"({domain}) + ({additional_domain})"

    @typing.overload
    def __get__(self, records: None, owner: typing.Any = None) -> typing.Self: ...
    @typing.overload
    def __get__(self, records: BaseModel, owner: typing.Any = None) -> BaseModel: ...
    @typing.overload
    def __get__(self, records: object, owner: typing.Any = None) -> typing.Any: ...

    @override
    def __get__(
        self, records: typing.Any, owner: typing.Any = None
    ) -> BaseModel | typing.Self:
        if records is not None and self._inverse_is_computed:
            # force the computation of the (computed) inverse field to ensure
            # that the cache value of self is consistent
            records.env[self.comodel_name]._recompute_model([self.inverse_name])
        return super().__get__(records, owner)

    @override
    def read(self, records: BaseModel) -> None:
        # retrieve the lines in the comodel
        context = {"active_test": False}
        context.update(self.context)
        comodel = records.env[self.comodel_name].with_context(**context)
        inverse = self.inverse_name
        inverse_field = comodel._fields[inverse]

        # optimization: fetch the inverse and active fields with search()
        domain = self.get_comodel_domain(records) & Domain(inverse, "in", records.ids)
        field_names = [inverse]
        if comodel._active_name:
            field_names.append(comodel._active_name)
        try:
            lines = comodel.search_fetch(domain, field_names)
        except AccessError as e:
            raise AccessError(
                records.env._("Failed to read field %s", self) + "\n" + str(e)
            ) from e

        # group lines by inverse field (without prefetching other fields)
        get_id = (lambda rec: rec.id) if inverse_field.type == "many2one" else int
        group = defaultdict(list)
        for line in lines:
            # line[inverse] may be a record or an integer
            group[get_id(line[inverse])].append(line.id)

        # store result in cache
        values = [tuple(group[id_]) for id_ in records._ids]
        self._insert_cache(records, values)

    def _write_nonstored_commands(
        self,
        records: BaseModel,
        records_commands_list: Sequence[tuple[BaseModel, list[CommandValue]]],
        comodel: BaseModel,
        browse_lines: typing.Callable[..., BaseModel],
        update_line: typing.Callable[..., None],
    ) -> None:
        """Apply x2many commands to the cached value of a *non-stored* one2many.

        Shared by :meth:`write_real` and :meth:`write_new`, which differ only in
        how a command's line ids are resolved (real ids vs ``NewId``-wrapped) and
        how a ``Command.UPDATE`` is applied (``write`` vs in-memory ``update``) —
        both injected so the cache-update logic lives in one place.

        :param records: all records being written (the ``unlink`` target set).
        :param browse_lines: ``ids -> recordset`` resolving comodel lines.
        :param update_line: ``(lines, vals) -> None`` applying ``Command.UPDATE``.
        """

        def link(record, lines):
            ids = record[self.name]._ids
            self._update_cache(record, tuple(unique(ids + lines._ids)))

        def unlink(lines):
            for record in records:
                self._update_cache(record, (record[self.name] - lines)._ids)

        for recs, commands in records_commands_list:
            for command in commands or ():
                match command[0]:
                    case Command.CREATE:
                        for record in recs:
                            link(record, comodel.new(command[2], ref=command[1]))
                    case Command.UPDATE:
                        update_line(browse_lines([command[1]]), command[2])
                    case Command.DELETE | Command.UNLINK:
                        unlink(browse_lines([command[1]]))
                    case Command.LINK:
                        link(recs[-1], browse_lines([command[1]]))
                    case Command.CLEAR | Command.SET:
                        # assign the given lines to the last record only
                        self._update_cache(recs, ())
                        lines = browse_lines(
                            command[2] if command[0] == Command.SET else []
                        )
                        self._update_cache(recs[-1], lines._ids)

    @override
    def write_real(
        self,
        records_commands_list: Sequence[tuple[BaseModel, list[CommandValue]]],
        create: bool = False,
    ) -> None:
        """Update real records."""
        # records_commands_list = [(records, commands), ...]
        if not records_commands_list:
            return

        model = records_commands_list[0][0].browse()
        comodel = model.env[self.comodel_name].with_context(**self.context)
        comodel = self._check_sudo_commands(comodel)

        if self.store:
            inverse = self.inverse_name
            to_create = []  # line vals to create
            to_delete = []  # line ids to delete
            to_link = defaultdict(OrderedSet)  # {record: line_ids}
            allow_full_delete = not create

            def unlink(lines):
                if getattr(comodel._fields[inverse], "ondelete", False) == "cascade":
                    to_delete.extend(lines._ids)
                else:
                    lines[inverse] = False

            def flush():
                if to_link:
                    before = {record: record[self.name] for record in to_link}
                if to_delete:
                    # unlink() will remove the lines from the cache
                    comodel.browse(to_delete).unlink()
                    to_delete.clear()
                if to_create:
                    # create() will add the new lines to the cache of records
                    comodel.create(to_create)
                    to_create.clear()
                if to_link:
                    for record, line_ids in to_link.items():
                        lines = comodel.browse(line_ids) - before[record]
                        # linking missing lines should fail
                        lines.mapped(inverse)
                        lines[inverse] = record
                    to_link.clear()

            for recs, commands in records_commands_list:
                for command in commands or ():
                    match command[0]:
                        case Command.CREATE:
                            to_create.extend(
                                dict(command[2], **{inverse: record.id})
                                for record in recs
                            )
                            allow_full_delete = False
                        case Command.UPDATE:
                            prefetch_ids = recs[self.name]._prefetch_ids
                            comodel.browse(command[1]).with_prefetch(
                                prefetch_ids
                            ).write(command[2])
                        case Command.DELETE:
                            to_delete.append(command[1])
                        case Command.UNLINK:
                            unlink(comodel.browse(command[1]))
                        case Command.LINK:
                            to_link[recs[-1]].add(command[1])
                            allow_full_delete = False
                        case Command.CLEAR | Command.SET:
                            line_ids = command[2] if command[0] == Command.SET else []
                            if not allow_full_delete:
                                # in creation mode, don't delete if nothing
                                # was created yet
                                if line_ids:
                                    # equivalent to Command.LINK
                                    if line_ids.__class__ is int:
                                        line_ids = [line_ids]
                                    to_link[recs[-1]].update(line_ids)
                                    allow_full_delete = False
                                continue
                            flush()
                            # assign the given lines to the last record only
                            lines = comodel.browse(line_ids)
                            domain = (
                                self.get_comodel_domain(model)
                                & Domain(inverse, "in", recs.ids)
                                & Domain("id", "not in", lines.ids)
                            )
                            # a SET/CLEAR must detach archived lines too, so
                            # neutralize the implicit active_test filter (an
                            # explicit active condition in the field's own
                            # domain still applies via get_comodel_domain)
                            unlink(
                                comodel.with_context(active_test=False).search(domain)
                            )
                            lines[inverse] = recs[-1]

            flush()

        else:
            ids = OrderedSet(
                rid for recs, cs in records_commands_list for rid in recs._ids
            )
            records = records_commands_list[0][0].browse(ids)
            self._write_nonstored_commands(
                records,
                records_commands_list,
                comodel,
                comodel.browse,
                lambda lines, vals: lines.write(vals),
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

        ids = {record.id for records, _ in records_commands_list for record in records}
        records = model.browse(ids)

        def browse(ids):
            return comodel.browse([id_ and NewId(id_) for id_ in ids])

        # make sure self is in cache
        records[self.name]

        if self.store:
            inverse = self.inverse_name

            # make sure self's inverse is in cache
            inverse_field = comodel._fields[inverse]
            for record in records:
                inverse_field._update_cache(record[self.name], record.id)

            for recs, commands in records_commands_list:
                for command in commands:
                    match command[0]:
                        case Command.CREATE:
                            for record in recs:
                                line = comodel.new(command[2], ref=command[1])
                                line[inverse] = record
                        case Command.UPDATE:
                            browse([command[1]]).update(command[2])
                        case Command.DELETE | Command.UNLINK:
                            browse([command[1]])[inverse] = False
                        case Command.LINK:
                            browse([command[1]])[inverse] = recs[-1]
                        case Command.CLEAR:
                            # reset the removed lines' inverse (same path as
                            # DELETE) before dropping them from self's cache,
                            # so the pseudo-record graph stays coherent during
                            # onchange
                            for record in recs:
                                if removed := record[self.name]:
                                    removed[inverse] = False
                            self._update_cache(recs, ())
                        case Command.SET:
                            # assign the given lines to the last record only
                            last, lines = recs[-1], browse(command[2])
                            for record in recs:
                                if removed := record[self.name] - lines:
                                    removed[inverse] = False
                            self._update_cache(recs, ())
                            self._update_cache(last, lines._ids)
                            inverse_field._update_cache(lines, last.id)

        else:
            self._write_nonstored_commands(
                records,
                records_commands_list,
                comodel,
                browse,
                lambda lines, vals: lines.update(vals),
            )

    @override
    def _get_query_for_condition_value(
        self,
        model: BaseModel,
        comodel: BaseModel,
        operator: str,
        value: Domain | Query,
    ) -> Query:
        inverse_field = comodel._fields[self.inverse_name]
        if inverse_field not in comodel.env.registry.not_null_fields:
            # exclude NULLs from the subquery: a NULL makes the IN test NULL
            # instead of FALSE, discarding expected results -- e.g.
            # "id NOT IN (42, NULL)" is never TRUE.
            if isinstance(value, Domain):
                value &= Domain(inverse_field.name, "not in", {False})
            else:
                coquery = super()._get_query_for_condition_value(
                    model, comodel, operator, value
                )
                coquery.add_where(
                    SQL(
                        "%s IS NOT NULL",
                        comodel._field_to_sql(
                            coquery.table, inverse_field.name, coquery
                        ),
                    )
                )
                return coquery
        return super()._get_query_for_condition_value(model, comodel, operator, value)

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
            return Domain(not exists)._to_sql(model, alias, query)

        comodel = model.env[self.comodel_name].sudo()
        inverse_field = comodel._fields[self.inverse_name]
        if not inverse_field.store:
            # non-stored inverse: read it in Python instead of SQL (a subquery
            # from arbitrary compute code is not feasible)
            recs = comodel.browse(coquery).with_context(prefetch_fields=False)
            if inverse_field.relational:
                inverses = inverse_field.__get__(recs)
            else:
                # int values, map them
                inverses = model.browse(inverse_field.__get__(rec) for rec in recs)
            subselect = inverses._as_query(ordered=False).subselect()
            return SQL(
                "%s%s%s",
                SQL.identifier(alias, "id"),
                SQL_OPERATORS["in" if exists else "not in"],
                subselect,
            )

        subselect = coquery.subselect(
            SQL(
                "%s AS __inverse",
                comodel._field_to_sql(coquery.table, inverse_field.name, coquery),
            )
        )
        return SQL(
            "%sEXISTS(SELECT FROM %s AS __sub WHERE __inverse = %s)",
            SQL.EMPTY if exists else SQL("NOT "),
            subselect,
            SQL.identifier(alias, "id"),
        )
