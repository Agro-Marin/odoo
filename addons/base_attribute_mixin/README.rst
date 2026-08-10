================
Attribute Mixins
================

Reusable EAV (Entity-Attribute-Value) abstract mixins, meant to be inherited
by concrete attribute families defined in consuming modules.

Ships mixins only: no concrete models, no data, no views. The shape is derived
from ``product``'s attribute engine, which is the mature implementation in the
tree; ``product`` consumes these mixins rather than duplicating them.

Mixins
======

* ``attribute.mixin`` -- the attribute (dimension): ``name``, ``sequence``,
  ``active``, ``value_type`` and ``display_type``. Concrete models add their
  own ``value_ids`` One2many pointing at their value model.
* ``attribute.value.mixin`` -- a value: ``name``, ``sequence``, ``color``
  (defaulted across the palette by ``_get_default_color``), ``active``, and a
  ``display_name`` qualified with the attribute. Concrete models add
  ``attribute_id``.
* ``attribute.line.mixin`` -- one attribute plus its chosen values, bound to a
  subject record: ``sequence``, ``active``, ``value_count``, and the
  ``_check_values`` coherence constraint. Concrete models declare the parent
  Many2one, ``attribute_id``, ``value_ids`` and their own ``_rec_name``.

``value_type`` vs ``display_type``
==================================

They are orthogonal and both belong on the attribute:

* ``value_type`` (``single`` / ``multi``) is a **data rule** -- how many values
  one line may hold.
* ``display_type`` (``radio`` / ``pills`` / ``select`` / ``color`` / ``multi``
  / ``image``) only picks the **widget**. A ``single`` attribute may still
  render as radio, pills, select or colour swatches.

What ``single`` means depends on what a line *is* for the subject, and consumers
differ:

* Where a line is the **offer** -- a product template listing the values it
  sells -- the line legitimately holds many values and the choice of one is
  made downstream, per variant. ``product.attribute`` therefore defaults
  ``value_type`` to ``multi``.
* Where a line is the **selection** -- a surface or a partner recording what it
  actually is -- ``single`` means exactly one value on the line.

Hooks a consumer can set
========================

``attribute.mixin._attribute_line_model``
  Name of the concrete line model, e.g. ``"product.template.attribute.line"``.
  **Set this.** ``_check_values`` is an ``@api.constrains`` on the *line*, and
  the ORM has no cross-model constrains, so nothing re-runs it when the
  *attribute* changes. Without this hook, flipping ``value_type`` from
  ``multi`` to ``single`` left every existing multi-value line silently
  violating the rule the constraint exists to enforce.

``attribute.line.mixin._requires_value``
  Whether an active line must hold at least one value. ``True`` where the line
  is the offer (an empty one says nothing); ``False`` -- the default -- where a
  line is a slot awaiting capture.

``attribute.line.mixin._subject_label()``
  Human name of the record the line hangs off, used to qualify coherence
  errors ("... for *Chair*"). Empty by default; override where users need one
  record disambiguated from thousands.

``attribute.value.mixin._get_default_color()``
  Palette index for a new value. Defaults to a random 1-11 so values are
  visually distinguishable; ``0`` means "no colour" and is not drawn.

Name uniqueness
===============

Deliberately **not** declared by these mixins, and a consumer must not declare
it as a plain ``UNIQUE(name)`` / ``UNIQUE(attribute_id, name)`` constraint.

``name`` is ``translate=True``, so it is stored as a ``jsonb`` column and a
UNIQUE constraint compares whole translation *documents* rather than names. Two
records both called "Whitefly" are distinct rows the moment their translation
sets differ -- and they differ as soon as a second language is active, because
Odoo writes the active language alongside the source term on create. A user
working in Spanish creating "Mosca blanca" stores ``{"en_US": .., "es_MX": ..}``
where an English colleague stored ``{"en_US": ..}``, and the constraint sees no
duplicate.

The rule has to compare the *source term*, which means an expression, and
PostgreSQL does not allow expressions in a UNIQUE constraint. Consumers should
therefore declare a ``models.UniqueIndex`` over ``(name->>'en_US')``, scoped to
the parent where values are only unique within their attribute.

Gotcha: unstated field attributes are inherited
===============================================

Odoo merges field attributes across the MRO, so an attribute a consumer does
*not* restate is taken from the mixin. Redeclaring ``sequence`` to add an index
does not reset its ``default`` -- the mixin's ``10`` still applies. Restate any
attribute you need to differ.

Depends
=======

``base``.
