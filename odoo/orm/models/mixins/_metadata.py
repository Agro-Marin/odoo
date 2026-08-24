"""Model identity and schema metadata — the declarations, not the behaviour.

Nearly every unit of the composition reads these. Counted in the units
``mixin_coupling_check.py`` builds — 31 of them, this module plus 30 others —
``self._fields`` is read by 26, ``self._name`` by 26, ``self._table`` by 13 and
``self.pool`` by 9, then a long tail of ``_order`` / ``_rec_name`` /
``_inherits`` / ``_parent_name`` (2 to 4 each).
While they were declared in ``BaseModel``'s own class body, every mixin had a
``self``-call edge back into ``base.py``, and that single fan-in was what put
``base.py`` inside a **nine-unit cycle** with ``access``, ``create``, ``env``,
``iteration``, ``read``, ``recompute``, ``search`` and ``traversal``. Removing
it collapsed that cycle to two, which is the measurement that motivated this
module; giving query construction its own leaf (``_query.py``) then removed the
last one visible through ``self``. Counting calls made through *another
recordset of the same model* later exposed one more (``base.py`` <-> ``create``,
via ``_validate_fields``), which moving the constraint machinery to
``_constraints.py`` removed. The graph is now a DAG in both views
(``tooling/architecture/mixin_coupling_check.py``).

The cause was that ``BaseModel`` held two responsibilities: it is the
**composition root** that assembles the mixins, and it was also the
**metadata holder** they all read through. This module takes the second one, so
``base.py`` keeps only field/method discovery and coordination.

**Nothing about the public surface changes.** These stay ordinary class
attributes reached as ``self._name`` / ``self._fields``; only the class that
*declares* them moves, and attribute lookup crosses that hop through the MRO for
free. That matters: counting ``self.``-qualified reads in this repo's two addon
trees (``odoo/addons/`` and ``addons/``), ``self._name`` has about 400 sites
and ``self._fields`` about 360 — a change in how they are *reached* would be a
breaking change to the most widely used surface in the framework, for no
structural gain the MRO does not already give. The sibling repos
(``enterprise``, ``agromarin``, ``design-themes``) add several hundred more;
they are left uncounted on purpose, because a number this file cannot
re-measure is a number that rots. The scope above is exactly what
``tooling/architecture/doc_restated_counts.py`` re-derives.

**Stated to the ten, not to the unit.** The claim being made is that this
surface is used in hundreds of places, and a rounded pair carries that claim
exactly as well as an exact one while staying refutable: the gate holds the
sentence to within 5% of the tree it describes, and rewrites the digits under
``--update`` once it drifts further. An exact pair would instead go red on any
unrelated commit that adds one ``self._name`` read to an addon, which is a gate
that reports on the calendar rather than on the claim.

Two declarations deliberately stay in ``BaseModel``:

* ``_register = False`` — :class:`~odoo.orm.models.metaclass.MetaModel` reads it
  out of the raw class-body ``attrs`` dict, not off the class, so inheriting it
  is not enough: ``attrs.get("_register", True)`` would come back ``True`` and
  ``BaseModel`` would try to register itself as an addon model and raise
  ``ImportError: Invalid import of odoo.orm.models.base.BaseModel``.
* ``id`` / ``display_name`` — those are :class:`~odoo.fields.Field` instances,
  not metadata. ``Field.__set_name__`` binds to the declaring class, so moving
  them would re-owner the two magic fields.
"""

import typing

from odoo.tools import SQL, OrderedSet, frozendict

from ._model_stubs import _ModelStubs

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from types import MappingProxyType

    from ...fields.base import Field
    from ...runtime import Registry
    from ..table_objects import TableObject


class _ModelMetadataMixin(_ModelStubs):
    """The model-identity and schema attributes shared by every mixin."""

    __slots__ = ()

    pool: Registry

    _fields__: dict[str, Field]
    _fields: MappingProxyType[str, Field]

    _auto: bool = False
    _abstract: bool = True
    _transient: bool = False
    _is_registry_metadata: bool = False

    _name: str = None
    _description: str | None = None
    _module: str | None = None
    _custom: bool = False

    _inherit: str | list[str] | tuple[str, ...] = ()
    _inherits: dict[str, str] = frozendict()
    _table: str = ""
    _table_query: SQL | str | None = None
    _table_objects: dict[str, TableObject] = frozendict()
    _table_inheritance_root: str = ""
    _inherit_children: OrderedSet[str]

    _rec_name: str | None = None
    _rec_names_search: list[str] | None = None
    _order: str = "id"
    _parent_name: str = "parent_id"
    _parent_store: bool = False
    _active_name: str | None = None
    _fold_name: str = "fold"

    _translate: bool = True
    _check_company_auto: bool = False

    _allow_sudo_commands: bool = True

    _depends: frozendict[str, Iterable[str]] = frozendict()

    @property
    def _table_sql(self) -> SQL:
        table_query = self._table_query
        if table_query and isinstance(table_query, SQL):
            table_sql = SQL("(%s)", table_query)
        elif table_query:
            table_sql = SQL(f"({table_query})")
        else:
            table_sql = SQL.identifier(self._table)
        if not self._depends:
            return table_sql

        fields_to_flush: OrderedSet[Field] = OrderedSet()
        seen: set[str] = {self._name}
        models = [self]
        while models:
            current_model = models.pop()
            for model_name, field_names in current_model._depends.items():
                model = self.env[model_name]
                if model_name not in seen:
                    seen.add(model_name)
                    models.append(model)
                fields_to_flush.update(model._fields[fname] for fname in field_names)

        return SQL.EMPTY.join(
            [
                table_sql,
                *(SQL(to_flush=field) for field in fields_to_flush),
            ]
        )

    def _is_an_ordinary_table(self) -> bool:
        return self.pool.is_an_ordinary_table(self)

    def _is_table_inheritance_root(self) -> bool:
        return bool(self._table) and self._table == self._table_inheritance_root
