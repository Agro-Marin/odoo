import itertools
import typing
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Reversible,
    Sequence,
)
from operator import attrgetter
from typing import override

from odoo.exceptions import MissingError
from odoo.libs.constants import PREFETCH_MAX
from odoo.tools import SQL, OrderedSet, Query, unique
from odoo.tools.misc import PENDING, SENTINEL, unquote

from ..._recordset import is_recordset
from ...domain import Domain
from ...domain.constants import SUBDOMAIN_OPERATORS
from ...primitives import COLLECTION_TYPES, Command, NewId
from ..base import Field, _logger


def _domain_depend_paths(domain: Domain) -> Iterator[str]:
    """Yield the dotted field paths a field ``domain`` depends on, descending
    into ``any`` / ``not any`` sub-domains.

    :meth:`Domain.iter_conditions` does not recurse, so an ``any`` condition
    ``('partner_id', 'any', [('country_id', '=', x)])`` would contribute only
    ``partner_id`` and miss ``partner_id.country_id``. Recursing makes dependency
    tracking independent of whether the domain uses the ``any`` or the dotted
    form. ``any!`` values that are SQL/Query rather than sub-domains are skipped.
    """
    for condition in domain.iter_conditions():
        yield condition.field_expr
        value = condition.value
        if isinstance(value, Domain):
            subdomain = value
        elif condition.operator in SUBDOMAIN_OPERATORS and isinstance(
            value, (list, tuple)
        ):
            subdomain = Domain(value, internal=True)
        else:
            continue
        for sub_path in _domain_depend_paths(subdomain):
            yield f"{condition.field_expr}.{sub_path}"


if typing.TYPE_CHECKING:
    from odoo.tools.misc import Collector

    from ..._typing import (
        CommandValue,
        ContextType,
        DomainType,
        Environment,
        Registry,
    )
    from ...models import BaseModel

    OnDelete = typing.Literal["cascade", "set null", "restrict"]


