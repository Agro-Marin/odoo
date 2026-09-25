import typing

if typing.TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from odoo.db import BaseCursor, FunctionStatus
    from odoo.models import BaseModel

    from ._init_phase import InitModelsPhase


class _RegistryStubs:
    if typing.TYPE_CHECKING:
        db_name: str
        models: dict[str, type[BaseModel]]
        ready: bool

        def cursor(self, /, readonly: bool = False) -> BaseCursor: ...

        @property
        def init_phase(self) -> InitModelsPhase:
            pass

        def ensure_init_models_window(self) -> AbstractContextManager[None]: ...

        unaccent_status: FunctionStatus

        has_trigram: bool
        unaccent: typing.Any

        @property
        def model_names_by_inheritance_root(self) -> dict[str, tuple[str, ...]]:
            pass
