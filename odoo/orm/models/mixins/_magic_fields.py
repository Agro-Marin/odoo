from ..metaclass import MetaModel
from ._metadata import _ModelMetadataMixin

from ...fields.misc import Id  # isort: skip
from ...fields.textual import Char  # isort: skip


class _MagicFieldsMixin(_ModelMetadataMixin, metaclass=MetaModel):
    __slots__ = ()

    _register = False

    id = Id()
    display_name = Char(
        string="Display Name",
        compute="_compute_display_name",
        search="_search_display_name",
    )
