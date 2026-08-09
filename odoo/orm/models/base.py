import collections
import logging
import typing

from .. import decorators as api
from .._recordset import set_base_model
from ..fields.base import Field
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
from .mixins._display_name import _DisplayNameMixin
from .mixins._field_compute import _FieldComputeMixin
from .mixins._hooks import _HooksMixin
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
    _DisplayNameMixin,
    _FieldComputeMixin,
    _HooksMixin,
    # ORDER IS LOAD-BEARING for these last two, and for no other pair in this
    # list. `_MagicFieldsMixin` SUBCLASSES `_ModelMetadataMixin` -- it declares
    # `id` and `display_name` as Field instances, and `Field.__set_name__` reads
    # `owner._name`, which is a metadata attribute -- so a subclass appears here
    # beside its own base. Python requires the subclass first; swapping just
    # these two entries fails at import with "Cannot create a consistent method
    # resolution order (MRO)".
    #
    # Listing the base explicitly is deliberate, not redundancy to tidy away:
    # dropping it leaves the MRO byte-identical *today*, purely because
    # `_MagicFieldsMixin` happens to inherit it. This line is what says BaseModel
    # wants the metadata regardless of that.
    _MagicFieldsMixin,
    _ModelMetadataMixin,
    metaclass=MetaModel,
):
    __slots__ = ["_ids", "_prefetch_ids", "env"]

    _register: bool = False

    def _valid_field_parameter(self, field: Field, name: str) -> bool:
        return name == "related_sudo"

    @api.model
    def _post_model_setup__(self) -> None:
        pass

    def get_base_url(self) -> str:
        if len(self) > 1:
            raise ValueError(f"Expected singleton or no record: {self}")
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url")

    @property
    @api.deprecated("Deprecated since 19.0, use self.env.cr directly")
    def _cr(self) -> typing.Any:
        return self.env.cr


# A recordset is ordered, indexable and de-duplicated, which is neither ABC on
# its own, so it claims both. That is a real choice with two consequences a
# reader will not guess, and neither is written anywhere else:
#
# 1. `functools.singledispatch` cannot dispatch on both. Registering handlers
#    for `Set` and `Sequence` and passing a recordset raises
#    `RuntimeError: Ambiguous dispatch` -- or, depending on registration order,
#    silently picks one. Nothing in odoo/ or addons/ dispatches this way today;
#    a serialiser that starts to will hit this and the traceback will not
#    mention recordsets.
# 2. `orm/primitives.py::COLLECTION_TYPES` is `(list, tuple, AbstractSet)`, so
#    **every recordset is a COLLECTION_TYPE**. Domain optimisation and
#    `Field.filter_function` branch on that constant, and at least one site was
#    written by someone who did not expect it: the relational inequality guard
#    in `orm/domain/optimizations.py` reads
#    `isinstance(value, (str, bool, *COLLECTION_TYPES)) or is_recordset(value)`,
#    whose second term is already implied by the first. Do not "simplify" that
#    one -- the two terms state two intentions, and only this registration makes
#    one imply the other.
#
# Measured 2026-08-09 before this comment was written: no production path is
# broken by either, because `Domain.optimize` normalises a recordset comparand
# to ids before any consumer of COLLECTION_TYPES sees it. Dropping the `Set`
# registration would change `isinstance(x, COLLECTION_TYPES)` across the whole
# tree, which is why this is documented rather than "tidied".
collections.abc.Set.register(BaseModel)
collections.abc.Sequence.register(BaseModel)

set_base_model(BaseModel)


AbstractModel = BaseModel


class Model(AbstractModel):
    _auto: bool = True
    _register: bool = False
    _abstract: typing.Literal[False] = False
