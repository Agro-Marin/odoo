# ADR-0049: A field hook is named for the field it serves, and the count says how far that is true

- **Status:** Accepted
- **Date:** 2026-08-19

## Context

`doc/coding_guidelines.rst` §2.4 fixes the *prefix* of a compute, search,
inverse or default method and stops there. What follows the prefix is not a
matter of taste: `compute="_compute_x"` names the method from inside the field
declaration, so the field's name and the method's name sit inches apart in the
same call and can disagree without anything noticing.

The loss is specific. A reader asking what writes `reconciled` greps for it and
finds a field declaration pointing at `_compute_amount_residual`, a name that
mentions a different field. Nothing is broken, and nothing can be found.

The tree had already decided most of this. Measured over the model classes of
this repository, 2026-08-19:

| attribute | hooks serving one field | already `_<attr>_<field>` |
|---|---|---|
| `compute=` | 2,280 | 2,077 |
| `search=` | 222 | 194 |
| `inverse=` | 220 | 159 |
| `default=` | 171 | 79 |

So the rule is not an invention. It is what four fifths of the tree does, with a
nameable backlog.

A second shape turned up while measuring the first, and it is the more damaging.
346 hooks legitimately serve several fields — `_compute_amounts` sets thirteen —
and **145 of them are named after exactly one field they write**.
`_compute_amount_residual` also writes `amount_residual_currency` and
`reconciled`. That name is not untidy, it is false: it advertises one field and
sets three, and the reader who trusts it stops looking.

### §2.4 contradicted itself about inverse targets

The prefix table says an inverse target is `_inverse_`. The Mutation row said
`_set_*` is *reserved* for `inverse=` targets, and the provisional
`_set_`/`_update_` rule restated it. So a method wired as `inverse=` was required
to be `_inverse_x` and permitted to be `_set_x` — the defect §2.4 had already
fixed once for `_check_`/`_validate_`.

The tree settles it, measured 2026-08-19: 202 inverse targets are spelled
`_inverse_`, 37 are spelled `_set_`.

## Decision

**Count the hooks whose name does not point at their field, and ratchet the
count. Do not block on them.** Two shapes:

- a hook serving one field and not named `_<attr>_<field>`;
- a hook serving several fields but named for exactly one of them.

**The `_set_` carve-out is withdrawn.** An `inverse=` target is
`_inverse_<field>`. The general `_set_` versus `_update_` boundary stays
provisional and out of every count — it is about methods wired to nothing, a
genuinely fuzzy question. Only the inverse carve-out, which contradicted a table
three hundred lines above it, is removed.

The shape ADR-0033 chose for the verb vocabulary, and for the same arithmetic:
515 findings on day one would fail every build and the gate would be off within a
week.

### Why this one is counted where the `_get_`/`_prepare_` split is not

ADR-0033 excludes rules that cannot be decided from a name. This rule *is*
decidable, and not marginally: the field name and the method name are both in the
same `fields.X(...)` call. No question about a caller, no judgement about what a
return value feeds. A count nobody can lower by reading the rule is a count
people learn to ignore; this one can be lowered by reading the declaration.

The multi-field clause needs the whole tree rather than one file, because whether
`_compute_amounts` may keep its name depends on how many fields point at it.
That is why the gate lives in `tooling/architecture/` beside
`naming_vocabulary.py` and not in `test_lint`, whose Python checkers are per-file
by construction.

## Alternatives considered

**State the rule and leave it to review.** The state this replaces. The rule was
not stated at all — §2.4 gave the prefix and stopped — and the result is 515
hooks that disagree with their field, none of which any gate saw.

**Block on it.** Rejected on ADR-0033's arithmetic, with a sharper edge: 145 of
the findings are multi-field hooks whose fix is a rename plus a judgement about
what the group is called.

**Count only the single-field shape.** Simpler, and it drops the more damaging
half. A name that promises one field and writes three misleads in a way an
off-pattern name does not.

**Require `_<attr>_<field>` for multi-field hooks too, picking the first
field.** Incoherent: the name would be true of one field and false of the rest,
which is the defect, not the fix.

**Keep the `_set_` carve-out and exempt those 35.** It preserves two legal
spellings for one role — the ambiguity §2.4 exists to remove — and the tree
already voted 159 to 35 against it.

## Consequences

- The backlog is a number that can only fall, and each rename is permanent.
- `_set_*` wired as an `inverse=` target is now counted, so 37 findings arrive
  with this record. They are real: the table always said `_inverse_`.
- **`_set_*` is not abolished generally.** Adding it to §2.4's abolished list
  would move the naming ratchet by roughly 191 in one step for a question this
  record does not settle. The two counts stay separate.
- A `default=` that is a literal, a constant, or a lambda doing its own work
  names no method and is outside the rule. **Corrected by the first
  measurement**: a lambda was read as naming whatever attribute it called, so
  `default=lambda self: ",".join(...)` reported `join` as a field's default
  method; only a forward to `self.<method>()` counts now. And a `default=` may
  point at a shared utility — `get_base_url` has hundreds of callers and is one
  field's default — so the rule reaches a default only when the method exists for
  that field. Neither correction applies to `compute`/`search`/`inverse`, which
  name a hook by construction.
- The gate covers this repository only, like every other §2.4 count.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0049"`, run by
`.github/workflows/architecture.yml` against a floor in
`tooling/ratchet/baselines/`:

| gate | ratchets |
|---|---|
| `tooling/architecture/field_hook_naming.py` | field hooks whose name does not point at the field they serve |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`, and
`test_every_gate_refuses_an_empty_tree.py` probes it. Run the gate for the live
count.

## Amendments

### 2026-08-20 — when the canonical name looks worse, the field is the suspect

Draining this gate turned up six findings where applying the rule literally would
have made the tree worse. In every one the hook was honestly named and the FIELD
was the defect, so the repair was to rename the field — which then made the hook
correct without touching it. Two kinds.

*The field name states its mechanism.* The field once spelled
`search_date_category` on `stock.picking`, `mrp.production` and `repair.order`,
the one spelled `search_account_id` on `account.move.line`, and the one spelled
`fiscal_year_search` on `account.analytic.line` all said "this field exists to be
searched", which the declaration already says two lines down in `store=False` and
`search=`. The canonical hooks would have been `_search_search_date_category` and
`_search_search_account_id`. The stutter is the symptom; the name carrying the
mechanism is the defect.

*The field name is simply wrong.* On `hr.leave.type`, the field once spelled
`elligible_for_accrual_rate` was a typo — its own label read "Eligible for
Accrual Rate" and its compute was already spelled correctly, so the canonical
repair was to propagate the typo INTO the method. On `pos.make.invoice`, a field
spelled `count` carried no information on a model with one thing to count, while
its label read "Order Count".

**The hardest signal is a canonical name already taken on the same model.**
`product.pricelist.item` computes a `Char` field called `price` through
`_compute_price_label`, and the canonical `_compute_price` already exists there —
it is the pricing engine, `_compute_price(product, quantity, uom, date, ...)`.
When the name the rule asks for is occupied by a real method on that model, the
rule is pointing at the wrong half of the pair.

None of this weakens the rule. A hook and its field must agree; what these six
show is that the gate reports the DISAGREEMENT and cannot say which side is
wrong, so a finding is a question and not yet an instruction. Teaching it to
guess which side to blame would trade a decidable check for an unfalsifiable one.
