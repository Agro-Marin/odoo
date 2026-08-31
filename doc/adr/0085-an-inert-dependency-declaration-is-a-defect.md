# ADR-0085: An inert dependency declaration is a defect

- **Status:** Accepted
- **Date:** 2026-08-31

## Context

`@api.depends` is read off the method a field names as its `compute`. Put it on
any other method and Python accepts it, ruff accepts it, the registry builds,
every test passes — and the decorator does nothing at all. The field it was
meant for is left declaring no dependency, so the ORM never invalidates it and
it answers with whatever it computed first.

This is not hypothetical. `a55570962fa` split
`_compute_discount_allocation_needed` into a helper plus a compute and left the
decorator on the helper. Measured in the registry afterwards,
`field_depends[account.move.line.discount_allocation_needed]` was the empty
list, and so was `discount_allocation_dirty`'s. That killed the whole
discount-allocation branch of the dynamic-line sync — `_sync_dynamic_line`
clears the dirty flag in `prepare()` and returns early in `commit()` when
nothing is dirty, and with no dependency nothing ever re-marked it. An invoice
whose discount was edited kept booking the discount it was created with, in the
stored rows, through every write path including the web client's and the form's.

The failure is silent in every direction a reviewer normally looks. The
refactor was a pure extraction and read as one; the decorator moved with the
code that used the values; the suite stayed green because no test asserted that
a discount edit changes the discount line. Nothing about a method named
`_prepare_...` carrying `@api.depends` looks wrong on the page.

What makes it gateable is that the rule needs no model semantics: a
dependency list is meaningful only on a name some field wires. That is a
question about the source text, answerable without a database, and the answer
across `odoo/` plus `addons/` at the time of writing is a list of eight — of
which the first two examined are real defects of their own. `fleet.vehicle`
declares `vehicle_range = fields.Integer(string="Range")` with no `compute=`,
beside four sibling fields (`trailer_hook`, `power`, `co2_standard`,
`electric_assistance`) that all carry `compute=`, `store=True`,
`readonly=False`; its `_compute_vehicle_range` is wired to nothing and the value
is never loaded from `model_id`. `addons/mrp`'s own `_compute_display_assign_serial` overrides and calls
`super()._compute_display_assign_serial()`, but `display_assign_serial` and
`display_import_lot` were removed from `addons/stock` and now exist nowhere in
the workspace except that override — dead code that would raise if anything
reached it.

## Decision

A method carrying ``@api.depends`` or ``@api.depends_context`` whose name no field
in the scanned tree wires as `compute`, `inverse` or `search` is a gate
offender. `tooling/architecture/orphan_depends.py` measures it and
`architecture.yml` ratchets the count.

The check is deliberately the loosest reading that still catches the defect:
names are collected tree-wide rather than per model or per class. A per-model
reading has to answer what a mixin's method means on a model that inherits the
method but carries no such field, and it calls those orphans when they are not —
`mail.activity.mixin`'s `_compute_activity_user_id` is wired on the mixin and
inherited onto `ir.actions.server`, which declares no `activity_user_id` field.
Both spellings of the wiring count: the string `compute="_compute_x"` and the
bare reference `compute=_compute_x` that `res.lang`'s `flag_image_url` uses,
which a string-only reading misses.

The gate ships as a ratchet at its measured value rather than as a hard zero.
The eight standing offenders sit in seven modules — `fleet`, `mrp`,
`maintenance`, `hr`, `pos_sale`, `pos_self_order`,
`l10n_account_withholding_tax` — and each needs its own decision about what the
field was supposed to be, which is not the same work as installing the check.

## Alternatives considered

**A test asserting every computed field declares dependencies**, which is what
the `account.move.line` model now carries. Kept, and it is the sharper instrument where it
applies: it caught this defect from the other end, and its exemption list forces
each deliberately-undeclared compute to be named with a reason. Rejected as the
only measure because it is per model and per registry — its yield is
proportional to what a test database installs, and the account-only registry
used to develop this ADR reported **0** orphans while the source tree held eight.

**Read the registry instead of the source.** Rejected for the same reason,
plus the cost: a registry-based gate needs a database, an install and a module
set, and would report a different number for every lane that runs it.

**Refuse the decorator at import time**, in `api.depends` itself. Attractive —
it would make the defect unwritable rather than merely visible — but the
decorator cannot know at decoration time whether a field will later name the
method, since fields and methods are collected in class-body order and the
registry resolves them afterwards. A check at registry-build time is possible
and remains open; it would subsume this gate.

**Fix the eight and ship a hard zero.** Rejected as scope: two of the eight are
live defects in modules whose suites are a separate run, one is an
upstream-inherited shape rather than a fork regression, and bundling seven
modules' behaviour changes into the commit that installs a checker is how a
gate becomes the thing that broke the build.

## Consequences

The refactor that produced this defect is now a build failure rather than a
silent behaviour change, and the class is closed for the whole tree rather than
for the file that happened to be audited.

The ratchet starts at eight and can only fall. Each offender that is paid off is
a decision about a field — is it computed or is it stored data — which is worth
making explicitly and was previously invisible.

The tree-wide name collection means a method whose name coincides with a wired
name elsewhere is not flagged. That is the deliberate cost of avoiding the mixin
false positive, and it costs a detection only when the two names match exactly.

## Enforcement

`tooling/architecture/orphan_depends.py`, run by `architecture.yml` and ratcheted
as `orphandepends`. Two AST passes over `odoo/` and `addons/`: one collects every
name any field wires as `compute`, `inverse` or `search`, the other every method
carrying a dependency decorator. The difference is the offender list.

`--check` exits 1 on any offender, for a scope that has reached zero; `--count`
feeds the ratchet, which is how it runs today. It refuses an empty scan rather
than reporting 0 from one, and `test_every_gate_refuses_an_empty_tree.py` pins
that.

There is no `--update`. The floor moves through `ratchet.py` with a note, so
paying one off is a decision someone wrote down rather than a number that drifted.
