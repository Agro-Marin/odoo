"""High-level objects for fields."""

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
from odoo.libs.constants import PREFETCH_MAX
from odoo.tools import SQL, reset_cached_properties
from odoo.tools.misc import PENDING, SENTINEL, ReadonlyDict, Sentinel, unique

from .._recordset import base_model, is_model_class, is_recordset
from ..domain import Domain
from ..primitives import COLLECTION_TYPES
from ._field_convert import _FieldConvertMixin
from ._field_description import _FieldDescriptionMixin
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


def expand_ids(id0: IdType, ids: Iterable[IdType]) -> Iterator[IdType]:
    """Return an iterator of unique ids from the concatenation of ``[id0]`` and
    ``ids``, and of the same kind (all real or all new).
    """
    yield id0
    seen = {id0}
    kind = bool(id0)
    for id_ in ids:
        if id_ not in seen and bool(id_) == kind:
            yield id_
            seen.add(id_)


def _recordset_like(records: BaseModel, ids: Iterable[IdType]) -> BaseModel:
    """Build a recordset over *ids* sharing *records*' env and prefetch group.

    Inlines ``object.__new__`` + slot assignment to skip ``__init__`` (hot path).
    Unlike ``browse``, the original ``_prefetch_ids`` is preserved so later reads
    keep the broader prefetch group — hence ``Field._assign_*`` cannot use
    ``browse``.
    """
    rs = object.__new__(records.__class__)
    rs.env = records.env
    rs._ids = tuple(ids)
    rs._prefetch_ids = records._prefetch_ids
    return rs


IR_MODELS: tuple[str, ...] = (
    "ir.model",
    "ir.model.data",
    "ir.model.fields",
    "ir.model.fields.selection",
    "ir.model.relation",
    "ir.model.constraint",
    "ir.module.module",
)

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
    """Return the list of successively overridden values of attribute ``name``
    in mro order on ``model`` that satisfy ``predicate``.  Model registry
    classes are ignored.
    """
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
    """Simple helper for calling a method given as a string or a function.

    :param needle: callable or name of method to call on ``records``
    :param BaseModel records: recordset to call ``needle`` on or with
    :param args: additional arguments to pass to the determinant
    :returns: the determined value if the determinant is a method name or callable
    :raise TypeError: if ``records`` is not a recordset, or ``needle`` is not
                      a callable or valid method name
    """
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


