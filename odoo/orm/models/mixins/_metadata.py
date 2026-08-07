"""Model identity and schema metadata — the declarations, not the behaviour.

Nearly every unit of the composition reads these. Counted in the units
``mixin_coupling_check.py`` builds — 28 of them, this module plus 27 others —
``self._fields`` is read by 25, ``self._name`` by 25, ``self._table`` by 13 and
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
trees (``odoo/addons/`` and ``addons/``), ``self._name`` has 359 sites and
``self._fields`` 325 — a change in how they are *reached* would be a breaking
change to the most widely used surface in the framework, for no structural gain
the MRO does not already give. The sibling repos (``enterprise``,
``agromarin``, ``design-themes``) add several hundred more; they are left
uncounted on purpose, because a number this file cannot re-measure is a number
that rots. The scope above is exactly what
``test_architecture_doc.TestCountsRestatedElsewhere`` re-derives.

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
    """The registry instance, set as a class attribute during model setup.

    Same object as ``self.env.registry``. Convention: use ``self.pool`` for
    registry *metadata* (field_computed, field_inverses, ...) and
    ``self.env.registry`` / ``self.env[model_name]`` for model class lookups.
    """

    _fields__: dict[str, Field]
    _fields: MappingProxyType[str, Field]

    _auto: bool = False
    """Whether a database table should be created.
    If set to ``False``, override :meth:`~odoo.models.BaseModel.init`
    to create the database table.

    Defaults to ``True`` for :class:`Model` and :class:`TransientModel`, and
    ``False`` for :class:`AbstractModel`/:class:`BaseModel` (which have no
    table).

    .. tip:: To create a model without any table, inherit
            from :class:`~odoo.models.AbstractModel`.
    """
    _abstract: bool = True
    """ Whether the model is *abstract*.

    .. seealso:: :class:`AbstractModel`
    """
    _transient: bool = False
    """ Whether the model is *transient*.

    .. seealso:: :class:`TransientModel`
    """

    _name: str = None
    _description: str | None = None
    _module: str | None = None
    _custom: bool = False

    _inherit: str | list[str] | tuple[str, ...] = ()
    """Python-inherited models:

    :type: str or list(str) or tuple(str)

    .. note::

        * If :attr:`._name` is set, name(s) of parent models to inherit from
        * If :attr:`._name` is unset, name of a single model to extend in-place
    """
    _inherits: dict[str, str] = frozendict()
    """dictionary {'parent_model': 'm2o_field'} mapping the _name of the parent business
    objects to the names of the corresponding foreign key fields to use::

      _inherits = {
          'a.model': 'a_field_id',
          'b.model': 'b_field_id'
      }

    implements composition-based inheritance: the new model exposes all
    the fields of the inherited models but stores none of them:
    the values themselves remain stored on the linked record.

    .. warning::

      if multiple fields with the same name are defined in the
      :attr:`~odoo.models.Model._inherits`-ed models, the inherited field will
      correspond to the last one (in the inherits list order).
    """
    _table: str = ""
    _table_query: SQL | str | None = None
    _table_objects: dict[str, TableObject] = frozendict()
    _table_inheritance_root: str = ""
    """Name of the table this model's subtypes share through PostgreSQL table
    inheritance (``CREATE TABLE ... INHERITS``), when it is this model's own.

    A foreign key pointing at such a table is accepted by PostgreSQL but only
    ever sees the rows of the parent itself, so it rejects every id that lives
    in a child table: relational fields must not declare one, and their
    ``ondelete`` has to be applied in Python instead.  Subtypes inherit the
    attribute but own a different :attr:`_table`, which is what makes
    :meth:`_is_table_inheritance_root` false for them — they are ordinary
    tables and do get their foreign keys.
    """
    _inherit_children: OrderedSet[str]

    _rec_name: str | None = None
    """Field to use for labeling records. Default: ``name`` if the model has it.

    Set during model setup in ``registration.py``. The default stays ``name``
    (not ``''``): ``_compute_display_name`` relies on the implicit fallback.
    """
    _rec_names_search: list[str] | None = None
    _order: str = "id"
    _parent_name: str = "parent_id"
    _parent_store: bool = False
    """set to True to compute parent_path field.

    Alongside a :attr:`~.parent_path` field, sets up an indexed storage
    of the tree structure of records, to enable faster hierarchical queries
    on the records of the current model using the ``child_of`` and
    ``parent_of`` domain operators.
    """
    _active_name: str | None = None
    """field to use for active records, automatically set to either ``"active"``
    or ``"x_active"``.
    """
    _fold_name: str = "fold"

    _translate: bool = True
    """Whether to export translations for this model.

    Legacy attribute; some models (e.g. ir.model.constraint) set it to
    ``False`` to suppress translation export.
    """
    _check_company_auto: bool = False
    """On write and create, call ``_check_company`` to ensure companies
    consistency on the relational fields having ``check_company=True``
    as attribute.
    """

    _allow_sudo_commands: bool = True
    """Allow One2many and Many2many Commands targeting this model in an environment using `sudo()` or `with_user()`.
    By disabling this flag, security-sensitive models protect themselves
    against malicious manipulation of One2many or Many2many fields
    through an environment using `sudo` or a more privileged user.
    """

    _depends: frozendict[str, Iterable[str]] = frozendict()
    """dependencies of models backed up by SQL views
    ``{model_name: field_names}``, where ``field_names`` is an iterable.
    This is only used to determine the changes to flush to database before
    executing any search/read operations. It won't be used for cache
    invalidation or recomputing fields.
    """

    @property
    def _table_sql(self) -> SQL:
        """Return the :class:`SQL` object for the table identifier or table query."""
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
        """Whether this model owns the table its subtypes inherit from.

        See :attr:`_table_inheritance_root`.  Relational fields consult this to
        skip the foreign key PostgreSQL would let them create but never honour.
        """
        return bool(self._table) and self._table == self._table_inheritance_root
