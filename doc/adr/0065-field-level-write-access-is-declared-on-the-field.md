# ADR-0065: Field-level write access is declared on the field

- **Status:** Accepted
- **Date:** 2026-08-25

## Context

`Field.groups` is the only field-level access declaration the ORM has, and it is
all-or-nothing in two directions at once: a user outside the spec can neither
read the field nor write it, and `fields_get` omits it entirely, so the field
disappears from every view. There is no way to say *everyone reads this, only
these groups change it* — the shape almost every "managed" field actually wants:
a cost, a price, a category, a flag that decides which application a record
appears in.

`AccessMixin._has_field_access(field, operation)` already took an `operation`
argument and ignored it, because `field.groups` answered both. That parameter
was the shape of the missing declaration, with nothing behind it.

Absent a mechanism, both this fork and upstream converged on the same
workaround, independently, in at least five places: a non-stored `Boolean`
computed from `has_group`, pulled into the arch as `<field ... invisible="1"/>`
purely so a sibling node can say `readonly="not that_flag"`.

- `is_template_editor` in `addons/mail/models/mail_template.py`
- `user_has_group_validate_bank_account` in
  `addons/account/models/res_partner_bank.py`
- `has_edit_delete_access` in `addons/hr_gamification/models/gamification.py`
- `can_publish` in `addons/website/models/website_page.py`
- a group-flags mixin in the AgroMarin addons, 15 such fields across two models

Three properties make that idiom worth replacing rather than tidying:

1. **It enforces nothing.** `readonly=` in an arch is a rendering hint. The
   group it names is bypassed by `web_save`, by import, by a server action, by
   any RPC client. A field that looks access-controlled in the form is writable
   by anyone the model's `ir.model.access` row admits.
2. **It costs a field per group per model.** Each one is transported in every
   `web_read` and `web_search_read` payload, identical on every record.
3. **The declaration is split three ways** — the field, the group→field mapping,
   and the `readonly` expression on each node it guards — with no gate binding
   them. The badge-user case shows the failure mode: its compute reads
   `self.env.user` and declares no `depends_context`, so one user's answer is
   cached for the transaction and handed to the next reader.

## Decision

`Field` gains a second access declaration, `write_groups`, checked only for
`operation == "write"` and only after `groups` has admitted the user:

```python
standard_price = fields.Float(write_groups="marin.group_product_cost_manager")
```

It accepts either a group spec — the same `has_groups` grammar as `groups`,
including `,` for OR and `!` for negation, and `fields.NO_ACCESS` — or a
**callable** taking the recordset being written and returning a bool:

```python
write_groups=lambda records: not records.ids or records.env.user.has_group(...)
```

The callable exists because the string form cannot express a gate that varies
with the records. `create()` empties `self` before checking
(`odoo/orm/models/mixins/create.py`), and `write()` returns early when `self` is
empty, so `not records.ids` distinguishes creation from modification exactly.
That is the shape behind every `readonly="id and not <flag>"` in the tree.

No new mixin, and nothing to inherit. The declaration sits on the field, the
check sits in `AccessMixin`, and every model has it.

## Alternatives considered

**Keep the computed-boolean idiom and give it a shared mixin.** This was built
first, as `mixin.user.group.flags` in `agromarin/marin`. It fixes the
`depends_context` bug and the mapping duplication, and fixes neither of the
other two: still unenforced, still a field per group on the wire. A mixin makes
a workaround uniform; it does not make it an access control.

**Resolve group predicates in the arch, in `_postprocess_access_rights`.**
`ir_ui_view.py` already strips `groups=` nodes per user, after the
group-agnostic arch cache, so a `readonly_groups` attribute could be resolved in
the same pass for no extra query. It would produce a correct *view* and still no
enforcement, and it would put the declaration in the arch — once per node that
mentions the field, rather than once per field.

**Widen `Field.groups` with a write-only spelling** (`groups="…:write"`).
`groups` is not only an access check: `ir_ui_view._narrow_model_groups` folds it
into the static group key that decides which nodes are stripped from a cached
arch. A spec that varies by operation cannot participate in that intersection,
and a callable certainly cannot. Keeping the two attributes separate keeps
`groups` statically analysable.

**A model-level policy hook** (`_get_write_gated_fields()`). Moves the
declaration away from the field it governs and puts every model's policy in one
method, which is the mapping-duplication problem again with a different shape.

## Consequences

- `fields_get` already reports `readonly = readonly or not
  _has_field_access(field, "write")`, and `field_arch.js` already falls back to
  `fields[name].readonly` when the node carries no `readonly` attribute. A gated
  field therefore renders readonly in every view — form, list, kanban, embedded
  x2many — with no arch change. **A node that sets `readonly` explicitly
  overrides the server's verdict rather than combining with it**; converting a
  field means deleting the arch attribute, not leaving it.
- `write()` and `create()` raise `AccessError` naming the field. Code that
  legitimately writes a gated field on the user's behalf must `sudo()`, and
  which sites those are is a question each gate has to answer for itself.
- The verdict from `fields_get` is per model and per user, never per record. A
  callable gate is enforced on write but cannot make the client render a field
  readonly for some records and not others; that stays an arch expression.
- `write_groups` propagates along `related` and `_inherits` fields through the
  existing `_related_<attr>` mechanism, so gating a delegating model's field
  gates its variants without a second declaration. A plain `related` field is
  `readonly` by default and has no inverse, so the inherited gate is inert
  there; a delegated `_inherits` field is writable and the gate bites.
- **It gates `create`, and `create` checks `default_*` context keys**, so the
  declaration is wrong for a field ordinary object creation must supply. Gating
  `product.template.list_price` in the AgroMarin addons broke 24 test classes in
  one run — every one of them `ProductCommon` creating a product with a price as
  a non-sales user — and gating `categ_id` breaks the Products button on
  `product.view_product_category_form`, which passes `default_categ_id`. Not
  checking context defaults was considered and rejected: it would leave
  `with_context(default_standard_price=999).create({})` as an open bypass.
  The declaration is for a value that is a *decision* reserved to a group.

## Enforcement

None. This is a facility models may use, not a rule they must follow, so no gate
counts its adoption. `odoo/addons/test_access_rights` pins the mechanism:
denial on write and on create, `sudo` bypass, `NO_ACCESS`, composition with
`groups`, the `fields_get` verdict, predicate arguments, and propagation to a
delegated field.

## Amendments

None.