class _Relational(Field["BaseModel"]):
    """Abstract class for relational fields."""

    relational: typing.Literal[True] = True
    comodel_name: str
    domain: DomainType = []  # domain for searching values
    context: ContextType = {}  # context for searching values
    bypass_search_access: bool = (
        False  # whether access rights are bypassed on the comodel
    )
    check_company: bool = False

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
        # base case: do the regular access
        if records is None or len(records._ids) <= 1:
            return super().__get__(records, owner)

        # Inlined ACL short-circuit (matches _make_scalar_get): skip
        # _check_field_access for an ungrouped field or superuser, the common case.
        env = records.env
        if not (not self.groups or env.su or records._has_field_access(self, "read")):
            records._check_field_access(self, "read")

        # multi-record case
        if self.is_stored_computed and env._core.has_pending_field(self):
            # pending-guard: skip recompute on the common no-pending path
            self.recompute(records)

        # get the cache
        field_cache = self._get_cache(env)

        # Retrieve values from cache and fetch missing ones. Reading each with a
        # plain subscript keeps the no-miss case cheap (a genuine miss raises
        # KeyError, handled below). PENDING can only sit in cache for a stored
        # computed field, so the guard short-circuits away for a plain many2one.
        check_pending = self.is_stored_computed
        vals = []
        _append = vals.append
        for record_id in records._ids:
            try:
                value = field_cache[record_id]
            except KeyError:
                pass
            else:
                if not (check_pending and value is PENDING):
                    _append(value)
                    continue
                # A stored computed field can leave PENDING in cache when its
                # compute skipped this record. Mirror base Field.__get__: evict
                # the sentinel so the fetch below sees a genuine miss (never
                # leaking PENDING into the recordset), and fall back to the falsy
                # default while the field is being computed.
                field_cache.pop(record_id, None)
                record = records.browse(record_id)
                if env.is_protected(self, record):
                    value = self.convert_to_cache(False, record, validate=False)
                    self._update_cache(record, value)
                    _append(value)
                    continue
            # cache miss (or a PENDING value still awaiting recompute): fetch it
            if self.store and record_id and len(vals) < len(records) - PREFETCH_MAX:
                # a lot of missing records, just fetch that field
                remaining = records[len(vals) :]
                remaining.fetch([self.name])
                # re-resolve: fetch() flushes/recomputes, which can call
                # env.invalidate_all() and detach the per-field dict captured
                # above (mirrors base Field.__get__ after _fetch_field).
                field_cache = self._get_cache(env)
                # fetch does not raise MissingError, check value
                if record_id not in field_cache:
                    raise MissingError(
                        "\n".join(
                            [
                                env._("Record does not exist or has been deleted."),
                                env._(
                                    "(Record: %(record)s, User: %(user)s)",
                                    record=record_id,
                                    user=env.uid,
                                ),
                            ]
                        )
                    ) from None
            else:
                remaining = object.__new__(records.__class__)
                remaining.env = env
                remaining._ids = (record_id,)
                remaining._prefetch_ids = records._prefetch_ids
                super().__get__(remaining, owner)
                # re-resolve: the singleton fetch above can likewise flush and
                # detach the captured dict.
                field_cache = self._get_cache(env)
            # we have the record now
            _append(field_cache[record_id])

        return self.convert_to_record_multi(vals, records)

    def _update_inverse(self, records: BaseModel, value: BaseModel) -> None:
        """Update the cached value of ``self`` for ``records`` with ``value``."""
        raise NotImplementedError

    def convert_to_record_multi(self, values: list, records: BaseModel) -> BaseModel:
        """Convert cache-format values to record format in batch."""
        raise NotImplementedError

    @override
    def setup_nonrelated(self, model: BaseModel) -> None:
        super().setup_nonrelated(model)
        assert self.comodel_name in model.pool, (
            f"Field {self} with unknown comodel_name {self.comodel_name or '???'!r}"
        )

    def setup_inverses(
        self, registry: Registry, inverses: Collector[Field, Field]
    ) -> None:
        """Populate ``inverses`` with ``self`` and its inverse fields."""

    def get_comodel_domain(self, model: BaseModel) -> Domain:
        """Return a domain from the domain attribute."""
        domain = self.domain
        if callable(domain):
            # the callable can return either a list, Domain or a string
            domain = domain(model)
        if not domain or isinstance(domain, str):
            # no domain, or a str domain (client-side only) -> match all
            return Domain.TRUE
        return Domain(domain)

    @property
    def _related_domain(self) -> DomainType | None:
        def validated(domain):
            if isinstance(domain, str) and not self.inherited:
                # string domains are expressions that are not valid for self's model
                return None
            return domain

        if callable(self.domain):
            # will be called with another model than self's
            return lambda recs: validated(self.domain(recs.env[self.model_name]))  # pylint: disable=not-callable
        else:
            return validated(self.domain)

    _related_context = property(attrgetter("context"))

    _description_relation = property(attrgetter("comodel_name"))
    _description_context = property(attrgetter("context"))

    def _description_domain(self, env: Environment) -> str | list:
        domain = self._internal_description_domain_raw(env)
        if self.check_company:
            field_to_check = None
            if self.company_dependent:
                cids = "[allowed_company_ids[0]]"
            elif self.model_name == "res.company":
                # when using check_company=True on a field on 'res.company', the
                # company_id comes from the id of the current record
                cids = "[id]"
            elif "company_id" in env[self.model_name]:
                cids = "[company_id]"
                field_to_check = "company_id"
            elif "company_ids" in env[self.model_name]:
                cids = "company_ids"
                field_to_check = "company_ids"
            else:
                _logger.warning(
                    env._(
                        "Couldn't generate a company-dependent domain for field %s. "
                        "The model doesn't have a 'company_id' or 'company_ids' field, and isn't company-dependent either.",
                        self.model_name + "." + self.name,
                    )
                )
                return domain
            company_domain = env[self.comodel_name]._check_company_domain(
                companies=unquote(cids)
            )
            if not field_to_check:
                return f"{company_domain} + {domain or []}"
            else:
                no_company_domain = env[self.comodel_name]._check_company_domain(
                    companies=""
                )
                return f"({field_to_check} and {company_domain} or {no_company_domain}) + ({domain or []})"
        return domain

    def _description_allow_hierarchy_operators(self, env: Environment) -> bool:
        """Return if the child_of/parent_of makes sense on this field."""
        comodel = env[self.comodel_name]
        return comodel._parent_name in comodel._fields

    def _internal_description_domain_raw(self, env: Environment) -> str | list:
        domain = self.domain
        if callable(domain):
            domain = domain(env[self.model_name])
        if isinstance(domain, Domain):
            domain = list(domain)
        return domain or []

    @override
    def filter_function(
        self,
        records: BaseModel,
        field_expr: str,
        operator: str,
        value: typing.Any,
    ) -> Callable[[BaseModel], bool]:
        getter = self.expression_getter(field_expr)

        if (self.bypass_search_access or operator == "any!") and not records.env.su:
            # bypass access: search corecords with sudo plus a context key that
            # un-sudoes the env before evaluating sub-domains.
            expr_getter = getter
            sudo_env = records.sudo().with_context(filter_function_reset_sudo=True).env
            getter = lambda rec: expr_getter(rec.with_env(sudo_env))  # noqa: E731

        corecords = getter(records)
        if operator in ("any", "any!"):
            assert isinstance(value, Domain)
            if operator == "any" and records.env.context.get(
                "filter_function_reset_sudo"
            ):
                corecords = corecords.sudo(False)._filtered_access("read")
            corecords = corecords.filtered_domain(value)
        elif operator == "in" and isinstance(value, COLLECTION_TYPES):
            value = set(value)
            if False in value:
                if not corecords:
                    # shortcut, we know none of records has a corecord
                    return lambda _: True
                if len(value) > 1:
                    value.discard(False)
                    filter_values = self.filter_function(
                        records, field_expr, "in", value
                    )
                    return lambda rec: not getter(rec) or filter_values(rec)
                return lambda rec: not getter(rec)
            corecords = corecords.filtered_domain(Domain("id", "in", value))
        else:
            corecords = corecords.filtered_domain(Domain("id", operator, value))

        if not corecords:
            return lambda _: False

        ids = set(corecords._ids)
        # ``getter(rec)._ids`` reads the whole related set's ids in one shot;
        # iterating ``getter(rec)`` would allocate a singleton recordset per
        # corecord (M×K objects) only to re-read the same ids.
        return lambda rec: not ids.isdisjoint(getter(rec)._ids)


