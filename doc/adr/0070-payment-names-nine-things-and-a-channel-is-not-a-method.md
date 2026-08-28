# ADR-0070: "Payment" names nine things, and a channel is not a method

- **Status:** Accepted
- **Date:** 2026-08-26

## Context

Forty models in this workspace carry `payment` in their `_name`. They do not name
one concept. They name nine, and five of the nine are called "payment method".

| Concept | Model today |
|---|---|
| **Settlement** — money moved, or instructed to move | `account.payment` |
| **Provider transaction** — an authorisation or capture against a PSP | `payment.transaction` |
| **Method** — a capability: a code and a direction | `account.payment.method` |
| **Channel** — a journal offering a method, booking to an outstanding account | `account.payment.channel` (see Amendments) |
| **Provider method** — what the customer picks on the payment form | `payment.method` |
| **Till method** — how a POS session takes money | `pos.payment.method` |
| **Fiscal code** — a tax authority's catalogue entry | `l10n_mx_edi.payment.method` |
| **Due schedule** — when an invoice falls due; not a payment at all | `account.payment.term` |
| **Register wizard** | `account.payment.register` |

Provider method, till method and fiscal code are disambiguated by their prefix
and by the module a reader has already chosen to open. **Method and channel are
not.** They share the prefix `account.payment.method`, they are edited on the
same journal form, and — measured 2026-08-26 over both addon roots of this
repository and the enterprise and agromarin checkouts beside it — they are the
**only two of the forty** whose `_description` strings are identical: both
shipped `"Payment Methods"`. The UI could not tell them apart either.

The distinction the two models actually draw:

> A **method** is a capability. A **channel** is that capability wired to a
> journal and an outstanding account. A payment is made through a channel, never
> through a method: on `account.payment`, `payment_method_line_id` is required
> and `payment_method_id` is a `related` read off it.

The word cost three wrong readings on 2026-08-26 alone:

1. **`account_payment` was opened expecting to find `account.payment`.** The
   module defines no such model — it is the bridge between accounting and the
   provider engine, and its only new model is `payment.refund.wizard`. The model
   lives in `account`.
2. **`account.payment` was proposed for dissolution into `account.move`**, on the
   reading that a payment is a journal entry wearing a second name. It was
   `_inherits`-delegated to `account.move` until upstream `01b87f1230b` made the
   journal entry optional. Refuting it needed a measurement, not an argument: of
   its 45 own fields exactly **one** is `related` to `move_id`, and in this
   deployment — `accountant` installed, no outstanding account on the channel —
   the ordinary payment carries **no journal entry at all**.
3. **`.line` was read as a document line.** It is a configuration record, called
   a line only because it sits in a One2many on `account.journal`. Everywhere
   else in this tree `.line` means a line of a document.

`account.payment.term` is the fourth reading and the one that must not be
"fixed": it is a due schedule, but "payment terms" is the industry's name for a
due schedule.

## Decision

**The nine categories are named, and the names are used in prose, docstrings,
`_description` strings, records and commit messages.** The load-bearing pair is
**method** against **channel**.

**A model whose `_name` contains `payment` states which category it is**, and no
two of them share a `_description`. Enforced over model names — the level that
propagates, on ADR-0048's reasoning: a model's vocabulary is inherited by its
fields and its views, and a model name is the identifier another repository
writes down.

`l10n_*` models are exempt; their names are ecosystem identifiers.

Two renames follow from the vocabulary and are scheduled, not immediate:
the model then spelled account.payment.method.line takes the name
account.payment.channel, and the module `account_payment` takes the name
account_payment_provider — both spelled here in plain prose because neither
exists yet, and a record does not name code the tree does not carry. The
`_description` strings move first and alone, because they are the half of the
ambiguity that reaches a user and they cost one line each.

## Alternatives considered

**Dissolve `account.payment`.** Into `account.move`: refuted by measurement —
most payments here have no move, so there is no entry to dissolve into, and the
merge would reintroduce the outstanding-account entries upstream deliberately
removed and need move states for `in_process` and `rejected`. Into
`payment.transaction`: refuted by layering — `payment` depends on `onboarding`
and `portal` and must install without `account`, and most payments never touch a
provider. This is the record's main job: the proposal is reasonable on its face
and will be made again.

