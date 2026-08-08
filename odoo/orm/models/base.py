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


collections.abc.Set.register(BaseModel)
collections.abc.Sequence.register(BaseModel)

set_base_model(BaseModel)


AbstractModel = BaseModel


class Model(AbstractModel):
    _auto: bool = True
    _register: bool = False
    _abstract: typing.Literal[False] = False
