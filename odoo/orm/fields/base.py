import builtins
import collections
import functools
import itertools
import logging
import time
import typing
import warnings
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
)
from operator import attrgetter

from odoo.db import schema as sql
from odoo.exceptions import AccessError, MissingError
from odoo.libs._field_access import to_prefetch_ids as _to_prefetch_ids
from odoo.tools import SQL, reset_cached_properties
from odoo.tools.misc import (
    PENDING,
    SENTINEL,
    ReadonlyDict,
    Sentinel,
    frozendict,
    unique,
)

from .._recordset import base_model, is_model_class, is_recordset
from ..domain import Domain
from ..primitives import COLLECTION_TYPES, PREFETCH_MAX, STATE_FIELD
from ._field_convert import _FieldConvertMixin
from ._field_description import _FieldDescriptionMixin
from ._field_metadata import _FieldMetadataMixin
from ._field_sql import _FieldSqlMixin

if typing.TYPE_CHECKING:
    from .._typing import (
        BaseModel,
        ContextType,
        DomainType,
        ModelLike,
        ModelType,
        Self,
    )
    from ..primitives import IdType
    from ..runtime import Environment, Registry

    M = typing.TypeVar("M", bound=BaseModel)


def _expand_ids(id0: IdType, ids: Iterable[IdType]) -> Iterator[IdType]:
    yield id0
    seen = {id0}
    kind = bool(id0)
    for id_ in ids:
        if id_ not in seen and bool(id_) == kind:
            yield id_
            seen.add(id_)


def _batch_then_single(
    batch: Callable[[], None],
    single: Callable[[], None],
    recs: BaseModel,
    *,
    catching: tuple[type[BaseException], ...],
    reraise_when_single: bool = True,
) -> bool:
    try:
        batch()
        return False
    except catching:
        if reraise_when_single and len(recs) == 1:
            raise
    single()
    return True


def _recordset_like(records: BaseModel, ids: Iterable[IdType]) -> BaseModel:
    rs = object.__new__(records.__class__)
    rs.env = records.env
    rs._ids = tuple(ids)
    rs._prefetch_ids = records._prefetch_ids
    return rs


COMPANY_DEPENDENT_FIELDS: tuple[str, ...] = (
    "char",
    "float",
    "boolean",
    "integer",
    "text",
    "many2one",
    "date",
    "datetime",
    "selection",
    "html",
)
_logger = logging.getLogger("odoo.fields")
_orm_compute = logging.getLogger("odoo.orm.compute")


def resolve_mro(
    model: BaseModel, name: str, predicate: Callable[[typing.Any], bool]
) -> list[typing.Any]:
    result = []
    for cls in model._model_classes__:
        value = cls.__dict__.get(name, SENTINEL)
        if value is SENTINEL:
            continue
        if not predicate(value):
            break
        result.append(value)
    return result


def determine(
    needle: str | Callable[..., typing.Any] | None,
    records: ModelLike,
    *args: object,
) -> typing.Any:
    if not is_recordset(records):
        msg = "Determination requires a subject recordset"
        raise TypeError(msg)
    if isinstance(needle, str):
        method = getattr(records, needle)
        if not method.__name__.startswith("__"):
            return method(*args)
    elif callable(needle):
        if not getattr(needle, "__name__", "").startswith("__"):
            return needle(records, *args)

    msg = "Determination requires a callable or method name"
    raise TypeError(msg)


_global_seq = itertools.count()


