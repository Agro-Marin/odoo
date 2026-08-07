import typing

if typing.TYPE_CHECKING:
    from odoo.tools import Query

    from .._typing import BaseModel, ModelLike
    from ..domain import Domain
    from ..primitives import ContextType
    from ..runtime import Environment


class _FieldStubs:
    __slots__ = ()

    if typing.TYPE_CHECKING:
        name: str
        model_name: str
        string: str | None
        help: str | None
        type: str
        store: bool
        index: str | None
        translate: bool
        is_text: bool
        company_dependent: bool
        aggregator: str | None
        falsy_value: typing.Any
        inherited_field: typing.Any
        _column_type: tuple[str, str] | None

        bypass_search_access: bool
        check_company: bool
        context: ContextType
        relation: str | None
        column1: str | None
        column2: str | None

        def _is_context_dependent(self, env: Environment) -> bool: ...
        def _company_dependent_fallback_raw(
            self, records: typing.Any
        ) -> typing.Any: ...

        def get_comodel_domain(self, model: ModelLike) -> Domain: ...
        def get_currency_field(self, model: ModelLike) -> str | None: ...
        def join(
            self, model: ModelLike, alias: str, query: Query
        ) -> tuple[BaseModel, str]: ...
        def _add_default_values(
            self, env: typing.Any, values: dict[str, typing.Any]
        ) -> list[typing.Any] | dict[str, typing.Any]: ...
        def convert_to_read_multi(
            self,
            values: list[typing.Any],
            records: ModelLike,
            use_display_name: bool = True,
        ) -> list[typing.Any]: ...
        def _get_stored_translations(
            self, record: BaseModel
        ) -> dict[str, str] | None: ...
