# ADR-0050: A domain is its own family, and `domain=` is a field hook like the rest

- **Status:** Superseded by ADR-0054
- **Date:** 2026-08-19

## Context

§2.4 fixes one canonical verb per operation and ADR-0049 fixes what follows the
prefix of a field hook. Neither says anything about a method that returns a
domain, and §2.4 is worse than silent: `_domain` is listed among the *payload
suffixes*, so `naming_vocabulary.py` reads a domain builder as a payload and
steers it to `_prepare_*`.

Wrong on the guide's own terms. `_prepare_`'s discriminator is "the return value
feeds `create()` / `write()` / `Command`", and a domain feeds none of them — it
feeds `search()` and a field's `domain=`. The tree agrees: `_get_*_domain` is
spelled 222 times against 4 `_prepare_*_domain`.

Two populations sit under the word and want different things. Measured
2026-08-19:

- **129 free-standing domain builders**, of which **114 (88%)** already end in
  `_domain`. The convention exists; only the rule was missing.
- **26 methods named by a field's `domain=`**, of which 11 are already
  `_domain_<field>`. `domain=` is a field attribute that names a method exactly
  like `compute=`, `search=`, `inverse=` and `default=` —
  `mixin.order.line.fields` writes
  `domain=lambda self: self._domain_product_id()` — and ADR-0049 did not
  enumerate it.

## Decision

**A domain is its own family. It is neither a read nor a payload.**

1. **`domain=` is the fifth field attribute of ADR-0049**, and its hook is
   `_domain_<field>`. This extends that record's gate rather than replacing it.
2. **A method that returns a domain says so: its name ends in `_domain`.**
   Counted from the return statements, not from the name.
3. **`_domain` leaves the payload-suffix list.** An abolished verb on a
   domain-suffixed name is still abolished, but its target is the domain family:
   `_make_po_get_domain` is wrong because of `_make_`, and the fix is not
   `_prepare_`.

### The 222 are not a bill

Requiring only the *suffix* of a free-standing builder is deliberate. Making
`_domain_*` canonical for every domain-returning method would put 222
`_get_*_domain` methods in debt for a prefix, buying nothing a reader does not
already get from the suffix. The prefix is canonical where the method is a
*hook*, because there the field's name is the rest of it and ADR-0049's argument
applies unchanged.

## Alternatives considered

**Keep `_domain` a payload suffix.** Contradicts `_prepare_`'s stated
discriminator, and commits the fork to a spelling four methods use against 222.

**Make `_get_*_domain` canonical and be done.** The tree's majority, and
tempting. Rejected because `_get_`'s discriminator is "returns state that already
exists; does not build it", and a domain is built — the family would be borrowed
rather than owned, and the `domain=` hook would have no name of its own.

**One rule for both populations.** Rejected on cost: a free-standing builder and
a field hook ask different questions, and the answer that suits one is 222
renames for the other.

**Detect a domain by name rather than by return.** What the payload suffix did,
and how `tracking_fields` on `mixin.utm` — a list of three-string tuples with no
operator — would be read as a domain. The gate matches `(field, operator, value)`
instead.

## Consequences

- Two counted shapes join `field_hook_naming.py`: `domain=` hooks not named
  `_domain_<field>` (13) and domain-returning methods whose name does not end in
  `_domain` (8).
- `_search_*` is exempt from the second, by binding and by convention: a domain
  is a search hook's contract, and ADR-0049 already fixes what it is called.
- `default=` and `domain=` both take the dedication test, since either may point
  at a shared helper rather than a hook; the other three name a hook by
  construction.
- The naming ratchet does not move: the five domain-suffixed findings stay
  findings, and only the canonical they name changes.

## Enforcement

`tooling/architecture/field_hook_naming.py` (ADR-0049) gains the fifth attribute
and the second shape; `tooling/architecture/naming_vocabulary.py` (ADR-0033)
drops `_domain` from `PAYLOAD_SUFFIXES` and retargets domain-suffixed findings.
Both run in `.github/workflows/architecture.yml` against floors in
`tooling/ratchet/baselines/`. Run the gates for live counts.
