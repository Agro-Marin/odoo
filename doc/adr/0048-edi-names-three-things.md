# ADR-0048: "EDI" names three things, and only one of them is interchange

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

`account_edi`'s own manifest defines the word for this tree:

> EDI is the electronic interchange of business information using a standardized
> format. [...] the transmission of said documents to various parties involved in
> the exchange (**other company, governements**, etc.)

Trading partners and governments in one clause. That is the conflation, and it
has propagated into ~79 module names.

**Fiscal clearance.** A government mandates an XML shape, requires a signature,
and clears or receives the document before it is legally an invoice. The
counterparty is the state or a licensed agent. `l10n_mx_edi`'s two outbound
endpoints are named, in its own data file, *"Mexican PAC (CFDI stamping)"* and
*"SAT (CFDI status)"*. No trading partner appears anywhere in the module. ~71 of
the 79 are this.

**Partner interchange — true EDI.** Structured business documents exchanged
between two businesses. `agromarin/syngenta_edi` is *"Send sale and stock reports
to the Syngenta web service"*: sell-through and inventory reporting to a
supplier. `purchase_edi_ubl_bis3`, `sale_edi_ubl`, `account_peppol` likewise.

**Document import.** Reading a file someone sent you and making a record of it.
No exchange, no counterparty — a parser.
`addons/account/models/account_move_import.py` holds this; it was named
`account_move_edi.py` until 2026-08-18, and its docstring carried a disclaimer
that the file is unrelated to the `account_edi` addon. A comment apologising for
a name is a name that wants changing.

The word cost three wrong conclusions on 2026-08-18 alone:

1. A redundancy audit paired `account_edi` with `l10n_mx_edi` as "two EDI
   document abstractions" and needed a dependency-closure computation to
   establish they solve different problems — `l10n_mx_edi` has never depended on
   `account_edi`.
2. That same file was proposed for a move into `account_edi`. It is document
   import wearing a fiscal-clearance name. Measured blast radius: **15 modules**
   would need a new `account_edi` dependency, `purchase` among them.
3. `account_edi` reads as dead code in this deployment. It is *unused here* and
   load-bearing for eight other localizations.

## Decision

The three categories are named, and the names are used in prose, docstrings,
records and commit messages: **fiscal clearance**, **partner interchange**,
**document import**.

**A new module, model or field does not take `edi` in its name unless its
counterparty is another business.** Enforced for module names, the level that
propagates — a module's vocabulary is inherited by its models and fields, and a
module name is the identifier other repositories write down.

`l10n_*` modules are exempt; their names are Odoo ecosystem identifiers.

## Alternatives considered

**Rename `l10n_mx_edi` to `l10n_mx_cfdi`.** Measured: 12 dependent manifests, 45
Python imports, **3413 xmlid references**, plus `ir_module_module` and every
`ir_model_data` row. Rejected on three grounds. It is the largest single-change
surface in this workspace and a missed xmlid fails at *runtime*, often silently.
Every future upstream companion module (`_pos`, `_sale`, `_stock`,
`_website_sale` all exist today) would need renaming on arrival, permanently. And
the name is wrong by *category*, not by *subject*: a reader who knows the three
categories is not misled by it. The machinery exists — this fork has renamed
`base_credential_manager` to `credential` and absorbed `api_gateway` into
`api_transport` — so this is a judgement about value, not capability.

**Do nothing and rely on review.** ADR-0045 rejects this for duplication and the
argument transfers: the second wrong proposal is rarely in the same diff as the
first, and after it lands nothing points at the reasoning that refuted it. Three
wrong conclusions in one afternoon is the measurement.

**Gate model and field names too.** `l10n_mx_edi_*` alone is 194 distinct fields
and 8121 occurrences whose own names (`_cfdi_uuid`, `_payment_policy`) are
already accurate; they inherit only the module's prefix. The signal-to-noise does
not support it.

## Consequences

`l10n_mx_edi` keeps its name, permanently. That is the point of recording this:
the argument does not need a fourth outing.

Two renames follow and are done: `account_move_edi.py` became
`addons/account/models/account_move_import.py`, and `account.edi.document`'s
`_description` changed from *"Electronic Document for an account.move"* to what
it is — a queued transmission.

A module whose counterparty is a tax authority is named for the document or the
regime (`_cfdi`, `_fiscal`), not `_edi`.

## Enforcement

`tooling/architecture/edi_vocabulary.py`, run by `architecture.yml`.
Default-deny over module names, on the `tooling/typecheck/scope_gate.py` pattern:
an allowlist of the eight non-`l10n_` modules that carry the word today, each
annotated with its category, and `l10n_*` exempt by rule. Anything new fails
until someone adds it deliberately.

`--prune` drops an entry whose module is gone. There is no `--update`: a flag
that rewrites the list to whatever exists would let the next wrong name in
silently.

Vocabulary and worked examples live outside this repository, in the
`agromarin-knowledge` vault under `reference/dev`, as the EDI vocabulary page.
