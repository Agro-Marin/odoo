# ADR-0016: The root modules are foundational

- **Status:** Accepted
- **Date:** 2026-08-09

## Context

`odoo/` holds a handful of modules that sit directly at the package root rather
than in any subpackage: `exceptions.py`, `release.py`, `logutils.py`,
`init.py`, `_testing_bootstrap.py`, `__main__.py`.

Two of them are load-bearing everywhere. `exceptions.py` is the single most
imported module in the core — 179 files across every package, including
`odoo/db/`, which is otherwise held ORM-agnostic by ADR-0003. `release.py` is
read by `init.py` before anything else is importable, to enforce the Python
floor.

Neither was constrained in the direction that matters. The subsystem map in
`doc/architecture/module.md` enumerates *packages*, so root modules appear in no
layer and no bracket. `core-does-not-depend-on-addons` names all three as
contract *sources*, which sounds like coverage and is not: that contract forbids
exactly one thing, `odoo.addons`. Nothing prevented `odoo/exceptions.py` from
importing `odoo.orm`, `odoo.http` or `odoo.service`.

That is not a theoretical hole. An exception module that imports the ORM
inverts the whole stack: every package that raises would transitively depend on
the model layer, and `db-is-orm-agnostic` — which forbids `odoo.orm` in `db/`
but says nothing about `odoo.exceptions` — would go on reporting clean while
the property it protects was gone.

Both modules import nothing from `odoo` today. The invariant costs nothing to
declare and is only cheap while that remains true.

## Decision

`odoo/exceptions.py` and `odoo/release.py` may import nothing from `odoo.*`
except `odoo.libs`, which is itself dependency-free (ADR-0004).

**`odoo/logutils.py` is deliberately excluded.** It imports `odoo.db`,
`odoo.release` and `odoo.tools` at module level and reaches `odoo.modules`
through deferred imports. It is a *consumer* of the stack — the logging
configuration of a running server — not a foundation of it, and grouping it
with the other two by virtue of its file location would either falsify the
contract or force it to be written so loosely as to assert nothing. Location in
the tree is not the criterion; direction of dependency is.

`init.py`, `_testing_bootstrap.py` and `__main__.py` are likewise out of scope:
the first two are bootstrap, which by definition runs before layering exists,
and the third is three lines that call the CLI.

## Consequences

- The de-facto foundation under every layer is now declared and enforced rather
  than merely true.
- A future need for `exceptions.py` to know about a higher layer must be
  argued, not discovered. The likely shape of such a request — attaching
  behaviour to an exception — is better served by the existing `http_status`
  pattern: a plain data attribute that subclasses override, requiring no
  import.
- The cost is one more contract to read, and a rule that says nothing about the
  root module most likely to grow dependencies (`logutils.py`). That asymmetry
  is recorded above so it is not mistaken for an oversight.

## Alternatives considered

**Include `logutils.py` and allow what it needs.** The contract would have to
permit `odoo.db`, `odoo.tools` and `odoo.modules` — three of the five things a
foundation must not import. It would assert almost nothing while appearing to
cover all three root modules, which is worse than not covering the third at
all: the next reader would take the name at face value.

**Move `exceptions.py` into a package** — under `odoo/libs/`, or a new
foundation package — so an existing contract covers it. Rejected because
`odoo.exceptions` is public API with 179 importers across four repositories,
and this is a rule about direction, not location. Relocation would be churn in
service of the checker's convenience.

**Widen `libs-is-dependency-free` to include the two modules.** Rejected
because they are not `libs`: `libs/` is a coherent area with its own façade
rules (`libs_facade_check.py`) and D/ANN enforcement, and neither module would
satisfy those or benefit from them. Sharing a *predicate* is not sharing an
*identity*.

**Do nothing, on the grounds that both modules are clean.** This is the option
the previous state chose by default. It is exactly the argument the fork has
already rejected twice — for the `db/`↔`http/` tiers, which were "documentation
only until they were measured", and for the mixin graph, "called a DAG on the
strength of the `self`-only view". A property that is true and unenforced is a
property that stays true until someone has a reason.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`root-modules-are-foundational`. For the contract's live status, run the
checker — this record does not restate it.
