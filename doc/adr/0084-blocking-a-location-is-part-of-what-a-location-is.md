# ADR-0084: Blocking a location is part of what a location is

- **Status:** Accepted
- **Date:** 2026-08-31

## Context

`stock_blocked_location` was an AgroMarin addon that gave `stock.location` five
blocking modes — `soft_in`, `soft_out`, `soft_both`, `hard` and none — and
enforced them. It shipped 850 lines of Python across four models, four security
groups, three inherited views and 137 tests, and it depended on `stock` alone.

Every line of it was an override of `stock`:

| the addon's model | what it overrode |
|---|---|
| `stock.location` | `create`, `write`, `_quantity_domains` |
| `stock.move` | `_action_done` |
| `stock.move.line` | `create`, `write` |
| `stock.quant` | `_get_available_quantity`, `_get_reserve_quantity`, `_get_gather_domain`, `_update_available_quantity` |

It declared no model of its own, no menu, no action, no report. Its entire
surface was two stored columns on `stock_location` and a set of gates threaded
through `stock`'s reservation, gathering and validation paths — the paths a
warehouse runs on, not a feature bolted beside them.

Three costs followed from that shape.

**The overrides were invisible to `stock`'s own tests.** `_get_reserve_quantity`
is 60 lines of removal-strategy and packaging logic; the addon wrapped it to
change which quants are gatherable. `stock`'s suite exercises the wrapped
version in no lane, because `integration_tests.yml` installs `stock` without the
addon and `module_installability.yml` only asks whether the graph assembles.
The behaviour that decides whether a delivery can be reserved was tested only
where the addon was installed.

**`sudo()` and the context were doing security work across a module boundary.**
The addon's gates key off context flags — `stock_blocked_completing`,
`stock_blocked_is_inventory` — set by its own `_action_done` and read by its own
`_check_operation_allowed`. Because the web client controls the context of every
`call_kw`, a plain `True` there is forgeable, and the addon answered with a
module-level sentinel object that cannot cross the JSON boundary. That is the
right answer, and it is one an addon has to invent because the flag has to
survive a trip through code it does not own.

**A recursive stored compute broke, and the addon's own suite recorded it
passing nowhere.** `effective_block_type` merges a location's mode with every
ancestor's. Measured on `19.0-marin` at HEAD, two of the addon's hierarchy tests
failed: three levels deep, a grandchild kept `none` under a hard-blocked
ancestor. The cause is not in the addon — the recompute engine hands a recursive
field one record at a time in an order that put the descendant before its
ancestor, so the descendant read the parent's pre-write value, stored it, and
was never marked again. `stock.location`'s `complete_name` has the same shape and
the same exposure; it has survived on batch order.

## Decision

**The blocking feature is part of `stock`.** Its fields, groups, enforcement,
views, translations and tests live in `addons/stock`; the addon is gone.

Its xml ids are re-homed from `stock_blocked_location.*` to `stock.*`, its three
inherited views are folded into the base arch of the views they inherited, and
its constants live in `stock/const.py` beside the ones already there.

`effective_block_type` walks `block_type` up the tree rather than reading
its parent's `effective_block_type`. The `depends` still names the parent's
computed field, because that is what marks a whole subtree when an ancestor
changes; the compute body reads a plain stored column, which is never pending,
so the result no longer depends on the order the engine chose.

## Alternatives considered

**Leave it an addon.** The reviewer's case is separation of concerns: a
warehouse that never quarantines anything should not carry the code. It does not
survive contact with the shape — the code is not beside `stock`'s reservation
path, it is *in* it, and an addon whose whole body is overrides of one module is
that module with an install flag in front of it. The flag's real cost is the
untested combination: `stock` alone and `stock` + addon are two different
reservation engines, and only the first has a lane.

**Keep the addon and add an integration lane for it.** This buys the missing
coverage and none of the rest. The context sentinel still exists because the
boundary still exists; `_get_reserve_quantity` still has two versions; and the
lane doubles the cost of every future change to `stock`'s gathering, since both
combinations must stay green.

