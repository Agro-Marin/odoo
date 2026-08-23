# ADR-0061: A merge re-points references always, and absorbs values by choice

- **Status:** Accepted
- **Date:** 2026-08-23

## Context

`mixin.merge` does three things to fold one record into another: it re-points
everything that referenced the sources, it copies the sources' own values onto
the destination, and it deletes the sources. Until now the second was not a
separable step, and it was not even in one place.

`_update_values_generic` copies the scalar fields, destination last, so the
destination keeps whatever it already had and the sources fill its blanks. That
is the right rule for the case the wizard was written for — two records of the
same customer, one holding the phone number and the other the VAT.

It is the wrong rule when the destination is a **bucket**: a catch-all contact
that dormant customers are swept into, which must come out the other side with
its own identity intact. `agromarin/marin` has exactly that flow, and expressed
it by overriding `_update_values` to return early when a context key was set.
That override was measured against the real registry and closed less than half
of the hole:

- **Company-dependent fields went on leaking**, because the jsonb copy that
  merges them lives at the end of `_update_reference_fields_generic` — a method
  named for re-pointing references, doing value absorption. Overriding the value
  phase cannot reach it. Measured on the deployed dependency set: `trust`
  `normal -> bad` and `property_payment_term_id` empty -> set, on a bucket whose
  plain fields the override had successfully protected.
- **Stored many2many went on leaking**, because `_get_excluded_merge_tables`
  builds its exclusion set from the *wizard's* own m2m relations rather than the
  merged model's, so `res_partner_res_partner_category_rel` is one of the 55
  relations the foreign-key pass re-points. The caller had noticed and was
  restoring `category_id` by hand afterwards.
- **Bank accounts went on leaking** twice over: `_merge_bank_accounts` moves
  them, and the foreign-key pass would move them anyway.

The hand-written restore is the tell. A caller that repairs the destination
field by field after the fact is compensating for a phase it could not turn off,
and it can only repair what it can see: the restore reads `category_id` through
that field's domain, so a source tag outside the domain is re-pointed onto the
bucket and then *cannot* be removed by the restore — it is invisible to the read
that computes the replacement set. Verified: the bucket ends up holding a tag
that no user interface will ever show it holding.

## Decision

The three things a merge does are three phases, and the middle one is a choice.

**Re-pointing is unconditional.** Foreign keys, reference fields, attachments,
followers, messages and `ir.model.data` always move to the destination. This is
what a merge is for, and no mode turns it off.

**Absorbing values is a mode**, declared on the wizard record as
`absorb_source_values` (default `True`) and read through
`mixin.merge._merge_absorbs_source_values()`. A concrete wizard that has no such
notion inherits the default and is unaffected. When the mode is off, the merge
skips the scalar copy, the company-dependent copy, the stored many2many
re-pointing, and — for partners — `res_partner_bank`.

**The company-dependent copy moves to the value phase it belongs to.** It is
extracted from `_update_reference_fields_generic` into
`_update_company_dependent_values_generic` and called from the top of
`_update_values_generic`, which preserves the order the two had before the split
— jsonb merge first, ORM write second — so the default path is unchanged.

A mode, not a context key: the wizard is a record, and a caller that wants a
different kind of merge says so in the values it creates it with. A context key
sets the mode in one place and reads it three call levels down in a method that
does not mention it.

The consequence to state plainly: with the mode off, a source's bank accounts
are **deleted** with the source rather than moved, because excluding a table
from re-pointing leaves its rows to the `ondelete='cascade'`. For sweeping
dormant records into a bucket that is the intent. For any other use of the mode
it is the thing to check first.

## Alternatives considered

**Keep the context key and widen what the override covers.** The reviewer's
first instinct, and it is what the tree already showed being tried: the
downstream override plus a hand-written `category_id` restore. Rejected because
the company-dependent copy is not reachable from the value phase at all, so no
amount of widening the override closes it — the split has to happen in core.
And a restore is bounded by what the reading user can see, which is how the
invisible tag survives.

**Add an `absorb_source_values=` parameter to `_merge`.** Rejected because the
value has to reach `_get_excluded_merge_tables`, three calls down through
`_update_foreign_keys_generic` and `_get_relations_to_repoint`, both `@api.model`
methods shared with `product.merge.wizard`. Threading a parameter through them changes
signatures for a wizard that does not have the notion. A field plus a policy
hook leaves those signatures alone.

**Give the partner wizard a `_get_fields_excluded_value()` hook and stop
there.** This is the shape `product.merge.wizard` already uses, and the hook is added
here — it is the right seam for "this particular field must not travel". It is
not enough on its own: excluding every field one by one is not a mode, it does
not reach the m2m relation tables or the bank accounts, and the list would have
to be recomputed whenever a module adds a field.

## Consequences

**A source's bank accounts are deleted, not moved, when the mode is off.**
Excluding `res_partner_bank` from re-pointing leaves its rows to
`ondelete='cascade'`, and the row is gone with the partner. For sweeping dormant
records into a bucket that is the point; for any other use of the mode it is the
first thing to check. It is pinned by
`test_not_absorbing_leaves_the_source_bank_account_behind`.

**Stored many2many stop travelling when the mode is off, and that includes
memberships.** `discuss.channel` reaches a partner through
`discuss_channel_member`, so a bucket no longer joins the channels its sources
were in. This is intended and it is a behaviour change for anyone who turns the
mode off expecting only scalars to stop.

**The default path is unchanged.** The company-dependent copy runs in the same
order relative to the ORM write as it did before the split, so a merge with the
mode left alone writes what it always wrote.
`TestMergePartnerCompanyDependent`, which predates this record, is what says so.

**A wizard that never heard of the mode is unaffected.** `product.merge.wizard`
inherits `_merge_absorbs_source_values()` returning `True` and behaves exactly as
before, including the company-dependent copy it used to receive from the
reference pass and now receives from the value phase.

## Enforcement

No new gate. What this record constrains is which phase a value copy belongs to,
which is a judgement about a method's name matching its work — not a code shape
a checker can recognise.

It is pinned by tests instead. `TestMergePartnerAbsorbSourceValues`, in
`odoo/addons/base/tests/test_res_partner_merge.py`,
asserts both directions on one fixture: with the mode on the destination absorbs
the source's `vat` and tags, with it off the destination keeps its own `vat`,
`street`, `barcode`, tags and bank accounts while the source's attachment is
still re-pointed. `TestMergePartnerCompanyDependent` pins the copy that moved.
In the consumer repository, marin's own
test_general_partner_merge pins the flow that needed the mode and fails on two
subtests without it — named in plain prose because CI checks this repository out
alone, so no path to it can resolve here.

The regression this record exists to prevent is a future contributor moving the
company-dependent copy back into `_update_reference_fields_generic` because that
is where the flush already is. The `barcode` assertion in
`test_not_absorbing_keeps_the_destination_identity` is what would catch it: that
column is only reachable through the phase that moved.
