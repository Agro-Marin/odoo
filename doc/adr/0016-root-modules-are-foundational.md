# ADR-0016: The root modules are foundational

- **Status:** Accepted
- **Date:** 2026-08-09

## Context

`odoo/` holds a few modules at the package root rather than in any subpackage:
`exceptions.py`, `release.py`, `logutils.py`, `init.py`,
`_testing_bootstrap.py`, `__main__.py`.

Two are load-bearing everywhere. `exceptions.py` is the most imported module in
the core — 179 files across every package, including `odoo/db/`, which ADR-0003
otherwise holds ORM-agnostic. `release.py` is read by `init.py` before anything
else is importable, to enforce the Python floor.

Neither was constrained in the direction that matters. The subsystem map in
`doc/architecture/module.md` enumerates *packages*, so root modules appear in no
layer and no bracket. `core-does-not-depend-on-addons` names all three as
contract *sources*, which sounds like coverage and is not: that contract forbids
exactly one thing, `odoo.addons`. Nothing prevented `odoo/exceptions.py` from
importing `odoo.orm`, `odoo.http` or `odoo.service`.

An exception module that imports the ORM inverts the stack: every package that
raises would transitively depend on the model layer, and `db-is-orm-agnostic` —
which forbids `odoo.orm` in `db/` but says nothing about `odoo.exceptions` —
would go on reporting clean while the property it protects was gone.

Both modules import nothing from `odoo`. The invariant costs nothing to declare
and is only cheap while that remains true.

## Decision

`odoo/exceptions.py` and `odoo/release.py` may import nothing from `odoo.*`
except `odoo.libs`, itself dependency-free (ADR-0004).

**`odoo/logutils.py` is deliberately excluded.** It imports `odoo.db`,
`odoo.release` and `odoo.tools` at module level and reaches `odoo.modules`
through deferred imports. It is a *consumer* of the stack — the logging
configuration of a running server — not a foundation of it. Location in the tree
is not the criterion; direction of dependency is.

`init.py`, `_testing_bootstrap.py` and `__main__.py` are out of scope: the first
two are bootstrap, which runs before layering exists, and the third is three
lines calling the CLI.

## Consequences

- The de-facto foundation under every layer is declared and enforced rather than
  merely true.
- A future need for `exceptions.py` to know a higher layer must be argued, not
  discovered. The likely shape — attaching behaviour to an exception — is better
  served by the existing `http_status` pattern: a data attribute subclasses
  override, needing no import.
- Cost: one more contract, and a rule silent about the root module most likely
  to grow dependencies (`logutils.py`). Recorded so it is not read as oversight.

## Alternatives considered

**Include `logutils.py` and allow what it needs.** The contract would have to
permit `odoo.db`, `odoo.tools` and `odoo.modules` — three of the five things a
foundation must not import. It would assert almost nothing while appearing to
cover all three root modules, which is worse than not covering the third: the
next reader takes the name at face value.

**Move `exceptions.py` into a package**, under `odoo/libs/` or a new foundation
package, so an existing contract covers it. Rejected: `odoo.exceptions` is
public API with 179 importers across four repositories, and this is a rule about
direction, not location.

**Widen `libs-is-dependency-free` to cover the two modules.** Rejected: they are
not `libs`. `libs/` is a coherent area with its own façade rules
(`libs_facade_check.py`) and D/ANN enforcement, which neither module would
satisfy or benefit from. Sharing a predicate is not sharing an identity.

**Do nothing; both modules are clean.** The default the previous state chose.
The fork has rejected that argument twice already — for the `db/`↔`http/` tiers,
"documentation only until they were measured", and for the mixin graph, "called
a DAG on the strength of the `self`-only view". A property that is true and
unenforced stays true until someone has a reason.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`root-modules-are-foundational`. Run the checker for its live status.
