# ADR-0058: A call resolves to something this checkout defines

- **Status:** Accepted
- **Date:** 2026-08-21

## Context

Five defects landed in one day, all the same shape and none visible to any gate
this fork runs:

- **`_message_log`.** `20d1a0995c6` moved tracking onto `_message_log_batch`.
  `account.tax`'s override of `_message_log` stopped being reached, taking four
  tests and 141 lines of rendering with it, while the raw snapshot it existed to
  strip leaked into the chatter.
- **`_prepare_access_error`.** `b7e04d61ef8` renamed a call and not its
  definition. Every forbidden-access path on `mail.message` raised instead of
  reporting — 30 errors across 18 tests.
- **`_get_or_create_member_for_self`, `_get_fields_store_linked_messages`,
  `_get_fields_store_partner_name`.** Three calls in `mail` to methods nothing
  defined. Fixing them turned 47 distinct failing entries green across 18 test
  classes, because all three sat on shared store and access paths.
- **`_get_relation_chain`.** Split into a chain and a separate label; two callers
  kept unpacking two values. On create of any `ir.actions.server` with mail
  installed, `ValueError: not enough values to unpack`.

Every one of these files scores clean on `ruff`, `C901` and `naming_vocabulary`.
Not a gap in those gates: they check how code is **written**, and each of these
defects is about whether a name still **resolves**.

The failure mode is specific to a fork that refactors as a matter of policy (§3).
A rename, a hoist, a batch-ification or an API split moves a definition; a call
somewhere else keeps the old spelling; and Python says nothing until the line
runs. Two of the five were latent for days on paths no suite exercised, and
`_get_relation_chain` was worse than a plain break, because a chain of exactly
two fields unpacks *successfully* and feeds a `Field` object to something
expecting a string.

The question is cheap to ask. One AST pass over the checkout collects every
`def`/`class` name and every `x._name(...)` call, and reports the calls with no
definition. Over `odoo/` and `addons/` it costs seconds and finds 25 call sites.

## Decision

`tooling/architecture/py_unresolved_calls.py` reports every `x._name(...)` whose
`_name` this checkout defines nowhere, and `architecture.yml` ratchets the count.

A name counts as defined by a `def` or `class` anywhere in scope, by an attribute
assignment (`obj._name = ...`, which is how a slot or a patched-in callable is
bound), or by appearing as a string literal (`__slots__`, `getattr`). Those three
separate a vanished method from a live one reached indirectly, and without all
three the report is noise: `access_scan.py` binds `_rescan` through `__slots__`
and a lambda, and would be flagged forever.

Dunders are out of scope, as is a small named `EXTERNAL` set for attributes
reached on an object whose class this scan cannot see — a stdlib or third-party
base, or a namedtuple. `self._formatMessage` is `unittest.TestCase`'s and
`self._add_object` is pypdf's. An entry there is a claim about the receiver and
is checked at the call site before it is added, because "I could not find it" is
the finding, not the excuse.

The floor is the count, not zero. Twenty-five call sites stand today, several
latent on paths no suite runs; they are debt to drive down. What the ratchet buys
immediately is that the next rename cannot add one.

## Alternatives considered

**Resolve properly, through the MRO.** Walk each model's `_inherit` chain and
check the method exists on the composed class — what Odoo does at runtime, and it
would drop false positives to nothing. It needs a built registry, which means a
database, which puts the check in an integration lane rather than a seconds-long
static one. The static version already found five real defects; the precise
version would have found the same five, later and more expensively.

**Restrict to `self._name(...)`.** Higher precision, since the receiver's class
is usually in the same file. It would have missed
`channel._get_or_create_member_for_self` and `certificate._get_pem_cer`, exactly
the cross-model calls a rename is most likely to strand.

**Leave it to review.** Five instances in one day, three by the same rename
commit, one surviving 601 files of review. A stale call reads exactly like a live
one.

**A lint rule instead of a gate.** `ruff` has no cross-file symbol table, and the
whole point is that the definition and the call are in different files. `mypy`
could in principle, but the fork measures it over six packages with
`ignore_missing_imports` (§9.3) and Odoo's dynamic model surface defeats it on
the models where this matters.

## Consequences

A rename that lands the definition and forgets a caller fails the build instead
of waiting for the path to run. The cost is one AST pass in `architecture.yml`.

The `EXTERNAL` set is the maintenance burden, deliberately small and justified
per entry so it stays reviewable. It grows when a new third-party base class is
subclassed; each addition should name the library in its comment.

Cross-repo calls are not covered. CI checks out `odoo` alone, so a call in
`addons/` to a method defined only in `enterprise` or `agromarin` reports here as
unresolved — correct, since a bundled addon may not depend on either. The
reverse, a call in `agromarin` to a vanished `odoo` method, is invisible to this
lane; four such calls stand in `agromarin` today. Closing that follows §9.4's
pattern — a cross-repo workflow in the sibling that checks out the fork beside
itself — and is not done here.

## Enforcement

```
python tooling/architecture/py_unresolved_calls.py --count \
    | xargs python tooling/ratchet/ratchet.py unresolved_calls --count
```

`architecture.yml`, `exact` mode, so a fix must lower the floor in the same PR.
