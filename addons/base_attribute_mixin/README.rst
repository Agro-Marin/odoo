================
Attribute Mixins
================

Reusable EAV (Entity-Attribute-Value) abstract mixins, meant to be inherited
by concrete attribute families defined in consuming modules.

Ships mixins only: no concrete models, no data, no views. The pattern mirrors
``product.template.attribute.line``, generalised so that subjects other than
product templates can carry an attribute set.

Mixins
======

* ``attribute.mixin`` -- the attribute (dimension): ``name``, ``sequence``,
  ``active``, ``value_type`` (``single`` / ``multi``; concrete models may
  extend it with ``selection_add``). Concrete models add their own
  ``value_ids`` One2many pointing at their value model.
* ``attribute.value.mixin`` -- a value: ``name``, ``sequence``, ``color``,
  ``active``. Concrete models add ``attribute_id``.
* ``attribute.line.mixin`` -- one attribute plus its chosen values, bound to a
  subject record. Provides the shared ``_check_values`` coherence constraint
  (values must belong to the attribute; a ``single`` attribute accepts one
  value); concrete models declare the parent Many2one, ``attribute_id`` and
  ``value_ids``.

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

Depends
=======

``base``.