class Field[T](
    _FieldDescriptionMixin, _FieldConvertMixin, _FieldSqlMixin, _FieldMetadataMixin
):
    type: str
    """The serialised discriminator: what ``ir.model.fields`` stores, what
    ``fields_get`` reports and what the web client dispatches on.

    It is a *persistence* concern, and the class hierarchy is what code in this
    package should branch on. ``relational``/``is_text`` below, and the
    predicates after them, exist so that a caller asks the field what it is
    rather than comparing this string -- see :attr:`is_delegating` for what the
    comparison form costs.
    """

    relational: bool = False
    is_text: bool = False
    falsy_value: T | None = None

    is_x2many: bool = False
    """Whether the field holds a *set* of comodel records (o2m or m2m).

    Declared with an inert default and overridden on ``_RelationalMulti``, the
    shared base of ``One2many`` and ``Many2many``, so the sites that spelled
    this as a membership test over the two type strings ask the field instead of
    reproducing the list.
    """

    is_temporal: bool = False
    """Whether the field holds a date or a datetime."""

    is_many2one: bool = False
    """Whether the field is a foreign-key scalar relation.

    ``Many2one`` only. In particular **not** ``Many2oneReference``, which points
    at one record too but is an ``Integer`` column paired with a model-name
    field, and so cannot be joined or grouped like an FK. The type strings say
    that (``"many2one"`` against ``"many2one_reference"``) and a reader has to
    know it; the predicate states it.

    Safe as a class attribute only because nothing subclasses ``Many2one`` and
    resets ``type`` -- the leak `fields/_field_sql.py` warns about, checked for
    every registered field type by ``orm/tests/test_field_predicates.py``.
    """

    is_properties: bool = False
    """Whether the field holds a JSON bag of dynamic, per-record properties.

    ``Properties`` only -- NOT ``PropertiesDefinition``, which is the separate
    field holding the *schema* those values are validated against. The two were
    told apart by their type strings (``"properties"`` vs
    ``"properties_definition"``), which is a distinction that survives only as
    long as nobody writes ``startswith("properties")``.
    """

    @property
    def is_delegating(self) -> bool:
        return False

    @property
    def is_attachment_backed(self) -> bool:
        return False

    write_sequence: int = 0
    """Field processing priority in ``write()`` — lower values are processed first.

    Controls the order in which ``mark_dirty()`` is called during ``write()``.
    This matters for correctness when fields depend on each other's cached values:

    ========== ============== ============================================
    Sequence   Field Type     Reason
    ========== ============== ============================================
    0          Regular        Default — scalar fields, M2O, currency fields
    10         Monetary       Needs ``currency_id`` (seq 0) cached for rounding
    10         Properties     Must be written after the definition field
    20         x2many (O2M)   May flush other fields when deleting lines
    ========== ============== ============================================

    Custom field types with similar dependencies should override this attribute.
    """

    _args__: dict[str, typing.Any] | None = None
    _module: str | None = None
    _modules: tuple[str, ...] = ()
    _setup_done = True
    _sequence: int
    _base_fields__: tuple[Self, ...] = ()
    _extra_keys__: tuple[str, ...] = ()
    _direct: bool = False
    _toplevel: bool = False

    inherited: bool = False
    inherited_field: Field | None = None

    comodel_name: str | None = None
    context: ContextType = frozendict({})
    """Extra context a relational field applies to its comodel.

    Not a plain ``{}``: this default is shared by every ``Field`` instance in the
    process, so one in-place mutation would rewrite the context of every field at
    once. ``ContextType`` is a ``Mapping``, which promises exactly that and cannot
    enforce it; the same file wraps ``_args__`` for this reason.

    ``frozendict`` rather than ``ReadonlyDict``, because it must also stay a
    ``dict``. ``_description_context`` hands this default to ``fields_get``
    verbatim, so it is wire-facing; as a ``ReadonlyDict`` -- a bare ``Mapping`` --
    it was refused by everything that tests ``isinstance(..., dict)``, stdlib
    ``json.dumps`` included, and it took out 2963 XML-RPC ``fields_get`` calls on
    one database in a day. ``frozendict`` refuses all eight mutation entry points
    exactly as ``ReadonlyDict`` does, so nothing above is given up for it.

    This does not make the default universally serialisable: ``xmlrpc.client``
    dispatches on *exact* type and so misses a ``dict`` subclass too, which is why
    ``OdooMarshaller`` has carried an explicit ``frozendict`` entry since long
    before this. Being a ``dict`` is simply the property serialisers test for, so
    the exception is one registration in one exact-type dispatcher rather than a
    type each of them has to learn. What it does give up is
    ``dict.__setitem__(field.context, ...)``, which bypasses the override --
    sabotage, not the accident this default guards against.

    Declared on the base class, with an inert default, for the same reason as
    ``comodel_name``: consumers key on it without first proving the field is
    relational.  ``Environment.cache_key`` is the one that made this load-bearing
    -- its ``active_test`` branch reads ``field.context`` for any field whose
    ``depends_context`` mentions it, so ``@api.depends_context("active_test")``
    on a computed scalar raised ``AttributeError`` on every read of that field.
    """

    delegate: bool = False
    """Whether a Many2one sets up ``_inherits`` delegation to its comodel.

    Declared here, with an inert default, for the same reason as
    ``comodel_name`` and ``context`` above: consumers key on it without first
    proving the field is a Many2one. ``Field.__get__``'s cache-miss path reads
    ``self.type == "many2one" and self.delegate``, and until 2026-08-09 the
    attribute existed *only* on ``Many2one`` -- so that line was safe purely by
    ``and`` short-circuiting on the type string. Reorder the condition, or add a
    second reader that checks ``delegate`` first, and every non-m2o field raises
    ``AttributeError`` on the hottest read path in the ORM.
    """

    attachment: bool = False
    """Whether a Binary field stores its bytes as an ``ir.attachment``.

    Same reason as ``delegate``: ``Field.update_db`` reads
    ``self.related_field.type == "binary" and self.related_field.attachment``,
    and the attribute lived only on ``Binary``.
    """

    index: str | None = None
    manual: bool = False
    copy: bool = True
    _depends: Collection[str] | None = None
    _depends_context: Collection[str] | None = None
    recursive: bool = False
    compute: str | Callable[[BaseModel], None] | None = None
    compute_sudo: bool = False
    precompute: bool = False
    inverse: str | Callable[[BaseModel], None] | None = None
    search: str | Callable[[BaseModel, str, typing.Any], DomainType] | None = None
    related: str | None = None
    default: Callable[[ModelLike], T] | T | None = None

    string: str | None = None
    export_string_translation: bool = True
    help: str | None = None
    readonly: bool = False
    required: bool = False
    groups: str | None = None
    change_default = False

    related_field: Field | None = None
    aggregator: str | None = None
    group_expand: (
        str | Callable[[ModelLike, typing.Any, DomainType], typing.Any] | None
    ) = None
    falsy_value_label: str | None = None
    prefetch: bool | str = True

    default_export_compatible: bool = False
    exportable: bool = True

    _by_type__: dict[str, builtins.type[Field]] = {}
    _register_type: typing.ClassVar[bool] = True

    def __init__(self, string: str | Sentinel = SENTINEL, **kwargs):
        kwargs["string"] = string
        self._sequence = next(_global_seq)
        self._args__ = ReadonlyDict(
            {key: val for key, val in kwargs.items() if val is not SENTINEL}
        )

    def __str__(self) -> str:
        if not self.name:
            return f"<{__name__}.{type(self).__name__}>"
        return f"{self.model_name}.{self.name}"

    def __repr__(self) -> str:
        if not self.name:
            return repr(f"<{__name__}.{type(self).__name__}>")
        return repr(f"{self.model_name}.{self.name}")

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not hasattr(cls, "type"):
            return

        if cls.type and cls._register_type:
            cls._by_type__.setdefault(cls.type, cls)

        cls.related_attrs = []
        cls.description_attrs = []
        for attr in dir(cls):
            if attr.startswith("_related_"):
                cls.related_attrs.append((attr.removeprefix("_related_"), attr))
            elif attr.startswith("_description_"):
                cls.description_attrs.append((attr.removeprefix("_description_"), attr))
        cls.related_attrs = tuple(cls.related_attrs)
        cls.description_attrs = tuple(cls.description_attrs)

    def __set_name__(self, owner: type[BaseModel], name: str) -> None:
        assert base_model() is None or is_model_class(owner)
        self.model_name = owner._name
        self.name = name
        if getattr(owner, "pool", None) is None:
            self._module = owner._module
            owner._field_definitions.append(self)

        if not self._args__.get("related"):
            self._direct = True
        if self._direct or self._toplevel:
            self._setup_attrs__(owner, name)
            if self._toplevel:
                self.__dict__.pop("_args__", None)
                if not self.related:
                    self.__dict__.pop("_base_fields__", None)

    def _get_attrs(
        self, model_class: type[BaseModel], name: str
    ) -> dict[str, typing.Any]:
        attrs = {}
        modules: list[str] = []
        for field in self._args__.get("_base_fields__", ()):
            if not isinstance(self, type(field)):
                attrs.clear()
                modules.clear()
                continue
            attrs.update(field._args__)
            if field._module:
                modules.append(field._module)
        attrs.update(self._args__)
        if self._module:
            modules.append(self._module)

        attrs["model_name"] = model_class._name
        attrs["name"] = name
        attrs["_module"] = modules[-1] if modules else None
        attrs["_modules"] = tuple(unique(modules) if len(modules) > 1 else modules)

        if name == STATE_FIELD:
            attrs["copy"] = attrs.get("copy", False)
        if attrs.get("compute"):
            attrs["store"] = store = attrs.get("store", False)
            attrs["compute_sudo"] = attrs.get("compute_sudo", store)
            if not (attrs["store"] and not attrs.get("readonly", True)):
                attrs["copy"] = attrs.get("copy", False)
            attrs["readonly"] = attrs.get("readonly", not attrs.get("inverse"))
        if attrs.get("related"):
            attrs["store"] = store = attrs.get("store", False)
            attrs["compute_sudo"] = attrs.get(
                "compute_sudo", attrs.get("related_sudo", True)
            )
            attrs["copy"] = attrs.get("copy", False)
            attrs["readonly"] = attrs.get("readonly", True)
        if attrs.get("precompute"):
            if not attrs.get("compute") and not attrs.get("related"):
                warnings.warn(
                    f"precompute attribute doesn't make any sense on non computed field {self}",
                    stacklevel=1,
                )
                attrs["precompute"] = False
            elif not attrs.get("store"):
                warnings.warn(
                    f"precompute attribute has no impact on non stored field {self}",
                    stacklevel=1,
                )
                attrs["precompute"] = False
        if attrs.get("company_dependent"):
            if attrs.get("required"):
                warnings.warn(
                    f"company_dependent field {self} cannot be required",
                    stacklevel=1,
                )
            if attrs.get("translate"):
                warnings.warn(
                    f"company_dependent field {self} cannot be translated",
                    stacklevel=1,
                )
            if self.type not in COMPANY_DEPENDENT_FIELDS:
                warnings.warn(
                    f"company_dependent field {self} is not one of the allowed types {COMPANY_DEPENDENT_FIELDS}",
                    stacklevel=1,
                )
            attrs["copy"] = attrs.get("copy", False)
            attrs["index"] = attrs.get("index", "btree_not_null")
            attrs["prefetch"] = attrs.get("prefetch", "company_dependent")
            attrs["_depends_context"] = ("company",)
        if "depends" in attrs:
            depends = tuple(attrs.pop("depends"))
            for dep in depends:
                if "id" in dep.split("."):
                    raise ValueError(f"Field {self} cannot depend on field 'id'.")
            attrs["_depends"] = depends
        if "depends_context" in attrs:
            depends_context = tuple(attrs.pop("depends_context"))
            if attrs.get("company_dependent") and "company" not in depends_context:
                depends_context = ("company", *depends_context)
            attrs["_depends_context"] = depends_context

        if "group_operator" in attrs:
            warnings.warn(
                "Since Odoo 18, 'group_operator' is deprecated, use 'aggregator' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            attrs["aggregator"] = attrs.pop("group_operator")

        return attrs

    def _setup_attrs__(self, model_class: type[BaseModel], name: str) -> None:
        attrs = self._get_attrs(model_class, name)

        extra_keys = tuple(key for key in attrs if not hasattr(self, key))
        if extra_keys:
            attrs["_extra_keys__"] = extra_keys

        self.__dict__.update(attrs)

        if not self.store or not self.column_type or self.manual:
            self.prefetch = False

        if not self.string and not self.related:
            self.string = (
                (name[:-4] if name.endswith("_ids") else name.removesuffix("_id"))
                .replace("_", " ")
                .title()
            )

        if self.default is not None and not callable(self.default):
            value = self.default
            self.default = lambda model: value

    def prepare_setup(self) -> None:
        self._setup_done = False

    def setup(self, model: BaseModel) -> None:
        if not self._setup_done:
            for key in self._extra_keys__:
                if not model._valid_field_parameter(self, key):
                    _logger.warning(
                        "Field %s: unknown parameter %r, if this is an actual"
                        " parameter you may want to override the method"
                        " _valid_field_parameter on the relevant model in order to"
                        " allow it",
                        self,
                        key,
                    )
            if self.related:
                self.setup_related(model)
            else:
                self.setup_nonrelated(model)

            if not isinstance(self.required, bool):
                warnings.warn(
                    f"Property {self}.required should be a boolean ({self.required}).",
                    stacklevel=1,
                )

            if not isinstance(self.readonly, bool):
                warnings.warn(
                    f"Property {self}.readonly should be a boolean ({self.readonly}).",
                    stacklevel=1,
                )

            self._setup_done = True
            reset_cached_properties(self)

    def setup_nonrelated(self, model: BaseModel) -> None:
        pass

    def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
        if self._depends is not None:
            return self._depends, self._depends_context or ()

        if self.related:
            if self._depends_context is not None:
                depends_context = self._depends_context
            else:
                depends_context = []
                field_model_name = model._name
                for field_name in self.related.split("."):
                    field_model = model.env[field_model_name]
                    field = field_model._fields[field_name]
                    depends_context.extend(field.get_depends(field_model)[1])
                    field_model_name = field.comodel_name
                depends_context = tuple(unique(depends_context))
            return [self.related], depends_context

        if not self.compute:
            return (), self._depends_context or ()

        if isinstance(self.compute, str):
            funcs = resolve_mro(model, self.compute, callable)
        else:
            funcs = [self.compute]

        depends = []
        depends_context = list(self._depends_context or ())
        for func in funcs:
            deps = getattr(func, "_depends", ())
            depends.extend(deps(model) if callable(deps) else deps)
            depends_context.extend(getattr(func, "_depends_context", ()))

        return depends, depends_context

    def setup_related(self, model: BaseModel) -> None:
        assert isinstance(self.related, str), self.related

        self._related_names = related_names = tuple(self.related.split("."))

        field_seq = []
        model_name = self.model_name
        for name in related_names:
            field = model.pool[model_name]._fields.get(name)
            if field is None:
                raise KeyError(
                    f"Field {name} referenced in related field definition {self} does not exist."
                )
            if not field._setup_done:
                field.setup(model.env[model_name])
            field_seq.append(field)
            model_name = field.comodel_name

        if self.type != field.type:
            raise TypeError(
                f"Type of related field {self} is inconsistent with {field}"
            )

        self.related_field = field

        model.pool.field_setup_dependents.add(field, self)

        self.compute = self._compute_related
        if self.inherited or not (self.readonly or field.readonly):
            self.inverse = self._inverse_related
        if not self.store and all(f._description_searchable for f in field_seq):
            self.search = self._search_related

        if self.default and self.readonly and not self.inverse:
            _logger.warning("Redundant default on %s", self)

        for attr, prop in self.related_attrs:
            if attr not in self.__dict__:
                setattr(self, attr, getattr(field, prop))

        for attr in field._extra_keys__:
            if not hasattr(self, attr) and model._valid_field_parameter(self, attr):
                setattr(self, attr, getattr(field, attr))

        if self.inherited:
            self.inherited_field = field
            if field.required:
                self.required = True
            delegate_field = model._fields[related_names[0]]
            self._modules = tuple(
                {*self._modules, *delegate_field._modules, *field._modules}
            )

    def traverse_related(self, record: BaseModel) -> tuple[BaseModel, Field]:
        for name in self._related_names[:-1]:
            corecord = record[name]
            record = next(iter(corecord), corecord)
        return record, self.related_field

    def _compute_related(self, records: BaseModel) -> None:
        values = list(records)
        for name in self._related_names[:-1]:
            try:
                values = [next(iter(val := value[name]), val) for value in values]
            except AccessError as e:
                description = records.env["ir.model"]._get(records._name).name
                env = records.env
                raise AccessError(
                    env._(
                        "%(previous_message)s\n\nImplicitly accessed through '%(document_kind)s' (%(document_model)s).",
                        previous_message=e.args[0],
                        document_kind=description,
                        document_model=records._name,
                    )
                ) from e
        falsy_groups: dict[tuple, tuple] = {}
        for record, value in zip(records, values, strict=True):
            processed = self._process_related(
                value[self.related_field.name], record.env
            )
            if processed:
                record[self.name] = processed
            else:
                key = (type(processed), processed)
                falsy_groups.setdefault(key, (processed, []))[1].append(record.id)
        for processed, ids in falsy_groups.values():
            records.browse(ids)[self.name] = processed

    def _process_related(self, value, env: Environment) -> typing.Any:
        return value

    def _inverse_related(self, records: BaseModel) -> None:
        record_value = {record: record[self.name] for record in records}
        for record in records:
            target, field = self.traverse_related(record)
            if target and bool(target.id) == bool(record.id):
                target[field.name] = record_value[record]

    def _search_related(self, records: BaseModel, operator: str, value) -> DomainType:

        falsy_value = self.falsy_value
        if isinstance(value, COLLECTION_TYPES):
            value_is_null = any(
                val is False or val is None or val == falsy_value for val in value
            )
        else:
            value_is_null = value is False or value is None or value == falsy_value
        can_be_null = (operator not in Domain.NEGATIVE_OPERATORS) == value_is_null
        if operator in Domain.NEGATIVE_OPERATORS and not value_is_null:
            return NotImplemented

        field_seq = []
        model_name = self.model_name
        for fname in self._related_names:
            field = records.env[model_name]._fields[fname]
            field_seq.append(field)
            model_name = field.comodel_name

        domain = Domain(field_seq[-1].name, operator, value)
        for field in reversed(field_seq[:-1]):
            domain = Domain(field.name, "any!" if self.compute_sudo else "any", domain)
            if can_be_null and field.is_many2one and not field.required:
                domain |= Domain(field.name, "=", False)
        return domain

    _related_comodel_name = property(attrgetter("comodel_name"))
    _related_string = property(attrgetter("string"))
    _related_help = property(attrgetter("help"))
    _related_groups = property(attrgetter("groups"))
    _related_aggregator = property(attrgetter("aggregator"))

    @functools.cached_property
    def is_stored_computed(self) -> bool:
        return bool(self.compute and self.store)

    @property
    def base_field(self) -> Self:
        return self.inherited_field.base_field if self.inherited_field else self

    def get_company_dependent_fallback(self, records: ModelLike) -> typing.Any:
        assert self.company_dependent
        fallback = self._company_dependent_fallback_raw(records)
        fallback = self.convert_to_cache(fallback, records, validate=False)
        return self.convert_to_record(fallback, records)

    def resolve_depends(self, registry: Registry) -> Iterator[tuple[Field, ...]]:
        Model0 = registry[self.model_name]

        for dotnames in registry.field_depends[self]:
            field_seq: list[Field] = []
            model_name = self.model_name
            check_precompute = self.precompute

            for index, fname in enumerate(dotnames.split(".")):
                if not model_name:
                    raise ValueError(
                        f"Wrong dependency '{dotnames}' of field {self}: "
                        f"'{field_seq[-1].name}' is not relational, so the path "
                        f"cannot continue with '{fname}'."
                    )
                Model = registry[model_name]
                if Model0._transient and not Model._transient:
                    break

                try:
                    field = Model._fields[fname]
                except KeyError:
                    raise ValueError(
                        f"Wrong @depends on '{self.compute}' (compute method of field {self}). "
                        f"Dependency field '{fname}' not found in model {model_name}."
                    ) from None
                if field is self and index and not self.recursive:
                    self.recursive = True
                    warnings.warn(
                        f"Field {self} should be declared with recursive=True",
                        stacklevel=1,
                    )

                if (
                    check_precompute
                    and field.store
                    and field.compute
                    and not field.precompute
                ):
                    warnings.warn(
                        f"Field {self} cannot be precomputed as it depends on non-precomputed field {field}",
                        stacklevel=1,
                    )
                    self.precompute = False

                if field_seq and not field_seq[-1]._description_searchable:
                    warnings.warn(
                        f"Field {field_seq[-1]!r} in dependency of {self} should be searchable. "
                        f"This is necessary to determine which records to recompute when {field} is modified. "
                        f"You should either make the field searchable, or simplify the field dependency.",
                        stacklevel=1,
                    )

                field_seq.append(field)

                if not (field is self and not index):
                    yield tuple(field_seq)

                if field.type == "one2many":
                    for inv_field in Model.pool.field_inverses[field]:
                        yield tuple(field_seq) + (inv_field,)

                if check_precompute and field.is_many2one:
                    check_precompute = False

                model_name = field.comodel_name

    _description_name = property(attrgetter("name"))
    _description_type = property(attrgetter("type"))
    _description_store = property(attrgetter("store"))
    _description_manual = property(attrgetter("manual"))
    _description_related = property(attrgetter("related"))
    _description_company_dependent = property(attrgetter("company_dependent"))
    _description_readonly = property(attrgetter("readonly"))
    _description_required = property(attrgetter("required"))
    _description_groups = property(attrgetter("groups"))
    _description_change_default = property(attrgetter("change_default"))
    _description_default_export_compatible = property(
        attrgetter("default_export_compatible")
    )
    _description_exportable = property(attrgetter("exportable"))

    def update_db(
        self, model: ModelLike, columns: dict[str, dict[str, typing.Any]]
    ) -> bool:
        if not self.column_type:
            return False

        column = columns.get(self.name)

        self.update_db_column(model, column)
        self.update_db_notnull(model, column)

        if (
            not column
            and self.related
            and self.related.count(".") == 1
            and self.related_field.store
            and not self.related_field.compute
            and not self.related_field.is_attachment_backed
            and not self.related_field.is_x2many
        ):
            join_field = model._fields[self._related_names[0]]
            if join_field.is_many2one and join_field.store and not join_field.compute:
                model.pool.post_init(self.update_db_related, model)
                return False

        return not column

    def update_db_column(self, model: ModelLike, column: dict[str, typing.Any]) -> None:
        if not column:
            sql.create_column(
                model.env.cr,
                model._table,
                self.name,
                self.column_type[1],
                self.string,
            )
            return
        if column["udt_name"] == self.column_type[0]:
            return
        self._convert_db_column(model, column)

    def _convert_db_column(self, model: ModelLike, column: dict[str, typing.Any]):
        sql.convert_column(model.env.cr, model._table, self.name, self.column_type[1])

    def update_db_notnull(
        self, model: ModelLike, column: dict[str, typing.Any]
    ) -> None:
        has_notnull = column and column["is_nullable"] == "NO"

        if not column or (self.required and not has_notnull):
            if model._table_has_rows():
                model._init_column(self.name)

        if self.required and not has_notnull:

            @model.pool.post_init
            def add_not_null():
                field = model._fields[self.name]
                if not field.required or not field.store:
                    return
                if field.compute:
                    records = model.browse(
                        id_
                        for (id_,) in model.env.execute_query(
                            SQL(
                                "SELECT id FROM %s AS t WHERE %s IS NULL",
                                SQL.identifier(model._table),
                                model._field_to_sql("t", field.name),
                            )
                        )
                    )
                    model.env.add_to_compute(field, records)
                model.flush_model([field.name])

                sql_default = None
                if (
                    field.default
                    and not field.translate
                    and not field.company_dependent
                ):
                    try:
                        value = field.default(model.browse())
                        if isinstance(value, (str, int, float, bool)):
                            sql_default = field.convert_to_column(
                                value, model, validate=False
                            )
                    except Exception:
                        _logger.debug(
                            "Could not derive a SQL DEFAULT for %s; "
                            "applying NOT NULL without one",
                            field,
                            exc_info=True,
                        )

                def apply_not_null(cr):
                    sql.set_not_null(cr, model._table, field.name)

                model.pool.post_constraint(
                    model.env.cr,
                    apply_not_null,
                    key=f"add_not_null:{model._table}:{field.name}",
                )

                if sql_default is not None:

                    def apply_default(cr, sql_default=sql_default):
                        sql.set_default(cr, model._table, field.name, sql_default)

                    model.pool.post_constraint(
                        model.env.cr,
                        apply_default,
                        key=f"set_default:{model._table}:{field.name}",
                    )

        elif not self.required and has_notnull:
            sql.drop_not_null(model.env.cr, model._table, self.name)

    def update_db_related(self, model: ModelLike) -> None:
        comodel = model.env[self.related_field.model_name]
        join_field, comodel_field = self._related_names
        model.env.cr.execute(
            SQL(
                """ UPDATE %(model_table)s AS x
                SET %(model_field)s = y.%(comodel_field)s
                FROM %(comodel_table)s AS y
                WHERE x.%(join_field)s = y.id """,
                model_table=SQL.identifier(model._table),
                model_field=SQL.identifier(self.name),
                comodel_table=SQL.identifier(comodel._table),
                comodel_field=SQL.identifier(comodel_field),
                join_field=SQL.identifier(join_field),
            )
        )

    def read(self, records: BaseModel) -> None:
        if not self.column_type:
            raise NotImplementedError(f"Method read() undefined on {self}")

    def create(self, record_values: Collection[tuple[BaseModel, typing.Any]]) -> None:
        for record, value in record_values:
            self.mark_dirty(record, value)

    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        records, cache_value = self._mark_dirty_prologue(records, value)
        if not records:
            return

        self._update_cache(records, cache_value, dirty=True)

    def _mark_dirty_prologue(
        self, records: BaseModel, value: typing.Any
    ) -> tuple[BaseModel, typing.Any]:
        records.env.remove_to_compute(self, records)

        cache_value = self.convert_to_cache(value, records)
        records = self._filter_not_equal(records, cache_value)
        return records, cache_value

    def _get_cache(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        field_cache = env._field_cache_memo.get(self)
        if field_cache is not None:
            return field_cache
        field_cache = self._get_cache_impl(env)
        env._field_cache_memo[self] = field_cache
        return field_cache

    def _get_cache_impl(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        cache = env._core.get_field_data(self)
        if self._is_context_dependent(env):
            cache = cache.setdefault(env.cache_key(self), {})
        return cache

    def _invalidate_cache(
        self,
        env: Environment,
        ids: Collection[IdType] | None = None,
        *,
        keep_dirty: bool = False,
    ) -> None:
        env._core.invalidate(
            self,
            ids,
            context_dependent=self._is_context_dependent(env),
            keep_dirty=keep_dirty,
        )

    def _get_all_cache_ids(self, env: Environment) -> Mapping[IdType, typing.Any]:
        return env._core.all_cached_ids(
            self, context_dependent=self._is_context_dependent(env)
        )

    def _cache_missing_ids(self, records: ModelLike) -> Iterator[IdType]:
        field_cache = self._get_cache(records.env)
        _pending = PENDING
        return (
            id_
            for id_ in records._ids
            if id_ not in field_cache or field_cache.get(id_) is _pending
        )

    def _filter_not_equal(
        self, records: ModelType, cache_value: typing.Any
    ) -> ModelType:
        field_cache = self._get_cache(records.env)
        ids = records._ids
        if len(ids) == 1:
            if field_cache.get(ids[0], SENTINEL) != cache_value:
                return records
            return records.browse()
        return records.browse(
            record_id
            for record_id in ids
            if field_cache.get(record_id, SENTINEL) != cache_value
        )

    def _to_prefetch(self, record: ModelType) -> ModelType:
        field_cache = self._get_cache(record.env)
        prefetch_ids = record._prefetch_ids
        record_id = record.id
        if isinstance(prefetch_ids, tuple) and type(field_cache) is dict:
            result = _to_prefetch_ids(
                record_id, prefetch_ids, field_cache, PREFETCH_MAX
            )
            if result is not None:
                return record.browse(result)
        kind = bool(record_id)
        result = [record_id]
        added = {record_id}
        for id_ in prefetch_ids:
            if len(result) >= PREFETCH_MAX:
                break
            if id_ not in field_cache and id_ not in added and bool(id_) == kind:
                result.append(id_)
                added.add(id_)
        return record.browse(result)

    def _clear_dead_pending(self, records: BaseModel) -> None:
        """Drop PENDING markers that no compute is going to replace.

        ``create`` seeds PENDING for every stored computed field, meaning "a
        compute owes this record a value". A compute that leaves a record
        unassigned -- the idiom for "leave the stored value alone" -- returns
        without clearing the marker and without scheduling anything, which is
        the state ``_flush`` refuses outright: *the value can never
        materialize*. Reading such a field papers over it with a full-width
        SELECT, and because ``_insert_cache`` is a ``setdefault`` the marker
        survives that SELECT, so the *next* field read pays for another one.

        The row is in hand here. Take it for every marker nothing else owns:
        still-scheduled fields keep theirs, because their compute is the
        authority, and dirty ids keep theirs, because a pending write is.
        """
        env = records.env
        field_cache = self._get_cache(env)
        if not field_cache:
            return
        core = env._core
        scheduled = core.pending_ids(self)
        dirty = core.get_dirty(self)
        for id_ in records._ids:
            if field_cache.get(id_) is not PENDING:
                continue
            if scheduled and id_ in scheduled:
                continue
            if dirty and id_ in dirty:
                continue
            del field_cache[id_]

    def _insert_cache(self, records: BaseModel, values: Iterable) -> None:
        field_cache = self._get_cache(records.env)
        collections.deque(
            map(field_cache.setdefault, records._ids, values, strict=True), maxlen=0
        )

    def _update_cache_items(
        self, env: Environment, items: Iterable[tuple[IdType, typing.Any]]
    ) -> None:
        items = list(items)
        if not items:
            return

        self._check_not_dirty(env, [id_ for id_, _ in items], "_update_cache_items")

        self._get_cache(env).update(items)

    def _check_not_dirty(
        self, env: Environment, ids: Collection[IdType], caller: str
    ) -> None:
        if not self.is_column:
            return
        dirty_ids = env._core.get_dirty(self)
        if not dirty_ids or dirty_ids.isdisjoint(ids):
            return
        overlap = sorted(dirty_ids.intersection(ids))
        raise ValueError(
            f"Field.{caller}: refusing to overwrite the dirty value of {self} "
            f"on records {overlap} without dirty=True; the pending write would "
            f"be lost"
        )

    def _update_cache(
        self, records: ModelLike, cache_value: typing.Any, dirty: bool = False
    ) -> None:
        env = records.env

        if not dirty:
            self._check_not_dirty(env, records._ids, "_update_cache")

        field_cache = self._get_cache(env)
        ids = records._ids
        if len(ids) <= 1:
            if ids:
                field_cache[ids[0]] = cache_value
        else:
            field_cache.update(dict.fromkeys(ids, cache_value))

        if self.is_column and dirty:
            env._core.mark_dirty(self, (id_ for id_ in records._ids if id_))

    @typing.overload
    def __get__(self, record: None, owner: typing.Any = None) -> Self: ...
    @typing.overload
    def __get__(self, record: BaseModel, owner: typing.Any = None) -> T: ...
    @typing.overload
    def __get__(self, record: object, owner: typing.Any = None) -> typing.Any: ...

    def __get__(self, record: typing.Any, owner: typing.Any = None) -> T | Self:
        if record is None:
            return self

        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")

        record_ids = record._ids
        if len(record_ids) != 1:
            if record_ids:
                record.ensure_one()
            value = self.convert_to_cache(False, record, validate=False)
            return self.convert_to_record(value, record)

        if self.is_stored_computed and env._core.has_pending_field(self):
            self.recompute(record)

        record_id = record_ids[0]
        try:
            field_cache = env.__dict__["_field_cache_memo"][self]
        except KeyError:
            field_cache = self._get_cache(env)
        try:
            value = field_cache[record_id]
        except KeyError:
            value = SENTINEL
        if value is not SENTINEL and value is not PENDING:
            if callable(self.translate):
                try:
                    return self.convert_to_record(value, record)
                except KeyError:
                    pass
            else:
                return self.convert_to_record(value, record)
        if value is PENDING:
            field_cache.pop(record_id, None)
            if env.is_protected(self, record):
                value = self.convert_to_cache(False, record, validate=False)
                self._update_cache(record, value)
                return self.convert_to_record(value, record)
        return self._get_cache_miss(record, env, record_id, field_cache)

    def _get_cache_miss(
        self,
        record: BaseModel,
        env: Environment,
        record_id: IdType,
        field_cache: MutableMapping[IdType, typing.Any],
    ) -> T:
        if self.store and record_id:
            recs = self._to_prefetch(record)
            _batch_then_single(
                lambda: recs._fetch_field(self),
                lambda: record._fetch_field(self),
                recs,
                catching=(AccessError,),
            )
            field_cache = self._get_cache(env)
            value = field_cache.get(record_id, SENTINEL)
            if value is SENTINEL:
                raise MissingError(
                    "\n".join(
                        [
                            env._("Record does not exist or has been deleted."),
                            env._(
                                "(Record: %(record)s, User: %(user)s)",
                                record=record,
                                user=env.uid,
                            ),
                        ]
                    )
                ) from None

        elif self.store and record._has_origin and not (self.compute and self.readonly):
            recs = self._to_prefetch(record)
            origin_prefetch = recs._origin._prefetch_ids
            spawn = type(recs)._spawn
            recs_env = recs.env

            def _batch() -> None:
                for rec in recs:
                    rec_id = rec._ids[0]
                    if origin_id := (rec_id or getattr(rec_id, "origin", None)):
                        rec_origin = spawn(recs_env, (origin_id,), origin_prefetch)
                        self._update_cache(
                            rec,
                            self.convert_to_cache(
                                rec_origin[self.name], rec, validate=False
                            ),
                        )

            def _single() -> None:
                self._update_cache(
                    record,
                    self.convert_to_cache(
                        record._origin[self.name], record, validate=False
                    ),
                )

            _batch_then_single(
                _batch, _single, recs, catching=(AccessError, KeyError, MissingError)
            )
            field_cache = self._get_cache(env)
            value = field_cache[record_id]

        elif self.compute:
            if env.is_protected(self, record):
                value = self.convert_to_cache(False, record, validate=False)
                self._update_cache(record, value)
            else:
                recs = record if self.recursive else self._to_prefetch(record)
                if _batch_then_single(
                    lambda: self.compute_value(recs),
                    lambda: self.compute_value(record),
                    recs,
                    catching=(AccessError, MissingError),
                    reraise_when_single=False,
                ):
                    recs = record

                missing_recs_ids = tuple(self._cache_missing_ids(recs))
                if missing_recs_ids:
                    missing_recs = record.browse(missing_recs_ids)
                    if self.readonly and not self.store:
                        raise ValueError(
                            f"Compute method failed to assign {missing_recs}.{self.name}"
                        )
                    false_value = self.convert_to_cache(False, record, validate=False)
                    self._update_cache(missing_recs, false_value)

                field_cache = self._get_cache(env)
                value = field_cache[record_id]

        elif self.is_delegating and not record_id:

            def is_inherited_field(name):
                field = record._fields[name]
                return field.inherited and field.related.split(".")[0] == self.name

            parent = record.env[self.comodel_name].new(
                {
                    name: value
                    for name, value in record._cache.items()
                    if is_inherited_field(name)
                }
            )
            value = self.convert_to_cache(parent, record, validate=False)
            self._update_cache(record, value)
            if inv_recs := parent._new_records:
                for invf in env.registry.field_inverses[self]:
                    invf._update_inverse(inv_recs, record)

        else:
            value = self.convert_to_cache(False, record, validate=False)
            self._update_cache(record, value)
            defaults = record.default_get([self.name])
            if self.name in defaults:
                value = self.convert_to_cache(defaults[self.name], record)
                self._update_cache(record, value)
            field_cache = self._get_cache(env)
            value = field_cache[record_id]

        return self.convert_to_record(value, record)

    def __set__(self, records: BaseModel, value: typing.Any) -> None:
        record_ids = records._ids
        core = records.env._core
        if len(record_ids) == 1:
            record_id = record_ids[0]
            if core.is_protected(self, record_id):
                self.mark_dirty(records, value)
                return
            if not record_id:
                self._assign_new(records, [record_id], value)
                return
            write_value = self.convert_to_write(value, records)
            records.write({self.name: write_value})
            return

        _protected_ids = core.protected_ids(self)
        protected_ids = []
        new_ids = []
        other_ids = []
        for record_id in record_ids:
            if record_id in _protected_ids:
                protected_ids.append(record_id)
            elif not record_id:
                new_ids.append(record_id)
            else:
                other_ids.append(record_id)

        if protected_ids:
            self._assign_protected(records, protected_ids, value)
        if new_ids:
            self._assign_new(records, new_ids, value)
        if other_ids:
            self._assign_real(records, other_ids, value)

    def _assign_protected(
        self, records: BaseModel, ids: list[typing.Any], value: typing.Any
    ) -> None:
        self.mark_dirty(_recordset_like(records, ids), value)

    def _assign_new(
        self, records: BaseModel, ids: list[typing.Any], value: typing.Any
    ) -> None:
        new_records = _recordset_like(records, ids)
        with records.env.protecting(
            records.pool.field_computed.get(self, [self]), new_records
        ):
            if self.relational:
                new_records._modified_before([self.name])
            self.mark_dirty(new_records, value)
            new_records.modified([self.name])

        if self.inherited:
            parents = new_records[self._related_names[0]]
            parents._new_records[self.name] = value

    def _assign_real(
        self, records: BaseModel, ids: list[typing.Any], value: typing.Any
    ) -> None:
        records = _recordset_like(records, ids)
        write_value = self.convert_to_write(value, records)
        records.write({self.name: write_value})

    def ensure_access(self, record: ModelLike) -> None:
        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")

    def read_cache(self, record_id: int, env: Environment) -> tuple[bool, typing.Any]:
        value = self._get_cache(env).get(record_id, SENTINEL)
        if value is SENTINEL or value is PENDING:
            return False, SENTINEL
        return True, value

    def ensure_computed(self, records: ModelLike) -> None:
        if self.is_stored_computed and records.env._core.has_pending_field(self):
            self.recompute(records)

    def recompute(self, records: ModelLike) -> None:
        to_compute_ids = records.env._core.pending_ids(self)
        if not to_compute_ids:
            return

        _debug = _orm_compute.isEnabledFor(logging.DEBUG)
        if _debug:
            _t0 = time.perf_counter()
            _pending_before = len(to_compute_ids)

            def _count():
                remaining = records.env._core.pending_ids(self)
                return _pending_before - len(remaining or ())

        def apply_except_missing(func, records):
            try:
                func(records)
                return
            except MissingError:
                pass

            existing = records.exists()
            if existing:
                func(existing)
            missing = records - existing
            for f in records.pool.field_computed[self]:
                records.env.remove_to_compute(f, missing)

        if self.recursive:

            def recursive_compute(records):
                for record in records:
                    if record.id in to_compute_ids:
                        self.compute_value(record)

            apply_except_missing(recursive_compute, records)
            if _debug:
                _orm_compute.debug(
                    "[%.3f ms] recompute %s.%s: %d records (recursive=True)",
                    (time.perf_counter() - _t0) * 1000,
                    self.model_name,
                    self.name,
                    _count(),
                )
            return

        for record in records:
            if record.id in to_compute_ids:
                ids = _expand_ids(record.id, to_compute_ids)
                recs = record.browse(itertools.islice(ids, PREFETCH_MAX))
                try:
                    apply_except_missing(self.compute_value, recs)
                    continue
                except AccessError:
                    pass
                self.compute_value(record)

        if _debug:
            _orm_compute.debug(
                "[%.3f ms] recompute %s.%s: %d records (recursive=False)",
                (time.perf_counter() - _t0) * 1000,
                self.model_name,
                self.name,
                _count(),
            )

    def compute_value(self, records: ModelLike) -> None:
        _debug = _orm_compute.isEnabledFor(logging.DEBUG)
        if _debug:
            _t0 = time.perf_counter()

        env = records.env
        if self.compute_sudo:
            records = records.sudo()
        fields = records.pool.field_computed[self]

        for field in fields:
            if field.store:
                env.remove_to_compute(field, records)

        try:
            with records.env.protecting(fields, records):
                records._compute_field_value(self)
        except Exception:
            for field in fields:
                if field.store:
                    env.add_to_compute(field, records)
            raise

        if _debug:
            _orm_compute.debug(
                "[%.3f ms] compute_value %s.%s: %d records (sudo=%s)",
                (time.perf_counter() - _t0) * 1000,
                self.model_name,
                self.name,
                len(records),
                self.compute_sudo,
            )

    def determine_inverse(self, records: ModelLike) -> None:
        _debug = _orm_compute.isEnabledFor(logging.DEBUG)
        if _debug:
            _t0 = time.perf_counter()

        determine(self.inverse, records)

        if _debug:
            _orm_compute.debug(
                "[%.3f ms] determine_inverse %s.%s: %d records",
                (time.perf_counter() - _t0) * 1000,
                self.model_name,
                self.name,
                len(records),
            )

    def determine_domain(
        self, records: BaseModel, operator: str, value: typing.Any
    ) -> typing.Any:
        return determine(self.search, records, operator, value)

    def determine_group_expand(
        self, records: BaseModel, values: typing.Any, domain: DomainType
    ) -> typing.Any:
        return determine(self.group_expand, records, values, domain)


def _make_scalar_get(
    cache_to_record: Callable[[typing.Any], typing.Any],
) -> Callable[..., typing.Any]:
    _PENDING = PENDING
    _base_get = Field.__get__

    def __get__(
        self, record: BaseModel | None, owner: type | None = None
    ) -> typing.Any:
        if record is None:
            return self
        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")
        ids = record._ids
        if len(ids) != 1:
            return _base_get(self, record, owner)
        if self.is_stored_computed and env._core.has_pending_field(self):
            self.recompute(record)
        try:
            value = env.__dict__["_field_cache_memo"][self][ids[0]]
        except KeyError:
            pass
        else:
            if value is not _PENDING:
                return cache_to_record(value)
        return _base_get(self, record, owner)

    return __get__
