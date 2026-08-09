import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.db import BaseCursor
    from odoo.modules.db import FunctionStatus
    from odoo.orm.components.model_graph import ModelGraph
    from odoo.orm.fields import Field
    from odoo.orm.models import BaseModel

    from ._init_phase import InitModelsPhase


class _RegistryStubs:
    __slots__ = ()

    if typing.TYPE_CHECKING:
        init_phase: InitModelsPhase
        """The open init_models() window; raises outside it (see Registry)."""

        model_graph: ModelGraph
        models: dict[str, type[BaseModel]]
        not_null_fields: set[Field]
        _constraint_queue: dict[typing.Any, Callable[[BaseCursor], None]]
        has_unaccent: FunctionStatus
        """Tri-state, NOT a bool: ``MISSING`` / ``PRESENT`` / ``INDEXABLE``.

        ``_registry_schema.check_indexes`` branches on all three -- only
        ``INDEXABLE`` (``unaccent`` declared ``IMMUTABLE``) may be used inside a
        trigram index expression, while ``PRESENT`` merely warns.  Declared
        ``bool`` until 19.0-marin, which made that comparison statically
        unsatisfiable (a ``bool`` is 0 or 1, ``INDEXABLE`` is 2) and reported it
        as ``comparison-overlap``; the branch it called dead is the one that
        runs on every database built from a template carrying an immutable
        ``unaccent``.  ``has_trigram`` really is a bool -- the asymmetry is why
        the wrong declaration read as plausible.
        """
        has_trigram: bool
        unaccent: typing.Any
