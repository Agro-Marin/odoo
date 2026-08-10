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
* ``band.mixin`` -- a half-open numeric band ``[min_value, max_value)`` over a
  scale, with bounds validation, overlap rejection and ``_covers(value)``.

Bands
=====

A *scale* is a set of sibling bands that together classify a number: a
production-size bucket derived from hectares, a commercial profile derived from
a score percentage.

Bounds are **half-open** -- the lower bound belongs to the band, the upper
bound belongs to the *next* one -- and ``max_value = 0`` means unbounded, which
is how the top band is written.

That is not a stylistic choice. Inclusive-both-ends bounds cannot express a
contiguous scale: ``0-10`` and ``10-20`` are rejected as overlapping at the
shared point 10, so a configuration has to leave integer gaps, and every
fractional measurement landing in a gap classifies into *nothing*. Both
consumers of this mixin had that shape, and in one of them the band selects a
multiplier applied to revenue targets, so "nothing" was not cosmetic.

Consumers say which records are bands and which bands share a scale:

``_is_band()``
  Whether the bounds are meaningful on this record. True by default; an
  attribute value overrides it to "only when my attribute is numeric".

``_band_siblings()``
  The other active bands of the same scale. Defaults to every other record,
  which suits a model that *is* one scale; override to scope per attribute, per
  company.

Note the mixin's ``@api.constrains`` can only name the fields it declares. If
``_is_band`` or ``_band_siblings`` reads a field of the concrete model, that
model must re-trigger ``_check_band`` on it -- moving a value to another
attribute changes both which rules apply and which scale it must not overlap.

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

``_used_records()`` (on the attribute and value mixins)
  Which of ``self`` is already bound to a subject. The default answers "some
  attribute line references it". Override to narrow it -- ``product`` counts
  only lines of *active* templates, so an attribute whose sole trace is an
  archived product stays deletable.

``_usage_label()`` (on the attribute and value mixins)
  Names the subjects holding the record, used to qualify the guard messages
  ("... because it is used on: *Chair*"). Empty by default, which selects a
  shorter sentence.

In-use protection
=================

Deleting an attribute cascades its values away and takes every captured line
with them; archiving one hides it from the pickers while the lines holding it
stay live. Both are silent data loss, so the mixins refuse:

* ``attribute.mixin`` -- ``@api.ondelete`` and ``action_archive`` guards.
* ``attribute.value.mixin`` -- an ``@api.ondelete`` guard, and a ``write``
  guard refusing to re-home a value in use (the lines point at the value, not
  at the attribute/value pair, so moving it leaves every one of them stray --
  a violation ``_check_values`` cannot see, because the write lands on the
  value).

All of them resolve "in use" through ``_used_records()``, so a consumer tunes
the policy in one place. ``_in_use_message()`` returns the same sentence
without raising, for a UI that wants to grey out a button rather than fail the
click; ``product`` exposes it over RPC as ``check_is_used_on_products``.

The guards are inert until ``_attribute_line_model`` is set -- with no line
model there is nothing to be in use *by*.

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