**Fix the recursive compute in the ORM instead.** The ordering defect is real
and is not this addon's — `_recompute_singly` expands a recursive field's
pending set from the record that was read, so a descendant can precede its
ancestor. Changing that ordering is a core change whose blast radius is every
recursive stored compute in the tree, `complete_name` and `parent_path`
consumers included. It is owed a record and a measurement of its own; it is not
a thing to do inside a module absorption. The local fix here is total for this
field and costs one tree walk of warehouse depth.

## Consequences

- **`stock` can no longer be installed without location blocking.** Every
  database that has `stock` gains two stored columns on `stock_location`, four
  groups and a radio on the location form. The default is `none` everywhere, so
  no behaviour changes until somebody blocks a location.
- **Every reference to a `stock_blocked_location.*` xml id breaks.** Inside this
  workspace there were sixteen, all in `agromarin/marin`, and all are re-homed.
  Outside it, a deployment's studio customisation or server action naming one
  must be updated by hand; the module row is deleted, so the id resolves to
  nothing rather than to something wrong.
- **The absorbed suites run in `stock`'s lane**, which is where the code they
  cover has always been. 137 tests, `test_blocked_location_*`.
- **`bypass_blocked_locations` stays the public escape hatch**, honoured under
  `env.su` only. Absorbing the code did not widen it.

## Enforcement

The absorption itself runs once, in `odoo/addons/base/migrations/1.25/`: it
re-homes the xml ids, deletes the three inherited views before the data files
load — a survivor would add `block_type` to a form that now declares it, and the
upgrade would fail on view validation — and removes the module row. It lives in
`base` and not in `stock` because `module_graph.extend` drops a module whose
directory is missing *and everything that depends on it*, so by `stock`'s own
pre-migration `marin` would already have stopped loading.

The addon's own data migrations are carried over in
`addons/stock/migrations/1.13/`, for databases that never reached them —
**as a `post-migrate`, through the ORM, and that is not a stylistic choice.**
Every gate reads `effective_block_type`, never `block_type`. Clearing an illegal
`block_type` in raw SQL, which is what the addon's own 19.0.3.0.0 did, leaves
the stored recursive compute at its old value on that row and its whole subtree,
and nothing marks it for recomputation. `hard` is in `INCOMING_BLOCK_TYPES`, so
a customer location left reading `hard` refuses every delivery into it for
anyone without the override, with nothing in the UI saying why. The same script
resyncs `effective_block_type` across the tree for the same reason: a stored
value that disagrees with its own compute is the feature being wrong in silence,
under-enforcing as readily as over-enforcing.

`test_blocked_location_migration.py` pins both directions, and was checked
against the raw-SQL shape to confirm it fails there.

No new gate. The feature is held by `stock`'s existing lanes.

## Amendments

### 2026-08-31 — three references corrected, no argument touched

`test_adr_coherence` was red on this record from the commit that landed it, and
its author had signed off. Corrected by another session under §12.1, which makes
a red gate mine once nobody is mid-fix on it. Recorded here because §10 makes an
Accepted record immutable, so a later reader is owed the diff rather than a
silent rewrite. The decision, the reasoning and every figure are unchanged.

- **The stock paths lost their odoo/ prefix**, twice, including the migrations
  path: they now read `addons/stock`. The gate resolves ADR paths from the repo
  root, where `odoo/` is the framework core PACKAGE and the bundled addons are
  `addons/`, so the original spelling resolved to nothing. Named in prose here
  rather than quoted, because a backticked path is itself a reference the gate
  must resolve -- quoting the broken one to explain it keeps the gate red.
- **`` `stock.location.complete_name` `` → `` `stock.location`'s `complete_name` ``.**
  A backticked dotted token is read as a model name, and no `_name`/`_inherit`
  declares that one. The field is real; the spelling asserted a model that is
  not. This is the same convention the rest of the corpus follows — `portal`'s
  `access_token` rather than the dotted form.
- **"`effective_block_type` now walks…" → "…walks…".** "Now" asserts a live
  status inside an immutable record, which `TestNoLiveStatusClaims` forbids: what
  is current at the time of writing stops being current, and the record cannot
  be edited to say so.

The `stock.location`'s `complete_name` exposure the Context names is unchanged
and still open.