**Merge `account.payment.method` into the channel.** The method is the catalogue
shared across journals; the channel is the per-journal binding.
`_get_payment_method_information` keys on the method's `code`, and every provider
code is mirrored into the catalogue by `account_payment`. Merging puts one row
per journal per capability into a table that exists to hold one row per
capability.

**Rename `account.payment.term`.** Rejected on ADR-0048's test and for its
reason: the name is wrong by *category*, not by *subject*, and a reader who knows
the nine categories is not misled by it. Measured: 1628 occurrences over 123
files, plus `payment_term_id` across `sale`, `purchase` and every localisation.

**Gate field names as well as model names.** `payment_method_line_id` alone is
407 occurrences over 143 files whose spelling is already consistent; they inherit
only their model's noun. ADR-0048 rejected the same widening for `l10n_mx_edi_*`
and the signal-to-noise argument transfers unchanged.

**Do nothing and rely on review.** ADR-0045 rejects this for duplication and
ADR-0048 for vocabulary; three wrong readings in one afternoon is the same
measurement that carried both.

## Consequences

`account.payment` keeps its name and its table, permanently. So does
`account.payment.term`. That is the point of recording this: neither argument
needs a fourth outing.

Three `_description` strings changed with this record:
`account.payment.method` to `"Payment Method"`, the channel's to
`"Payment Channel"` — naming the concept before the identifier moves, which is
the sequence — and `payment.method` to `"Provider Payment Method"`.

A new model named for a payment concept must pick a category or fail the build.

Vocabulary and worked examples live outside this repository, in the
`agromarin-knowledge` vault under `reference/dev`, as the payment vocabulary
page.

## Enforcement

`tooling/architecture/payment_vocabulary.py`, run by `architecture.yml`.
Default-deny over model names, on `tooling/typecheck/scope_gate.py`'s pattern: an
allowlist of the models carrying the word today, each annotated with its
category, and `l10n_*` exempt by rule. Anything new fails until someone adds it
deliberately. A second check requires the `_description` strings of the listed
models to be pairwise distinct — the collision above is mechanically detectable,
and it is the one that reached the UI.

The allowlist's vocabulary is the nine senses plus two annotations for the case
the nine do not cover: **domain qualifier**, where "payment" qualifies a
different head noun — a provider, a token, a QR code — and **test fixture**. An
entry naming no category fails the same build as an unlisted model; a category
is what the entry is for.

`--prune` drops an entry whose model is gone. There is no `--update`: a flag that
rewrites the list to whatever exists would let the next wrong name in silently.

## Amendments

### 2026-08-26 — the channel rename landed, and the citations follow it

The model spelled account.payment.method.line became `account.payment.channel`
on the day this record was accepted, with `account` at version 1.9 carrying the
model, table,
sequence, constraint, index and metadata rename, and `hr_expense`, `sale` and
`hr_expense_stripe` each renaming their own column. The three citations above
that named the old model are corrected to the new one, which is what this
amendment announces: the record's argument is unchanged, and only the names it
points at have moved.

The module rename recorded in *Decision* has not landed at the time of this
amendment. It is still spelled in prose there for the reason given.

### 2026-08-26 — the module rename landed, and the argument against it is recorded

The module then spelled account_payment is `account_payment_provider`, adopted
from the old `ir_module_module` row by a `pre_init_hook` on the
`credential/hooks.py` pattern. The citation in *Decision* is corrected with it.

**The case against was not in this record and belongs in it.** Odoo's
bridge-module convention is `<a>_<b>` — `pos_sale`, `sale_stock`,
`account_edi_ubl_cii` — so a bridge between `account` and `payment` is called
account_payment, and it was. The name was right by that convention and collided
only with a model that lives in a *different* module, which is the shape
ADR-0048 declines to rename for. `account_payment_provider` resolves the
collision at the cost of the convention: the module it bridges to is `payment`,
not `payment_provider`.

That trade was put to the fork's owner on 2026-08-26 with both readings and the
measured cost of each, and the rename was chosen. A future reader who thinks the
convention should have won is reading an argument that was made and lost, not one
that was missed.

Renaming a module is not free of its own vocabulary debt: `ir.config_parameter`
keys and `res.config.settings`' `module_<name>` fields carry the technical name,
so `account_payment.enable_portal_payment` became
`account_payment_provider.enable_portal_payment` and `module_account_payment`
became `module_account_payment_provider`, the first with a migration inside the
hook because the parameter is `noupdate="1"` and a data reload never rewrites it.