class _RelationalMulti(_Relational):
    r"Abstract class for relational fields \*2many."

    write_sequence = 20

    # important: the cache holds the ids of all records in the relation,
    # including inactive ones; convert_to_record() filters them out depending
    # on the context.

    @override
    def _update_inverse(self, records: BaseModel, value: BaseModel) -> None:
        new_id = value.id
        assert not new_id, "Field._update_inverse can only be called with a new id"
        field_cache = self._get_cache(records.env)
        for record_id in records._ids:
            assert not record_id, (
                "Field._update_inverse can only be called with new records"
            )
            cache_value = field_cache.get(record_id, SENTINEL)
            if cache_value is SENTINEL:
                records.env._core.add_patch(self, record_id, new_id)
            else:
                field_cache[record_id] = tuple(unique(cache_value + (new_id,)))

    @override
    def _update_cache(
        self, records: BaseModel, cache_value: typing.Any, dirty: bool = False
    ) -> None:
        field_patches = records.env._core.get_patches(self)
        # Take the per-record path only when some of *records* actually carry a
        # deferred patch; a patch for an unrelated record must not force every
        # bulk x2many cache write for this field onto the slow path.
        if field_patches and not field_patches.keys().isdisjoint(records._ids):
            for record in records:
                ids = field_patches.pop(record.id, ())
                if ids:
                    value = tuple(unique(itertools.chain(cache_value, ids)))
                else:
                    value = cache_value
                super()._update_cache(record, value, dirty)
            return
        super()._update_cache(records, cache_value, dirty)

    @override
    def convert_to_cache(
        self, value: typing.Any, record: BaseModel, validate: bool = True
    ) -> tuple[int | NewId, ...]:
        # cache format: tuple(ids)
        if is_recordset(value):
            if validate and value._name != self.comodel_name:
                raise ValueError(f"Wrong value for {self}: {value}")
            ids = value._ids
            if record and not record.id:
                # x2many field value of new record is new records
                ids = tuple(it and NewId(it) for it in ids)
            return ids

        elif isinstance(value, (list, tuple)):
            # value is a list/tuple of commands, dicts or record ids
            comodel = record.env[self.comodel_name]
            # if record is new, the field's value is new records
            if record and not record.id:

                def browse(it):
                    return comodel.browse((it and NewId(it),))
            else:
                browse = comodel.browse
            # take the current value of a real record (or new record with
            # origin). Read with active_test=False so archived lines survive:
            # the cache must include inactive ids (see class docstring);
            # convert_to_record filters them on read.
            if record._origin:
                ids = OrderedSet(record.with_context(active_test=False)[self.name]._ids)
            else:
                ids = OrderedSet()
            # modify ids with the commands
            for command in value:
                if isinstance(command, (tuple, list)):
                    match command[0]:
                        case Command.CREATE:
                            ids.add(comodel.new(command[2], ref=command[1]).id)
                        case Command.UPDATE:
                            line = browse(command[1])
                            if validate:
                                line.update(command[2])
                            else:
                                line._update_cache(command[2], validate=False)
                            ids.add(line.id)
                        case Command.DELETE | Command.UNLINK:
                            ids.discard(browse(command[1]).id)
                        case Command.LINK:
                            ids.add(browse(command[1]).id)
                        case Command.CLEAR:
                            ids.clear()
                        case Command.SET:
                            ids = OrderedSet(browse(it).id for it in command[2])
                elif isinstance(command, dict):
                    ids.add(comodel.new(command).id)
                else:
                    ids.add(browse(command).id)
            # return result as a tuple
            return tuple(ids)

        elif not value:
            return ()

        raise ValueError(f"Wrong value for {self}: {value}")

    def _make_corecords(
        self, env: Environment, ids: tuple[int | NewId, ...], prefetch_ids: typing.Any
    ) -> BaseModel:
        """Build a corecord recordset from raw *ids* without going through
        ``type.__call__``, dropping inactive corecords when ``active_test`` is on.

        The cache holds the ids of all records in the relation (including
        inactive ones); the active filter is applied here, once, so the two
        ``convert_to_record*`` entry points cannot drift.
        """
        Comodel = env.registry[self.comodel_name]
        corecords = object.__new__(Comodel)  # bypass type.__call__ dispatch
        corecords.env = env
        corecords._ids = ids
        corecords._prefetch_ids = prefetch_ids
        if Comodel._active_name and self.context.get(
            "active_test", env.context.get("active_test", True)
        ):
            corecords = corecords.filtered(Comodel._active_name).with_prefetch(
                prefetch_ids
            )
        return corecords

    @override
    def convert_to_record(
        self, value: tuple[int | NewId, ...], record: BaseModel
    ) -> BaseModel:
        return self._make_corecords(record.env, value, PrefetchX2many(record, self))

    def convert_to_record_multi(
        self, values: list[tuple[int | NewId, ...]], records: BaseModel
    ) -> BaseModel:
        # flatten the per-record id tuples into one de-duplicated recordset
        ids = tuple(unique(id_ for ids in values for id_ in ids))
        return self._make_corecords(records.env, ids, PrefetchX2many(records, self))

    @override
    def convert_to_read(
        self, value: BaseModel, record: BaseModel, use_display_name: bool = True
    ) -> list[int]:
        return value.ids

    @override
    def convert_to_write(
        self, value: typing.Any, record: BaseModel
    ) -> list[CommandValue] | typing.Literal[False]:
        if isinstance(value, tuple):
            # a tuple of ids, this is the cache format
            value = record.env[self.comodel_name].browse(value)

        if is_recordset(value) and value._name == self.comodel_name:

            def get_origin(val):
                return val._origin if hasattr(val, "_origin") else val

            # make result with new and existing records
            inv_names = {field.name for field in record.pool.field_inverses[self]}
            result = [Command.set([])]
            # loop var is ``rec``: the ``record`` param is still the env/pool holder
            for rec in value:
                origin = rec._origin
                if not origin:
                    values = rec._convert_to_write(
                        {
                            # snapshot field names: reading ``rec[name]`` /
                            # ``origin[name]`` below can fetch+prefetch and insert
                            # new field keys into the live cache dict that
                            # ``rec._cache`` iterates ("dictionary changed size").
                            name: rec[name]
                            for name in tuple(rec._cache)
                            if name not in inv_names
                        }
                    )
                    result.append(Command.create(values))
                else:
                    result[0][2].append(origin.id)
                    if rec != origin:
                        values = rec._convert_to_write(
                            {
                                # snapshot field names (see note above): the
                                # ``origin[name]`` read fetches the origin and
                                # mutates the cache dict being iterated.
                                name: val
                                for name in tuple(rec._cache)
                                if name not in inv_names
                                and get_origin(val := rec[name]) != origin[name]
                            }
                        )
                        if values:
                            result.append(Command.update(origin.id, values))
            return result

        if value is False or value is None:
            return [Command.clear()]

        if isinstance(value, list):
            return value

        raise ValueError(f"Wrong value for {self}: {value}")

    @override
    def convert_to_export(self, value: BaseModel, record: BaseModel) -> str:
        return ",".join(value.mapped("display_name")) if value else ""

    @override
    def convert_to_display_name(
        self, value: BaseModel, record: BaseModel
    ) -> str | typing.Literal[False]:
        raise NotImplementedError

    @override
    def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
        depends, depends_context = super().get_depends(model)
        if not self.compute and isinstance(domain := self.domain, (list, Domain)):
            domain = Domain(domain)
            depends = unique(
                itertools.chain(
                    depends,
                    (self.name + "." + path for path in _domain_depend_paths(domain)),
                )
            )
        return depends, depends_context

    @override
    def create(self, record_values: Collection[tuple[BaseModel, typing.Any]]) -> None:
        """Write the value of ``self`` on the given records, which have just
        been created.

        :param record_values: a list of pairs ``(record, value)``, where
            ``value`` is in the format of method :meth:`BaseModel.write`
        """
        self.write_batch(record_values, True)

    @override
    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        # discard recomputation of self on records
        records.env.remove_to_compute(self, records)
        self.write_batch([(records, value)])

    def write_batch(
        self,
        records_commands_list: Sequence[tuple[BaseModel, typing.Any]],
        create: bool = False,
    ) -> None:
        # Normalise into a fresh list of (records, [Command, ...]); never mutate
        # the caller's argument in place (it is typed read-only and may be reused).
        normalized: list[tuple[BaseModel, list]] = []
        for recs, value in records_commands_list:
            if isinstance(value, tuple):
                value = [Command.set(value)]
            elif is_recordset(value) and value._name == self.comodel_name:
                value = [Command.set(value._ids)]
            elif value is False or value is None:
                value = [Command.clear()]
            elif (
                isinstance(value, list)
                and value
                and not isinstance(value[0], (tuple, list))
            ):
                value = [Command.set(tuple(value))]
            if not isinstance(value, list):
                raise ValueError(f"Wrong value for {self}: {value}")
            normalized.append((recs, value))

        if not normalized:
            return

        record_ids = {rid for recs, cs in normalized for rid in recs._ids}
        if all(record_ids):
            self.write_real(normalized, create)
        else:
            assert not any(record_ids), (
                f"{normalized} contains a mix of real and new records. It is not supported."
            )
            self.write_new(normalized)

    def write_real(
        self,
        records_commands_list: Sequence[tuple[BaseModel, list[CommandValue]]],
        create: bool = False,
    ) -> None:
        raise NotImplementedError

    def write_new(
        self,
        records_commands_list: Sequence[tuple[BaseModel, list[CommandValue]]],
    ) -> None:
        raise NotImplementedError

    def _check_sudo_commands(self, comodel: BaseModel) -> BaseModel:
        # if the model doesn't accept sudo commands
        if not comodel._allow_sudo_commands:
            # Then, disable sudo and reset the transaction origin user
            return comodel.sudo(False).with_user(
                comodel.env.transaction.default_env.uid
            )
        return comodel

    @override
    def condition_to_sql(
        self,
        field_expr: str,
        operator: str,
        value: typing.Any,
        model: BaseModel,
        alias: str,
        query: Query,
    ) -> SQL:
        assert field_expr == self.name, "Supporting condition only to field"
        comodel = model.env[self.comodel_name]
        if not self.store:
            raise ValueError(f"Cannot convert {self} to SQL because it is not stored")

        # update the operator to 'any'
        if operator in ("in", "not in"):
            operator = "any" if operator == "in" else "not any"
        assert operator in (
            "any",
            "not any",
            "any!",
            "not any!",
        ), f"Relational field {self} expects 'any' operator"
        exists = operator in ("any", "any!")

        # check the value and execute the query
        if isinstance(value, COLLECTION_TYPES):
            value = OrderedSet(value)
            comodel = comodel.sudo().with_context(active_test=False)
            if False in value:
                #  [not]in (False, 1) => split conditions
                #  We want records that have a record such as condition or
                #  that don't have any records.
                if len(value) > 1:
                    in_operator = "in" if exists else "not in"
                    return SQL(
                        "(%s OR %s)" if exists else "(%s AND %s)",
                        self.condition_to_sql(
                            field_expr,
                            in_operator,
                            (False,),
                            model,
                            alias,
                            query,
                        ),
                        self.condition_to_sql(
                            field_expr,
                            in_operator,
                            value - {False},
                            model,
                            alias,
                            query,
                        ),
                    )
                #  in (False) => not any (Domain.TRUE)
                #  not in (False) => any (Domain.TRUE)
                value = comodel._search(Domain.TRUE)
                exists = not exists
            else:
                value = comodel.browse(value)._as_query(ordered=False)
        elif isinstance(value, SQL):
            # wrap SQL into a simple query
            comodel = comodel.sudo()
            value = Domain("id", "any", value)
        coquery = self._get_query_for_condition_value(model, comodel, operator, value)
        return self._condition_to_sql_relational(model, alias, exists, coquery, query)

    def _get_query_for_condition_value(
        self,
        model: BaseModel,
        comodel: BaseModel,
        operator: str,
        value: Domain | Query,
    ) -> Query:
        """Return Query run on the comodel with the field.domain injected."""
        field_domain = self.get_comodel_domain(model)
        if isinstance(value, Domain):
            domain = value & field_domain
            comodel = comodel.with_context(**self.context)
            bypass_access = self.bypass_search_access or operator in (
                "any!",
                "not any!",
            )
            query = comodel._search(domain, bypass_access=bypass_access)
            assert isinstance(query, Query)
            return query
        if isinstance(value, Query):
            # add the field_domain to the query
            domain = field_domain.optimize_full(comodel)
            if not domain.is_true():
                # mutates the Query in place: the caller passes a fresh Query
                # from _search(). A shared Query would need cloning first.
                value.add_where(domain._to_sql(comodel, value.table, value))
            return value
        raise NotImplementedError(f"Cannot build query for {value}")

    def _condition_to_sql_relational(
        self,
        model: BaseModel,
        alias: str,
        exists: bool,
        coquery: Query,
        query: Query,
    ) -> SQL:
        raise NotImplementedError


class PrefetchX2many(Reversible):
    """Iterable over an x2many's values across a record's prefetch set."""

    __slots__ = ("field", "record")

    def __init__(self, record: BaseModel, field: _RelationalMulti) -> None:
        self.record = record
        self.field = field

    def __iter__(self) -> Iterator[int | NewId]:
        field_cache = self.field._get_cache(self.record.env)
        return unique(
            coid
            for id_ in self.record._prefetch_ids
            for coid in field_cache.get(id_, ())
        )

    def __reversed__(self) -> Iterator[int | NewId]:
        field_cache = self.field._get_cache(self.record.env)
        return unique(
            coid
            for id_ in reversed(self.record._prefetch_ids)
            for coid in field_cache.get(id_, ())
        )
