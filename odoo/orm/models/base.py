"""BaseModel — the core ORM class, plus the Model subclass.

Operational logic lives in the mixins; this file holds model identity,
field/method discovery, and coordination.
"""

import collections
import functools
import logging
import typing
from collections import defaultdict
from inspect import getmembers

from odoo.exceptions import UserError

from .. import decorators as api
from .._recordset import set_base_model
from ..fields.base import Field, determine
from ..helpers import own_class_memo
from .metaclass import MetaModel
from .mixins import (
    AccessMixin,
    CacheMixin,
    CopyMixin,
    CreateMixin,
    EnvironmentMixin,
    ExportMixin,
    IterationMixin,
    LifecycleMixin,
    LoadMixin,
    ReadGroupMixin,
    ReadMixin,
    RecomputeMixin,
    SchemaMixin,
    SearchMixin,
    TranslationMixin,
    TraversalMixin,
    UnlinkMixin,
    WriteMixin,
)
from .mixins._constraints import _ConstraintsMixin
from .mixins._magic_fields import _MagicFieldsMixin
from .mixins._metadata import _ModelMetadataMixin
from .mixins._properties import _PropertiesMixin
from .mixins._query import _QueryMixin

_logger = logging.getLogger("odoo.models")
_orm_crud = logging.getLogger("odoo.orm.crud")


class BaseModel(
    CreateMixin,
    WriteMixin,
    UnlinkMixin,
    CopyMixin,
    IterationMixin,
    TraversalMixin,
    CacheMixin,
    RecomputeMixin,
    EnvironmentMixin,
    LifecycleMixin,
    ReadMixin,
    SearchMixin,
    ReadGroupMixin,
    TranslationMixin,
    SchemaMixin,
    ExportMixin,
    LoadMixin,
    AccessMixin,
    _PropertiesMixin,
    _QueryMixin,
    _ConstraintsMixin,
    _MagicFieldsMixin,
    _ModelMetadataMixin,
    metaclass=MetaModel,
):
    """Base class for Odoo models.

    Odoo models are created by inheriting one of the following:

    *   :class:`Model` for regular database-persisted models

    *   :class:`TransientModel` for temporary data, stored in the database but
        automatically vacuumed every so often

    *   :class:`AbstractModel` for abstract super classes meant to be shared by
        multiple inheriting models

    The system automatically instantiates every model once per database. Those
    instances represent the available models on each database, and depend on
    which modules are installed on that database. The actual class of each
    instance is built from the Python classes that create and inherit from the
    corresponding model.

    Every model instance is a "recordset", i.e., an ordered collection of
    records of the model. Recordsets are returned by methods like
    :meth:`~.browse`, :meth:`~.search`, or field accesses. Records have no
    explicit representation: a record is represented as a recordset of one
    record.

    To create a class that should not be instantiated,
    the :attr:`~odoo.models.BaseModel._register` attribute may be set to False.
    """

    __slots__ = ["_ids", "_prefetch_ids", "env"]

    # MetaModel reads this out of the raw class-body ``attrs`` dict, not off the
    # class, so unlike the rest of the metadata (now in _ModelMetadataMixin) it
    # cannot be inherited: attrs.get("_register", True) would be True and
    # BaseModel would try to register itself as an addon model.
    _register: bool = False

    def _valid_field_parameter(self, field: Field, name: str) -> bool:
        """Return whether the given parameter name is valid for the field."""
        return name == "related_sudo"

    @api.model
    def _post_model_setup__(self) -> None:
        """Method called after the model has been setup."""
        pass

    @property
    def _ondelete_methods(self) -> list:
        """Return a list of methods implementing checks before unlinking."""

        def is_ondelete(func):
            return callable(func) and hasattr(func, "_ondelete")

        cls = self.env.registry[self._name]
        return own_class_memo(
            cls,
            "_ondelete_methods__",
            lambda: [func for _, func in getmembers(cls, is_ondelete)],
        )

    @property
    def _onchange_methods(self) -> dict[str, list]:
        """Return a dictionary mapping field names to onchange methods."""

        def is_onchange(func):
            return callable(func) and hasattr(func, "_onchange")

        cls = self.env.registry[self._name]

        def build():
            methods = defaultdict(list)
            for _attr, func in getmembers(cls, is_onchange):
                missing = []
                for name in func._onchange:
                    if name in cls._fields:
                        methods[name].append(func)
                    else:
                        missing.append(name)
                if missing:
                    _logger.warning(
                        "@api.onchange%r parameters must be field names -> not valid: %s",
                        func._onchange,
                        missing,
                    )

            def onchange_default(field, self):
                value = field.convert_to_write(self[field.name], self)
                condition = f"{field.name}={value}"
                defaults = self.env["ir.default"]._get_model_defaults(
                    self._name, condition
                )
                self.update(defaults)

            for name, field in cls._fields.items():
                if field.change_default:
                    methods[name].append(functools.partial(onchange_default, field))

            return dict(methods)

        return own_class_memo(cls, "_onchange_methods__", build)

    @api.model
    def _rec_name_fallback(self) -> str:
        return self._rec_name or "id"

    @api.depends(
        lambda self: (
            (self._rec_name,) if self._rec_name and self._rec_name != "id" else ()
        )
    )
    def _compute_display_name(self) -> None:
        """Compute the value of the `display_name` field.

        The `display_name` field is a textual representation of the record.
        This method can be overridden to change the representation.  If needed,
        it can be made field-dependent using :attr:`~odoo.api.depends` and
        context-dependent using :attr:`~odoo.api.depends_context`.
        """
        if self._rec_name:
            convert = self._fields[self._rec_name].convert_to_display_name
            for record in self:
                record.display_name = convert(record[self._rec_name], record)
        else:
            for record in self:
                record.display_name = f"{record._name},{record.id}"

    @api.model
    def name_create(self, name: str) -> tuple[int, str]:
        """Create a new record by calling :meth:`~.create` with only one value
        provided: the display name of the new record.

        The new record will be initialized with any default values
        applicable to this model, or provided through the context. The usual
        behavior of :meth:`~.create` applies.

        :param name: display name of the record to create
        :return: the (id, display_name) pair value of the created record
        :raise UserError: if the model has no ``_rec_name`` defined.
        """
        if not self._rec_name:
            raise UserError(
                f"Cannot execute name_create: no _rec_name defined on {self._name}"
            )
        record = self.create({self._rec_name: name})
        return record.id, record.display_name

    def get_base_url(self) -> str:
        """Return the root URL for this record.

        By default the ``web.base.url`` system parameter; may be overridden
        per model.

        :return: the base url for this record
        """
        if len(self) > 1:
            raise ValueError(f"Expected singleton or no record: {self}")
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url")

    def _compute_field_value(self, field: Field) -> None:
        determine(field.compute, self)

        if field.store and any(self._ids):
            fnames = [f.name for f in self.pool.field_computed[field]]
            self.filtered("id")._validate_fields(fnames)

    @property
    @api.deprecated("Deprecated since 19.0, use self.env.cr directly")
    def _cr(self) -> typing.Any:
        return self.env.cr


collections.abc.Set.register(BaseModel)
collections.abc.Sequence.register(BaseModel)

set_base_model(BaseModel)


AbstractModel = BaseModel


class Model(AbstractModel):
    """Main super-class for regular database-persisted Odoo models.

    Odoo models are created by inheriting from this class::

        class ResUsers(Model): ...

    The system will later instantiate the class once per database (on
    which the class' module is installed).
    """

    _auto: bool = True
    _register: bool = False
    _abstract: typing.Literal[False] = False
