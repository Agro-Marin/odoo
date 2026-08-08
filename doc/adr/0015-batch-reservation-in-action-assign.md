# ADR-0015: Decide a batch's reservation before writing any of it

- **Status:** Accepted
- **Date:** 2026-08-08

## Context

`stock.move._action_assign` reserves a set of moves. Its loop decided *and persisted*
one move's reservation before it looked at the next, because "how much stock is left"
was a question it asked the database. Each iteration therefore cost a round trip, and
the cost was linear in the number of moves.

Measured on a delivery of N single-product moves (SQL captured and grouped by
statement shape, fresh database):

| | N=10 | N=50 |
|---|---:|---:|
| `action_confirm` | 81 queries | 238 queries |

200 of the 238 were four statements repeated once per move:

1. the `_gather` search that finds candidate quants,
2. `INSERT INTO stock_move_line`,
3. `SELECT … FOR UPDATE` on the quant (`try_lock_for_update`),
4. the re-read of that quant under the lock.

(3) and (4) are load-bearing. (4) in particular is the documented fix for the window
between gathering a quant and locking it, during which a concurrent transaction may
have changed it.

(2) is the one that should not have been per-move. `_action_assign` already
accumulates the *bypassed* moves' lines into a shared `move_line_vals_list` and creates
them in one call, and `stock.move.line._reserve_new_move_lines` already groups a
created batch by characteristics and updates each quant once. The machinery for
batching existed at both ends; what defeated it was the reserving path calling
`create()` per move in between.

It called it per move for a real reason. The reservation is what makes the stock
unavailable to the *next* move in the same loop, and the reservation only exists once
the line is written. Deferring the writes naively means every move measures
availability against untouched quants and every one of them believes it has the stock.

## Decision

Separate deciding from applying, and make the information that used to flow through the
database flow through an explicit object instead.

`_ReservationLedger` (in `stock_quant.py`, beside the other pure allocation helpers)
holds, for one `_action_assign` run:

- the quantity claimed on each quant and not yet written, and
- the move line values those claims justify.

It is threaded through the loop in the context, next to the `quants_cache` that is
already there. Three consumers read it:

- `stock.quant._sum_available_quantity` subtracts pending claims, so the *cap* on what
  a move may take is honest;
- `stock.quant._get_reserve_quantity` folds pending claims into each candidate's
  `reserved`, so `_distribute_reservation`'s per-candidate slack agrees with that cap
  and an already-emptied quant is skipped;
- `stock.move._update_reserved_quantity` appends its values to the ledger instead of
  creating them.

The claims become real reservations at the single batched `stock.move.line.create()`
that already ended the method: creating the lines runs `_reserve_new_move_lines`, which
groups them by characteristics and updates each quant once.

### Why the ledger holds the values as well as the numbers

A take recorded without its line over-reserves; a line kept without its take
double-reserves. They are two halves of one fact, and keeping them on one object makes
them hard to separate by accident.

### Why the extension point's signature does not change

`stock.move._update_reserved_quantity` is overridden by `product_expiry` and by
`enterprise/industry_fsm_stock` — which calls it repeatedly and sums what each call
returns — and called by `point_of_sale`. Its contract is "reserve up to this much and
tell me what you got", and that contract is unchanged: only *when* the write happens
moves. A second call still sees the reduced availability, because the ledger carries
what a persisted line used to carry. Overrides needed no edit.

### Why the ledger is scoped to the loop

The batched create runs on `self.env`, outside the loop's context. If the ledger were
visible there, `_reserve_new_move_lines` would subtract the very claims it is about to
persist. `test_the_ledger_is_scoped_to_one_run` pins this.

### Which takes are recorded

Only those whose write was deferred. `_update_reserved_quantity_vals` has a branch that
raises an *existing* move line rather than producing values for a new one; that write
syncs the quant immediately, so recording it too would count it twice. The recording
therefore sits in the two branches that append values, not at the top of the loop.

## Alternatives considered

Added after the fact to satisfy the rule this record is the first to fall under
(`ALTERNATIVES_REQUIRED_FROM = 14`), and assembled **only** from what the
sections above already argue — nothing here is reconstructed. That is the same
constraint `test_alternatives_are_required_from_the_cutoff_on` states for older
records: back-filling a rejected alternative is inventing history.

- **Keep persisting per move** (the status quo). Correct, and the reason the loop
  was written that way: a written line is what makes the stock unavailable to the
  next move. Rejected on the measurement in *Context* — four statements repeated
  once per move, 200 of 238 queries at N=50, linear in the number of moves.
