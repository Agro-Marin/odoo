"""The two fields every model has: ``id`` and ``display_name``.

Declared here rather than in ``BaseModel`` for one structural reason.
``IterationMixin.__int__`` reads ``self.id``, and while ``id`` was declared in
``base.py`` that single read was the **last edge closing the nine-unit mixin
cycle**: ``base.py -> {create|env|traversal} -> iteration -> base.py``. Hosting
the magic fields on a leaf removes ``base.py``'s participation, and the largest
cycle among the mixins drops from 9 to 2 (see
``tooling/architecture/mixin_coupling_check.py``).

Unlike every other mixin in this package, this class **must** carry
``metaclass=MetaModel``, and the three reasons are worth stating because each is
a silent-failure mode if broken:

* :meth:`odoo.orm.fields.base.Field.__set_name__` appends the field to
  ``owner._field_definitions``, a list that only ``MetaModel.__new__`` creates
  (``attrs.setdefault``). On a plain class the append raises ``AttributeError``.
* ``registration.py`` collects definitions with
  ``for cls in reversed(model_cls._model_classes__): if isinstance(cls,
  MetaModel): ... cls._field_definitions``. A non-``MetaModel`` holder would be
  skipped and **every model would silently lose ``id``**.
* ``_model_classes__`` is derived from ``model_cls.mro()`` filtered by
  ``pool is None``, so this class is picked up automatically by being in the MRO
  — nothing has to register it.

``_register = False`` for the same reason ``BaseModel`` needs it in its own body:
``MetaModel.__new__`` reads it out of the raw ``attrs`` dict, and a ``True``
default would make this class demand an ``odoo.addons.*`` module path.

``__set_name__`` resolves ``model_name`` from ``owner._name``, which is why this
inherits :class:`_ModelMetadataMixin` rather than ``_ModelStubs``: the stub
declares ``_name`` only under ``TYPE_CHECKING``, so at runtime the class would
have no such attribute and field setup would raise. The value is ``None``, which
is exactly what it was when these lived on ``BaseModel`` (whose ``_name`` is also
``None``). The behaviour is unchanged; only the declaring class moved.
"""

from ..metaclass import MetaModel
from ._metadata import _ModelMetadataMixin

# Imported from the field modules directly, not the odoo.fields facade: this is
# Layer 2 reaching down to Layer 1, which is the allowed direction.
from ...fields.misc import Id  # isort: skip
from ...fields.textual import Char  # isort: skip


class _MagicFieldsMixin(_ModelMetadataMixin, metaclass=MetaModel):
    """Holder for the implicit fields present on every model."""

    __slots__ = ()

    _register = False

    id = Id()
    display_name = Char(
        string="Display Name",
        compute="_compute_display_name",
        search="_search_display_name",
    )
