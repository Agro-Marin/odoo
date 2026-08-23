import typing

if typing.TYPE_CHECKING:
    from odoo.db import FunctionStatus
    from odoo.models import BaseModel

    from ._init_phase import InitModelsPhase


class _RegistryStubs:
    if typing.TYPE_CHECKING:
        models: dict[str, type[BaseModel]]

        @property
        def init_phase(self) -> InitModelsPhase:
            pass

        has_unaccent: FunctionStatus

        has_trigram: bool
        unaccent: typing.Any
