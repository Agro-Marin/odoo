# ADR-0077: A hook the ORM calls takes no arguments

- **Status:** Accepted
- **Date:** 2026-08-29

## Context

`@api.depends`, `@api.depends_context`, `@api.constrains`, `@api.onchange` and
`@api.ondelete` mark a method the framework invokes on its own schedule. It binds
the method to a recordset and calls it with **nothing**: no arguments are
available to pass, and none are passed. A parameter beyond `self` on such a
method is therefore either a `TypeError` waiting for the hook to fire, or a
decorator sitting on a method that was never the hook.

The second is the common case and it is silent. Splitting a long compute by
replacing the source **from its `def` line** leaves the decorator attached to
whatever helper lands above it:

```python
@api.depends("invoice_payment_term_id", "invoice_date", ...)   # never moved
def _get_payment_term_base_amounts(self, invoice, sign):        # <- helper landed here
    ...
def _compute_payment_terms(self):                               # <- has no depends now
```

The compute stops re-running. Nothing raises. `ruff`, every architecture gate and
every lint gate stay green, because each is asking a different question. It
surfaces as wrong data at a distance — in the case that produced this record,
payment-term lines dated from the invoice date instead of the payment term, and
`date_maturity` two weeks out.

Measured on 2026-08-29 while bringing `addons/account` to zero on every gate: the
shape occurred **five times in one session** — `_compute_abnormal_warnings`,
`_compute_payment_state`, `_compute_payment_terms`,
`_compute_stat_buttons_from_reconciliation`, `_compute_new_values` — and cost 96
new test failures across two full suite runs before an AST diff against `HEAD`
found it. Three further methods lost `@api.model` the same way.

The tree says this is a contract rather than debt:

| Scope | Hooks taking parameters beyond `self` |
|---|---:|
| `odoo/odoo` | **0** |
| `odoo/addons` | **0** |
| `agromarin` | **0** |
| `design-themes` | **0** |
| `enterprise` | 2 |

## Decision

**Count methods carrying a no-argument ORM hook that declare a parameter beyond
`self`. Hold the core checkout at zero.**

`tooling/architecture/py_hook_arity.py`, floored per scope like every other
cross-repo gate: `exact` 0 for `odoo/` and `addons/`, one-sided for the siblings,
which cannot be fixed from this repository.

The check is a **tree invariant**, not a diff. A diff-time check — comparing a
method's decorator set against `HEAD` — finds the same bug and is worth running
during a refactor, but it protects only the person who remembers to run it and
only for changes with a `HEAD` to compare against. This one holds for anyone
who ever reads the tree.

### The two findings are reported apart, and both count

A surplus parameter with no default raises `TypeError` the moment the hook fires.
One with a default, or `*args` / `**kwargs`, does not — the framework's
zero-argument call succeeds and the decorator's wrongness stays invisible. Both
are counted, because the second is the one that survives; the report labels them
`TypeError` and `masked` so the fatal ones can be taken first.

Both current `enterprise` findings are `masked`:
`knowledge/models/knowledge_article_member.py:32 _check_is_writable(on_unlink)`
under `@api.constrains`, and
`sale_commission/model/commission_plan.py:82 _compute_targets(amount)` under
`@api.depends`.

### `@api.model` and friends are not in scope

`@api.model`, `@api.model_create_multi`, `@api.autovacuum` and the rest describe
how a method is called, not that the framework calls it unprompted. They take
arguments legitimately and are excluded.

## Alternatives considered

**Fold it into ADR-0051's `hookpurity` count.** That one counts a hook that is
*also* a directly-called helper, and is fixed by splitting. This one counts a
method that cannot be a hook at all, and is fixed by moving a decorator. One
number covering both would say nothing about what to do next.

**Make it a diff-time check only.** Cheaper, and it was the first version written.
It finds nothing in a tree nobody is currently editing, which is exactly when the
next reader inherits the bug.

## Consequences

A refactor that moves methods around now fails a gate instead of a business
report. The gate cannot see the inverse mistake — a hook that **lost** its
decorator to a helper above it, leaving both methods well-formed — so ADR-0049's
naming rules and ADR-0051's purity count remain the other half of the picture.

## Enforcement

`tooling/architecture/py_hook_arity.py`, ratcheted per scope in
`tooling/ratchet/baselines/` and run by `.github/workflows/architecture.yml`:
`py_hook_arity` over the core package and `py_hook_arity_addons` over the
bundled tree, both `exact` at 0, and one-sided pins for the siblings whose
findings cannot be fixed from this repository.

Its blind spot is the inverse mistake. A refactor that moves a decorator onto a
helper leaves **two** well-formed methods — the helper wrongly decorated, which
this gate sees, and the real hook now undecorated, which it cannot. The second is
caught only by the compute failing to re-run, or by diffing decorator sets
against `HEAD` during the change. Reach for both during a refactor; this gate is
what protects the reader afterwards.
