# ADR-0054: A domain builder leads with its object, not with a suffix

- **Status:** Accepted
- **Date:** 2026-08-20

## Context

ADR-0050 gave the domain family a shape: `domain=` became the fifth field
attribute of ADR-0049 with the hook `_domain_<field>`, `_domain` left
`PAYLOAD_SUFFIXES`, and a free-standing builder was required to *end* in
`_domain`. Two of those three still stand. The third does not, and the reason
arrived the next day.

§2.4 gained **the object leads its qualifier** on 2026-08-20: a name returning a
qualified thing puts the thing first and the qualifier after —
`_get_fields_readable`, not `_get_readable_fields`. The rule is general — its
companion paragraph says *the ordering is settled and unapplied, which is a
different state from unsettled* — and it is enforced against a list of head nouns
that already contains `domains`.

So the tree carries two mechanisms pointed in opposite directions at one family,
and only a plural keeps them from meeting. `domains` is in
`naming_vocabulary._COLLECTION_HEADS`, so `_get_gmap_domains` counts as
head-first backlog; `field_hook_naming.py` exempted a builder ending in
`_domain` — singular — and would have asked the same method for the opposite
shape had its returns been read as domains.

ADR-0050 rejected the prefix form, and its argument has to be answered: that
`_domain_*` for every builder would put 222 `_get_*_domain` methods in debt for a
prefix "which buys nothing a reader does not already get from the suffix".

That answers a claim head-first does not make. Head-first is not argued from
ambiguity — `_get_readable_fields` was not ambiguous either. It is argued from
there being **one** rule instead of two: English puts an attributive adjective in
front of its noun and a prepositional phrase behind it, so a suffix convention
makes `_get_partner_domain` and `_get_domain_for_invoice_lines` both correct and
the family has no single shape. ADR-0050 measured the cost and priced the benefit
at zero, because the benefit had not been stated yet.

The cost is also smaller than it looked, and the difference is what the gate can
see rather than what a grep can. Measured 2026-08-20 over the model layer of this
repository: **91** methods whose every return is a domain, of which **59** are
free-standing — the rest are `search=` / `domain=` hooks or `_search_*`, all
exempt. Of those 59, **1** is already head-first and **51** end in `_domain`. The
222 of ADR-0050 counted names; this counts contracts.

## Decision

**A free-standing domain builder is `_get_domain_<what>`.**

1. **The object leads.** `_get_domain_children`, not `_get_children_domain`;
   `_get_domain_modules_to_load`, not `_get_modules_to_load_domain`. The public
   form drops the underscore and keeps the order, per ADR-0053. A bare
   `_get_domain` is well formed — there is nothing left to qualify.
2. **`_get_` is the verb, and the family marker moves next to it.** ADR-0050
   declined `_get_*_domain` partly because `_get_`'s discriminator is "returns
   state that already exists; does not build it". §2.4 has since resolved that
   generally, under *the payload and read tests are not opposites*: provenance
   decides nothing a reader can check, and `_get_` is the section's neutral read
   verb everywhere else.
3. **The hook is untouched.** `domain=` and `search=` hooks keep
   `_domain_<field>` and `_search_<field>`. A hook prefix is not a qualifier, it
   is the binding, and §2.4's `ids` carve-out already says head-first yields
   where a field-hook rule owns the spelling.
4. **ADR-0050's other two decisions are carried forward unchanged.**

## Alternatives considered

**Leave ADR-0050 standing and carve domains out of head-first.** A carve-out
needs a reason the family is different, and there is none: a domain is a
qualified thing returned, exactly as a set of fields is. The only difference
found was chronological.

**Convert the 51 in this change.** Rejected on blast radius rather than
principle. They sit in some thirty addons, several with overrides in
`enterprise`, and §2.4's *adoption* rule is to apply the vocabulary to what you
rework rather than churn files you pass through. They are banked as measured
debt, which is what the ratchet is for.

**Require only the prefix and drop the suffix requirement quietly.** That is this
decision without a record, and the next reader would find `field_hook_naming.py`
contradicting an Accepted ADR with nothing to explain it.

## Consequences

- `field_hook_naming.py` exempts `_?get_domain(_<what>)?` where it exempted a
  `_domain` suffix. The count moves 235 -> 285: 51 tail-first builders become
  findings and one already-head-first name (`_get_domain_aal_with_no_move_line`)
  stops being one.
- The `fieldhooks` floor rises by that amount in the same change. Debt with a
  list, not a new steady state.
- `odoo/addons/base` is converted: `ir.actions.server._get_domain_children` and
  `ir.module.module._get_domain_modules_to_load`, with the `base_automation` and
  `base_import_module` overrides and the `odoo/modules/loading.py` call site.
- ADR-0050 becomes `Superseded by ADR-0054`. Its first and third decisions live
  on here; its file keeps the argument that produced them.
- `naming_vocabulary._COLLECTION_HEADS` still lists only the plural `domains`.
  Adding the singular would double-count the family against this gate.

## Enforcement

`tooling/architecture/field_hook_naming.py`, in
`.github/workflows/architecture.yml`, against the `fieldhooks` floor in
`tooling/ratchet/baselines/`. Run the gate for the live count.
