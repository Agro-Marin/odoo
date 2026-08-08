from __future__ import annotations

import typing

from ...fields.base import determine
from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from ...fields.base import Field


class _FieldComputeMixin(_ModelStubs):
    """Run one field's ``compute`` over a recordset, then validate what it wrote.

    A leaf on purpose. Its only caller is Layer 1 -- ``Field.compute_value``
    (``fields/base.py``) -- so nothing in the composition depends on it, which
    is what lets it depend on ``traversal`` (``filtered``), ``_constraints``
    (``_validate_fields``) and ``_metadata`` (``pool``) without closing a cycle.

    It lived on ``base.py``, and the obvious home when moving it off was
    ``RecomputeMixin`` -- which is wrong, and ``mixin_coupling_check`` said so
    immediately: ``traversal`` already reaches ``recompute`` through
    ``flush_model``, so adding ``recompute -> traversal`` via ``filtered`` made
    a 2-cycle. Distinct from ``RecomputeMixin`` in any case: that schedules and
    drives recomputation across fields, this executes one field's compute.
    """

    __slots__ = ()

    def _compute_field_value(self, field: Field) -> None:
        determine(field.compute, self)

        if field.store and any(self._ids):
            fnames = [f.name for f in self.pool.field_computed[field]]
            self.filtered("id")._validate_fields(fnames)
