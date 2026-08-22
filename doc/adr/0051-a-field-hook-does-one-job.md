# ADR-0051: A field hook does one job, and the ones that do two are counted

- **Status:** Accepted
- **Date:** 2026-08-19

## Context

ADR-0049 and ADR-0050 settle what a field hook is *called*. They assume the
method is a hook. Measuring says that assumption is wrong 342 times.

Of the 3,232 methods a `compute=`, `search=`, `inverse=`, `default=` or
`domain=` names, **2,890 are called only by the framework**. The other **342 are
also called from production code**, making them two things at once: a hook the
ORM invokes on its own schedule, and a helper someone calls by hand.

`compute=` holds 251 of them, and matters most. A compute is a *declaration*:
the ORM decides when it runs, from `@api.depends`. A compute that production
code calls one hundred and ninety-nine times — `_compute_quantity`, defined four
times — is a compute whose dependency graph is not doing its job, with callers
compensating at each site. No naming rule reaches that. The name is fine; the
design is not.

`default=` shows the same shape more mildly and is what first exposed it.
`get_base_url` has over a hundred callers and supplies one URL field's default.
ADR-0049's gate exempts it by hand — a "dedication test" that skips a default
whose method is used too widely to be one — and that exemption is this rule in
disguise, applied to two attributes out of five.

## Decision

**Count the methods that are both a field hook and a directly-called helper.
Ratchet the count. Do not block on it.**

The remedy is a *split*: the hook keeps the hook's name and delegates to a
helper the other callers use. That is why this is its own record. The finding
survives any renaming, so it cannot live under "a hook is named for its field" —
a rename would leave it exactly where it was, and merging the counts would make
a refactor and a rename indistinguishable in one number.

### Calls from tests do not count

A test that calls a compute is exercising it, not depending on it. 67 hooks are
called from tests and nowhere else; counting those would report a well-designed
hook for being tested.

### Nothing is exempted

`_compute_display_name` is defined 167 times and called 48: a framework protocol
models override and code calls on purpose. It is in the count. An allowlist would
be a place for exemptions to accumulate quietly, and a ratchet does not need to
be reachable to be useful — it needs to be lowerable, and every unit of this one
can be lowered by splitting a method.

## Alternatives considered

**Fold it into ADR-0049's gate as a third finding kind.** That gate's findings
are fixed by renaming and this one's by refactoring. One number covering both
tells you nothing about what to do next.

**Flag only the loud cases** — a threshold on call volume. The threshold is
arbitrary, and a hook called twice is doing two jobs as surely as one called two
hundred times. The sort order already puts the loud ones first.

**Exempt the framework protocols by name.** The list would need to be right —
`_compute_display_name` is obvious, the next one is not.

**Leave it to review.** The state this replaces: the rule was already being
enforced, silently and partially, by a heuristic inside another gate.

## Consequences

- The naming gate's dedication test for `default=` and `domain=` is now the
  visible half of a stated rule rather than an unexplained exemption.
- 342 findings arrive with this record, 251 of them computes. Debt, not a defect
  list: each is a method to split when its module is next touched.
- The count includes methods whose split is not obviously worth making — the
  price of not keeping an allowlist, paid once.
- Test callers are invisible, so a hook can gain tests without gaining debt.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0051"`, run by
`.github/workflows/architecture.yml` against a floor in
`tooling/ratchet/baselines/`:

| gate | ratchets |
|---|---|
| `tooling/architecture/field_hook_purity.py` | methods that are both a field hook and a directly-called helper |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record, and `test_every_gate_refuses_an_empty_tree.py` probes
it. Run the gate for the live count.

## Amendments

### 2026-08-19 — the measurement above was wrong, and the decision survives it

The gate shipped counting a call by method name with any receiver. Odoo has
several methods sharing a name across unrelated models, and two dominate:

- `uom.uom._compute_quantity(qty, to_unit)` is a unit-conversion utility called
  198 times. Three unrelated models — `stock.move`, `stock.move.line`,
  `account.move.line` — spell a compute the same way, so each was charged all
  198. Each is called on `self` **zero** times.
- `_compute_display_name` is charged 48 calls on every model that declares it,
  because the calls are made against other models.

Counting only `self.<hook>()` inside the model that declares the hook, and keying
hooks by model as ADR-0049's gate now does, the count is **95, not 342**:
`default=` 51, `domain=` 20, `compute=` 12, `search=` 7, `inverse=` 5.

So the Context is wrong where it says `compute=` holds 251 and that a compute
called 199 times is the worst case — both artefacts of the name collision. The
corrected shape says something better for the rule: the two attributes that
accept an *arbitrary callable*, `default=` and `domain=`, hold 71 of the 95,
which is precisely why ADR-0049's gate needed a dedication test for those two and
no other.

**Known under-report.** A hook invoked on a record other than `self` is now
missed. The receiver's model is not knowable from the AST, and a count that
guesses is worth less than one that under-reports.

### 2026-08-19 — 95 was still wrong, and the shape it argued from was the remedy

Reading all 95 rather than their totals, two shapes turned out not to be two jobs.

*A lambda forwards to a helper.* `default=lambda self: self._default_uom_id()`
declares the *lambda* as the hook; `_default_uom_id` is a helper the lambda
calls, and its other callers are why it exists — precisely the split this record
asks for, so charging the helper penalises the fix. **62 of the 95** are this.

*Two hooks of one field share a value provider.* In
`delivery_stock_picking_batch`, `weight_uom_name` declares both
`compute="_compute_weight_uom_name"` and `default=_default_weight_uom_name`, and
one calls the other. One field, one value, reached twice by the framework — one
job. **10 more** are this.

Excluding both leaves **23**, and they are real. Three, each a different way of
doing two jobs:

- `account.move._compute_name` — an `@api.onchange` clears `name` and then calls
  the compute by hand. The compute is being used as a procedure.
- `stock.location._compute_warehouse_id` — invoked on a recordset because
  `@api.depends` cannot track the dependency, which the surrounding docstring
  states outright. A documented workaround is still two jobs.
- `documents.document._search_user_permission` — takes arguments and is called
  four times as a permission-query builder. The field's search hook *and* an ACL
  utility.

This retires the previous amendment's headline: `default=` 51 and `domain=` 20
were overwhelmingly the lambda shape, the sanctioned remedy counted as the
offence. `domain=` drops to **0**. The corrected shape is `compute=` 11,
`default=` 8, `inverse=` 3, `search=` 1.

ADR-0049's dedication test for `default=` and `domain=` stands on its own
argument — those attributes accept any callable, so nothing but a use count can
tell a dedicated hook from a borrowed helper — and never needed this one.

**The measurement has been corrected twice in two days, the second time
overturning the first, and that is the process working.** Each correction came
from reading the findings rather than the totals, and each made the rule sharper:
the first separated a hook from a same-named method on another model, the second
separated a hook from the helper it was split into. The rule has not moved.

So do not read 342 → 95 → 23 as a gate losing credibility. It is the count
converging on what the rule always described, and it will move again. The
standing instruction: **judge this gate by reading its findings, never by its
total.**