- **Defer the writes and change nothing else** — the naive batching. Rejected
  because every move would measure availability against untouched quants and each
  would believe it has the stock. This is the only alternative that was
  *measured*: stubbing `_ReservationLedger.pending()` to `0.0` reproduces it
  exactly, and 5 of 10 tests fail as over-reservation
  (`'assigned' != 'partially_available'`, `8.0 != 4.0`, a serial move taking two
  units where one was left). The ledger is precisely the difference between the
  two.
- **Change `_update_reserved_quantity`'s signature** to pass the pending state
  explicitly rather than through the context. Rejected: it is an extension point
  overridden by `product_expiry` and by `enterprise/industry_fsm_stock` — which
  calls it repeatedly and sums the results — and called by `point_of_sale`. Its
  contract, "reserve up to this much and tell me what you got", is unchanged by
  the ledger, so no override needed an edit; changing the signature would have
  made this a cross-repo change for no gain.
- **Give the ledger a wider scope than one `_action_assign` run.** Rejected on a
  correctness argument, not a taste one: the batched create runs on `self.env`,
  outside the loop's context, so a visible ledger would make
  `_reserve_new_move_lines` subtract the very claims it is about to persist.
  `test_the_ledger_is_scoped_to_one_run` pins the narrow scope.
- **Batch the remaining two per-move statements as well** — one locking statement
  over the whole set instead of N, and serving the non-strict `_gather` from the
  `quants_cache`. Not rejected, deferred: both are on the concurrency path, their
  failure mode is *silent under-reservation*, and both want concurrency tests this
  change did not need. *What this does not do* carries the detail.

## Consequences

- `action_confirm` on 50 moves: **238 → 189 queries**; on 10 moves: 81 → 73. The 50
  per-move INSERTs became one.
- `_action_assign` is now a planner followed by an apply, which is what makes the
  remaining two steps possible at all (see below).
- One more object to understand, and one context key that changes when a write lands.
  The ledger is pure and DB-free, so the arithmetic that decides who gets the last unit
  is unit-testable without an ORM, as `_distribute_reservation` and
  `_least_packages_search` already are.

### One consequence the suite caught

`preserve_state` was on the loop, so the in-loop creates never triggered
`_reserve_new_move_lines`'s `_recompute_state()` — which writes a move state, which
drags a `stock.warehouse.orderpoint` search behind it. Moving the creates *out* of the
loop moved them out from under that flag, and
`test_action_assign_does_not_refresh_orderpoints_per_move` failed (3 searches for 5
moves against a ceiling of 2). The flag now travels with the batched create, which is
correct on its own terms: the two explicit state writes immediately after already set
what the loop decided, for exactly those moves. Before the lines were batched this call
carried only the bypassed moves' lines and the redundant recompute was cheap; it is not
any more.

That test was written to pin a different optimisation and caught this one. Worth noting
as the argument for keeping cost-shape assertions in the suite, not just behavioural
ones.

### Verified

`stock/tests/test_reservation_batching.py` characterizes the allocation across a batch
in every shape the loop takes: insufficient stock split in order, sufficient stock,
several quants in removal order, serial, lot, foreign UoM, a move that already holds a
line, bypassed moves sharing the loop with reserving ones, chained moves distributing
what their origin brought, and re-assignment being idempotent.

The tests were shown to be discriminating rather than decorative: with
`_ReservationLedger.pending()` stubbed to return `0.0` — precisely the naive batching
this ADR rejects — **5 of 10 fail**, and they fail as over-reservation
(`'assigned' != 'partially_available'`, `8.0 != 4.0`, `8.0 != 6.0: the two legs
together may not exceed what the pick brought`, a serial move taking two units where
one was left). With the ledger, 12 of 12 pass.

## What this does not do

Two of the three remaining per-move statements are still per-move, and both are a
separate decision:

- **The lock and the re-read** are one pair per quant. With N moves over N distinct
  products they are irreducibly N locks — but they could be *one* locking statement over
  the whole set (ordered by id, as deadlock avoidance already requires) followed by one
  read, rather than N of each. That is a change to
  `stock.quant._update_available_quantity`, which is on the concurrency path.
- **The non-strict `_gather`** cannot use the `quants_cache` that `_action_assign` builds
  three lines earlier, because the cache fast path requires `strict` and the primary
  reservation gather is non-strict. Serving it would remove the last per-move query.
  Note this ADR makes that *safer* than it was: with the writes deferred, no quant is
  created mid-loop, which was the case `_QuantsCache.covers()` exists to refuse.

Neither was attempted here. The failure mode of getting them wrong is silent
under-reservation, and both want concurrency tests this change did not need.