class Field[T](_FieldDescriptionMixin, _FieldConvertMixin, _FieldSqlMixin):
    """The field descriptor contains the field definition, and manages accesses
    and assignments of the corresponding field on records. The following
    attributes may be provided when instantiating a field:

    :param str string: the label of the field seen by users; if not
        set, the ORM takes the field name in the class (capitalized).

    :param str help: the tooltip of the field seen by users

    :param bool readonly: whether the field is readonly (default: ``False``)

        This only has an impact on the UI. Any field assignation in code will work
        (if the field is a stored field or an inversable one).

    :param bool required: whether the value of the field is required (default: ``False``)

    :param str index: whether the field is indexed in database, and the kind of index.
        Note: this has no effect on non-stored and virtual fields.
        The possible values are:

        * ``"btree"`` or ``True``: standard index, good for many2one
        * ``"btree_not_null"``: BTREE index without NULL values (useful when most
                                values are NULL, or when NULL is never searched for)
        * ``"trigram"``: Generalized Inverted Index (GIN) with trigrams (good for full-text search)
        * ``None`` or ``False``: no index (default)

    :param default: the default value for the field; this is either a static
        value, or a function taking a recordset and returning a value; use
        ``default=None`` to discard default values for the field
    :type default: value or callable

    :param str groups: comma-separated list of group xml ids (string); this
        restricts the field access to the users of the given groups only

    :param bool company_dependent: whether the field value is dependent of the current company;

        The value is stored on the model table as jsonb dict with the company id as the key.

        The field's default values stored in model ir.default are used as fallbacks for
        unspecified values in the jsonb dict.

    :param bool copy: whether the field value should be copied when the record
        is duplicated (default: ``True`` for normal fields, ``False`` for
        ``one2many`` and computed fields, including property fields and
        related fields)

    :param bool store: whether the field is stored in database
        (default:``True``, ``False`` for computed fields)

    :param bool default_export_compatible: whether the field must be exported
        by default in an import-compatible export

    :param str search: name of a method that implements search on the field.
        The method takes an operator and value. Basic domain optimizations are
        ran before calling this function.
        For instance, all ``'='`` are transformed to ``'in'``, and boolean
        fields conditions are made such that operator is ``'in'``/``'not in'``
        and value is ``[True]``.

        The method should ``return NotImplemented`` if it does not support the
        operator.
        In that case, the ORM can try to call it with other, semantically
        equivalent, operators. For instance, try with the positive operator if
        its corresponding negative operator is not implemented.
        The method must return a :ref:`reference/orm/domains` that replaces
        ``(field, operator, value)`` in its domain.

        A stored field can also have a search method; it is invoked to rewrite
        the condition, which is useful e.g. for sanitizing the values used.

        .. code-block:: python

            def _search_partner_ref(self, operator, value):
                if operator not in ("in", "like"):
                    return NotImplemented
                ...  # add your logic here, example
                return Domain("partner_id.ref", operator, value)

    .. rubric:: Aggregation

    :param str aggregator: default aggregate function used by the webclient
        on this field when using "Group By" feature.

        Supported aggregators are:

        * ``count`` : number of rows
        * ``count_distinct`` : number of distinct rows
        * ``bool_and`` : true if all values are true, otherwise false
        * ``bool_or`` : true if at least one value is true, otherwise false
        * ``max`` : maximum value of all values
        * ``min`` : minimum value of all values
        * ``avg`` : the average (arithmetic mean) of all values
        * ``sum`` : sum of all values

    :param str group_expand: function used to expand results when grouping on the
        current field for kanban/list/gantt views. For selection fields,
        ``group_expand=True`` automatically expands groups for all selection keys.

        .. code-block:: python

            @api.model
            def _read_group_selection_field(self, values, domain):
                return ["choice1", "choice2", ...]  # available selection choices.


            @api.model
            def _read_group_many2one_field(self, records, domain):
                return records + self.search([custom_domain])

    .. rubric:: Computed Fields

    :param str compute: name of a method that computes the field

        .. seealso:: :ref:`Advanced Fields/Compute fields <reference/fields/compute>`

    :param bool precompute: whether the field should be computed before record insertion
        in database.  Should be used to specify manually some fields as precompute=True
        when the field can be computed before record insertion.
        (e.g. avoid statistics fields based on search/_read_group), many2one
        linking to the previous record, ... (default: `False`)

        .. warning::

            Precomputation only happens when no explicit value and no default
            value is provided to create().  This means that a default value
            disables the precomputation, even if the field is specified as
            precompute=True.

            Precomputing a field can be counterproductive if the records of the
            given model are not created in batch.  Consider the situation were
            many records are created one by one.  If the field is not
            precomputed, it will normally be computed in batch at the flush(),
            and the prefetching mechanism will help making the computation
            efficient.  On the other hand, if the field is precomputed, the
            computation will be made one by one, and will therefore not be able
            to take advantage of the prefetching mechanism.

            Following the remark above, precomputed fields can be interesting on
            the lines of a one2many, which are usually created in batch by the
            ORM itself, provided that they are created by writing on the record
            that contains them.

    :param bool compute_sudo: whether the field should be recomputed as superuser
        to bypass access rights (by default ``True`` for stored fields, ``False``
        for non stored fields)

    :param bool recursive: whether the field has recursive dependencies (the field
        ``X`` has a dependency like ``parent_id.X``); declaring a field recursive
        must be explicit to guarantee that recomputation is correct

    :param str inverse: name of a method that inverses the field (optional)

    :param str related: sequence of field names

        .. seealso:: :ref:`Advanced fields/Related fields <reference/fields/related>`
    """

    type: str
    relational: bool = False
    translate: bool = False
    is_text: bool = False
    falsy_value: T | None = None

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
    _column_type: tuple[str, str] | None = None

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

    name: str = ""
    model_name: str = ""
    comodel_name: str | None = None
    context: ContextType = {}
    """Extra context a relational field applies to its comodel.

    Declared on the base class, with an inert default, for the same reason as
    ``comodel_name``: consumers key on it without first proving the field is
    relational.  ``Environment.cache_key`` is the one that made this load-bearing
    -- its ``active_test`` branch reads ``field.context`` for any field whose
    ``depends_context`` mentions it, so ``@api.depends_context("active_test")``
    on a computed scalar raised ``AttributeError`` on every read of that field.
    """

    store: bool = True
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
    company_dependent: bool = False
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

    _by_type__: dict[str, Field] = {}
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
        """Perform the base setup of a field.

        :param owner: the owner class of the field (the model's definition or registry class)
        :param name: the name of the field
        """
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
        """Return the field parameter attributes as a dictionary."""
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

        if name == "state":
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
        """Initialize the field parameter attributes."""
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
        """Reset the setup done flag so the field will be set up again."""
        self._setup_done = False

    def setup(self, model: BaseModel) -> None:
        """Perform the complete setup of a field."""
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
        """Determine the dependencies and inverse field(s) of ``self``."""
        pass

    def get_depends(self, model: BaseModel) -> tuple[Iterable[str], Iterable[str]]:
        """Return the field's dependencies and cache dependencies."""
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
        """Setup the attributes of a related field."""
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
        """Traverse the fields of the related field `self` except for the last
        one, and return it as a pair `(last_record, last_field)`."""
        for name in self._related_names[:-1]:
            corecord = record[name]
            record = next(iter(corecord), corecord)
        return record, self.related_field

    def _compute_related(self, records: BaseModel) -> None:
        """Compute the related field ``self`` on ``records``."""
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
        """No transformation by default, but allows override."""
        return value

    def _inverse_related(self, records: BaseModel) -> None:
        """Inverse the related field ``self`` on ``records``."""
        record_value = {record: record[self.name] for record in records}
        for record in records:
            target, field = self.traverse_related(record)
            if target and bool(target.id) == bool(record.id):
                target[field.name] = record_value[record]

    def _search_related(self, records: BaseModel, operator: str, value) -> DomainType:
        """Determine the domain to search on field ``self``."""

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
            if can_be_null and field.type == "many2one" and not field.required:
                domain |= Domain(field.name, "=", False)
        return domain

    _related_comodel_name = property(attrgetter("comodel_name"))
    _related_string = property(attrgetter("string"))
    _related_help = property(attrgetter("help"))
    _related_groups = property(attrgetter("groups"))
    _related_aggregator = property(attrgetter("aggregator"))

    @functools.cached_property
    def column_type(self) -> tuple[str, str] | None:
        """Return the actual column type for this field, if stored as a column."""
        return (
            ("jsonb", "jsonb")
            if self.company_dependent or self.translate
            else self._column_type
        )

    @functools.cached_property
    def is_column(self) -> bool:
        """Return whether this field is stored as a database column."""
        return bool(self.store and self.column_type)

    @functools.cached_property
    def is_stored_computed(self) -> bool:
        """Return whether this field is computed and stored in the database."""
        return bool(self.compute and self.store)

    @property
    def base_field(self) -> Self:
        """Return the base field of an inherited field, or ``self``."""
        return self.inherited_field.base_field if self.inherited_field else self

    def _company_dependent_fallback_raw(self, records: BaseModel) -> typing.Any:
        """Raw ``ir.default`` fallback for ``self`` on ``records``'s company.

        Single authority for the fallback lookup, resolved through
        ``env._ir_defaults`` so that the write-side dedup
        (``convert_to_column_insert``), the read-side COALESCE
        (:meth:`get_company_dependent_fallback`) and the flush-side fallbacks
        (``ir.default._get_field_column_fallbacks``) all share one scope.
        """
        return records.env._ir_defaults._get_model_defaults(records._name).get(
            self.name
        )

    def get_company_dependent_fallback(self, records: BaseModel) -> typing.Any:
        assert self.company_dependent
        fallback = self._company_dependent_fallback_raw(records)
        fallback = self.convert_to_cache(fallback, records, validate=False)
        return self.convert_to_record(fallback, records)

    def resolve_depends(self, registry: Registry) -> Iterator[tuple[Field, ...]]:
        """Return the dependencies of `self` as a collection of field tuples."""
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

                if check_precompute and field.type == "many2one":
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
        """Update the database schema to implement this field.

        :param model: an instance of the field's model
        :param columns: a dict mapping column names to their configuration in database
        :return: ``True`` if the field must be recomputed on existing rows
        """
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
            and not (
                self.related_field.type == "binary" and self.related_field.attachment
            )
            and self.related_field.type not in ("one2many", "many2many")
        ):
            join_field = model._fields[self._related_names[0]]
            if (
                join_field.type == "many2one"
                and join_field.store
                and not join_field.compute
            ):
                model.pool.post_init(self.update_db_related, model)
                return False

        return not column

    def update_db_column(self, model: ModelLike, column: dict[str, typing.Any]) -> None:
        """Create/update the column corresponding to ``self``.

        :param model: an instance of the field's model
        :param column: the column's configuration (dict) if it exists, or ``None``
        """
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
        """Convert the given database column to the type of the field."""
        sql.convert_column(model.env.cr, model._table, self.name, self.column_type[1])

    def update_db_notnull(
        self, model: ModelLike, column: dict[str, typing.Any]
    ) -> None:
        """Add or remove the NOT NULL constraint on ``self``.

        :param model: an instance of the field's model
        :param column: the column's configuration (dict) if it exists, or ``None``
        """
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
        """Compute a stored related field directly in SQL."""
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
        """Read the value of ``self`` on ``records``, and store it in cache."""
        if not self.column_type:
            raise NotImplementedError(f"Method read() undefined on {self}")

    def create(self, record_values: Collection[tuple[BaseModel, typing.Any]]) -> None:
        """Write the value of ``self`` on the given records, which have just
        been created.

        :param record_values: a list of pairs ``(record, value)``, where
            ``value`` is in the format of method :meth:`BaseModel.write`
        """
        for record, value in record_values:
            self.mark_dirty(record, value)

    def mark_dirty(self, records: BaseModel, value: typing.Any) -> None:
        """Apply a write value for ``self`` on ``records``.  For stored scalar
        fields this converts the value, updates the cache, and marks it dirty
        (actual SQL happens at flush time).  Relational and attachment field
        overrides may execute immediate database operations.

        This is the field-level counterpart of :meth:`BaseModel.write`.

        Overrides MUST start by calling :meth:`_mark_dirty_prologue` (or
        delegate to ``super().mark_dirty()``): skipping it leaves a pending
        recomputation alive, which later silently overwrites the explicit
        write (enforced by ``test_mark_dirty_prologue``).

        :param records: recordset to update
        :param value: a value in any format
        """
        records, cache_value = self._mark_dirty_prologue(records, value)
        if not records:
            return

        self._update_cache(records, cache_value, dirty=True)

    def _mark_dirty_prologue(
        self, records: BaseModel, value: typing.Any
    ) -> tuple[BaseModel, typing.Any]:
        """Shared entry sequence of every ``mark_dirty`` implementation:
        cancel the pending recomputation of ``self`` on ``records`` (an
        explicit write always wins over a scheduled compute), convert the
        value to cache format, and narrow ``records`` to those actually
        modified.  Returns ``(records, cache_value)``.
        """
        records.env.remove_to_compute(self, records)

        cache_value = self.convert_to_cache(value, records)
        records = self._filter_not_equal(records, cache_value)
        return records, cache_value

    def _is_context_dependent(self, env: Environment) -> bool:
        """Whether this field's cache is keyed per context in ``env``.

        See the shape note above. ``True`` for translatable, company-dependent,
        and any field whose value varies with the environment context.
        """
        return self in env._field_depends_context

    def _get_cache(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        """Return the field's cache: a ``{record_id: cache_value}`` mapping
        (possibly environment-specific).

        Returns the same mapping instance for a given environment across calls,
        unless the transaction was entirely invalidated.
        """
        field_cache = env._field_cache_memo.get(self)
        if field_cache is not None:
            return field_cache
        field_cache = self._get_cache_impl(env)
        env._field_cache_memo[self] = field_cache
        return field_cache

    def _get_cache_impl(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
        """Implementation of :meth:`_get_cache`.  This method may provide a
        view to the actual cache, depending on the needs of the field.
        """
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
        """Invalidate cached values for the given ids (all if ``None``).

        Delegates to :meth:`FieldCache.invalidate` with the shape bit (see the
        shape note above): the cache owns the nested-shape decode, including
        the mixed setup-window state and dict-valued flat caches.

        Pass ``keep_dirty=True`` when the invalidation is a consistency side
        effect rather than a caller request; see :meth:`FieldCache.invalidate`.
        """
        env._core.invalidate(
            self,
            ids,
            context_dependent=self._is_context_dependent(env),
            keep_dirty=keep_dirty,
        )

    def _get_all_cache_ids(self, env: Environment) -> Mapping[IdType, typing.Any]:
        """Return all the record ids that have a value in cache in any environment.

        Delegates to :meth:`FieldCache.all_cached_ids` with the shape bit (see
        the shape note above). The result is a read-only mapping view.
        """
        return env._core.all_cached_ids(
            self, context_dependent=self._is_context_dependent(env)
        )

    def _cache_missing_ids(self, records: ModelLike) -> Iterator[IdType]:
        """Generator of ids that have no value in cache.

        Records with :data:`PENDING` (stored computed fields awaiting
        recomputation) are treated as missing.
        """
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
        """Return the subset of ``records`` for which the value of ``self`` is
        either not in cache, or different from ``cache_value``.
        """
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
        """Return a recordset including ``record`` to prefetch the field."""
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

    def _insert_cache(self, records: BaseModel, values: Iterable) -> None:
        """Update the cache of the given records with the corresponding values,
        ignoring the records that already have a value in cache.  This enables
        to keep the pending updates of those records, and flush them later.
        """
        field_cache = self._get_cache(records.env)
        collections.deque(
            map(field_cache.setdefault, records._ids, values, strict=True), maxlen=0
        )

    def _update_cache_items(
        self, env: Environment, items: Iterable[tuple[IdType, typing.Any]]
    ) -> None:
        """Cache a *different* value per record, in one pass.

        The many-values counterpart of :meth:`_update_cache`, which broadcasts a
        single value: it resolves the field cache and runs the dirty guard once
        for the whole batch instead of once per record.  Callers that own a
        ``[(id, value), ...]`` result -- ``UPDATE ... RETURNING`` in the
        ``parent_path`` maintenance, above all -- were looping
        ``field._update_cache(self.browse(id_), value)``, which builds a
        throwaway singleton, re-resolves the cache and re-checks the dirty set
        for every row of the hierarchy.

        Values are taken as already in cache format (as :meth:`_update_cache`
        takes ``cache_value``); ``items`` is consumed once.

        :raises ValueError: when any of the ids currently holds a pending write
            for ``self`` -- same contract as :meth:`_update_cache` without
            ``dirty=True``.
        """
        items = list(items)
        if not items:
            return

        if self.is_column:
            dirty_ids = env._core.get_dirty(self)
            if dirty_ids:
                overlap = sorted(dirty_ids.intersection(id_ for id_, _ in items))
                if overlap:
                    raise ValueError(
                        f"Field._update_cache_items: refusing to overwrite the "
                        f"dirty value of {self} on records {overlap} without "
                        f"dirty=True; the pending write would be lost"
                    )

        self._get_cache(env).update(items)

    def _update_cache(
        self, records: ModelLike, cache_value: typing.Any, dirty: bool = False
    ) -> None:
        """Update the value in the cache for the given records, and optionally
        make the field dirty for those records (for stored column fields only).

        One can normally make a clean field dirty but not the other way around.
        Updating a dirty field without ``dirty=True`` is a programming error and
        raises ``ValueError`` — silently overwriting a dirty value would lose
        the pending write at the next flush.

        :param dirty: whether ``field`` must be made dirty on ``record`` after
            the update
        :raises ValueError: when ``dirty=False`` and at least one of ``records``
            currently has a dirty value for ``self``
        """
        env = records.env

        if self.is_column and not dirty:
            dirty_ids = env._core.get_dirty(self)
            if dirty_ids and not dirty_ids.isdisjoint(records._ids):
                overlap = sorted(dirty_ids.intersection(records._ids))
                raise ValueError(
                    f"Field._update_cache: refusing to overwrite the dirty "
                    f"value of {self} on records {overlap} without dirty=True; "
                    f"the pending write would be lost"
                )

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
        """return the value of field ``self`` on ``record``"""
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
        """Resolve ``self`` on a single ``record`` whose value is not cached.

        Tail of :meth:`__get__`, invoked after the cache-hit fast path and
        PENDING eviction. Fetches (from DB or origin), computes, builds a
        delegate parent, or falls back to the default — updating the cache along
        the way — then returns the value in record format. ``field_cache`` is the
        already-resolved cache dict for ``self`` in ``env`` (it may be re-read
        here, since a compute can invalidate the whole cache).
        """
        if self.store and record_id:
            recs = self._to_prefetch(record)
            try:
                recs._fetch_field(self)
                fallback_single = False
            except AccessError:
                if len(recs) == 1:
                    raise
                fallback_single = True
            if fallback_single:
                record._fetch_field(self)
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
            try:
                for rec in recs:
                    rec_id = rec._ids[0]
                    if origin_id := (rec_id or getattr(rec_id, "origin", None)):
                        rec_origin = spawn(recs_env, (origin_id,), origin_prefetch)
                        value = self.convert_to_cache(
                            rec_origin[self.name], rec, validate=False
                        )
                        self._update_cache(rec, value)
                fallback_single = False
            except AccessError, KeyError, MissingError:
                if len(recs) == 1:
                    raise
                fallback_single = True
            if fallback_single:
                value = self.convert_to_cache(
                    record._origin[self.name], record, validate=False
                )
                self._update_cache(record, value)
            field_cache = self._get_cache(env)
            value = field_cache[record_id]

        elif self.compute:
            if env.is_protected(self, record):
                value = self.convert_to_cache(False, record, validate=False)
                self._update_cache(record, value)
            else:
                recs = record if self.recursive else self._to_prefetch(record)
                try:
                    self.compute_value(recs)
                    fallback_single = False
                except AccessError, MissingError:
                    fallback_single = True
                if fallback_single:
                    self.compute_value(record)
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

        elif self.type == "many2one" and self.delegate and not record_id:

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
        """Set the value of field ``self`` on ``records``.

        Records are partitioned into three buckets, each with different
        semantics (see the ``_assign_*`` methods for details):

        - **Protected**: currently being computed — direct cache write, no
          business logic, no recomputation triggers.
        - **New**: unsaved records (``NewId``) — cache write with dependency
          tracking via ``modified()``, but no access checks or validation.
        - **Real**: saved records with a database id — full ``write()`` flow
          including access checks, audit, validation, and constraints.
        """
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
        """Assign ``value`` to protected records (being computed).

        Minimal path: direct cache write via :meth:`mark_dirty`, no access
        checks, ``modified()`` triggers, or recomputation. Used inside compute
        methods that set the field as part of their own computation.
        """
        self.mark_dirty(_recordset_like(records, ids), value)

    def _assign_new(
        self, records: BaseModel, ids: list[typing.Any], value: typing.Any
    ) -> None:
        """Assign ``value`` to new (unsaved) records.

        Updates the cache and triggers ``modified()`` for dependency tracking,
        but skips access checks and validation (new records are built in
        onchange/``new()`` where the full ``write()`` flow is inappropriate).
        For inherited fields, also propagates to a new parent record.
        """
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
        """Assign ``value`` to real (saved) records.

        Full ``write()`` path: round-trips through :meth:`convert_to_write` then
        :meth:`BaseModel.write` (access checks, audit, validation, recompute).
        """
        records = _recordset_like(records, ids)
        write_value = self.convert_to_write(value, records)
        records.write({self.name: write_value})

    def ensure_access(self, record: ModelLike) -> None:
        """Check that the current user has read access to this field.

        Must be called before reading from the field cache when bypassing
        :meth:`__get__`.  No-op when ``env.su`` is True or the field has
        no ``groups`` restriction.
        """
        env = record.env
        if not (not self.groups or env.su or record._has_field_access(self, "read")):
            record._check_field_access(self, "read")

    def read_cache(self, record_id: int, env: Environment) -> tuple[bool, typing.Any]:
        """Read a single value from this field's cache.

        Returns ``(True, value)`` on cache hit, ``(False, SENTINEL)`` on miss.
        Treats :data:`PENDING` as a miss (stored computed field awaiting
        recomputation).

        Callers must ensure :meth:`ensure_computed` has been called first —
        this method does NOT trigger recomputation.
        """
        value = self._get_cache(env).get(record_id, SENTINEL)
        if value is SENTINEL or value is PENDING:
            return False, SENTINEL
        return True, value

    def ensure_computed(self, records: ModelLike) -> None:
        """Ensure pending recomputations of ``self`` are processed.

        Must be called before reading from the field cache for stored computed
        fields.  This is automatically handled by :meth:`__get__`, but code
        that bypasses ``__get__`` (e.g. direct cache access in
        ``_read_format``) must call this explicitly.

        No-op when the field is not stored-computed or has no pending entries
        in ``compute_engine``.
        """
        if self.is_stored_computed and records.env._core.has_pending_field(self):
            self.recompute(records)

    def recompute(self, records: ModelLike) -> None:
        """Process the pending computations of ``self`` on ``records``. This
        should be called only if ``self`` is computed and stored.
        """
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
            """Apply `func` on `records`, ignoring non-existent records."""
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
                ids = expand_ids(record.id, to_compute_ids)
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
        """Invoke the compute method on ``records``; the results are in cache."""
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
        """Given the value of ``self`` on ``records``, inverse the computation."""
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
        """Return a domain representing a condition on ``self``."""
        return determine(self.search, records, operator, value)

    def determine_group_expand(
        self, records: BaseModel, values: typing.Any, domain: DomainType
    ) -> typing.Any:
        """Expand the groups for ``self`` when grouping (via ``group_expand``)."""
        return determine(self.group_expand, records, values, domain)


def _make_scalar_get(
    cache_to_record: Callable[[typing.Any], typing.Any],
) -> Callable[..., typing.Any]:
    """Generate a ``__get__`` override for scalar field types.

    The generated closure inlines the :meth:`Field.__get__` optimizations: the
    ``not self.groups`` ACL short-circuit, the triple dict lookup
    (memo->cache->id), the ``has_pending()`` guard before ``recompute()``, and
    the PENDING check. Used as::

        __get__ = _make_scalar_get(lambda v: v or 0)

    The lookup is written out rather than delegated to
    :func:`~odoo.libs._field_access.scalar_cache_get`, which stays the readable
    reference implementation (and the oracle its own suite pins).  There is no
    Rust counterpart -- the crate documents why it would lose on this shape --
    so the helper was a plain Python call on the hottest path in the ORM,
    costing ~26 ns of pure call overhead per scalar read (71 ns delegated vs
    45 ns inlined).  ``KeyError`` and ``PENDING`` both mean "fall through to the
    canonical path", exactly as the helper's ``SENTINEL`` return does, and this
    is the shape :meth:`Field.__get__` itself already uses.

    :param cache_to_record: ``callable(cache_value) -> record_value``.
    """
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
