# ADR-0055: `IN` over a bound value goes through the SQL builder

- **Status:** Accepted
- **Date:** 2026-08-20

## Context

`WHERE id IN %s` is a spelling this tree inherited from psycopg2, where it was
correct for a reason that no longer holds. That driver adapted a Python tuple
into the literal `(1, 2, 3)` on the client, before the statement was sent, so
`IN` had a parenthesised list to read by the time PostgreSQL saw it.

psycopg 3 — the only driver `odoo/db/` imports — binds server-side. The
placeholder reaches the server as `$N`, and `IN $N` is not valid SQL for any
value type. Measured against this fork's own cursor on 2026-08-20:

```
cr.execute("... WHERE id IN %(x)s", {"x": (1, 2)})      SyntaxError near "$1"
cr.execute("... WHERE id IN %(x)s", {"x": [1, 2]})      SyntaxError near "$1"
execute_query(SQL("... WHERE id IN %(x)s", x=(1, 2)))   runs
execute_query(SQL("... WHERE id IN %(x)s", x=[1, 2]))   SyntaxError near "$1"
cr.execute("... WHERE id = ANY(%(x)s)", {"x": [1, 2]})  runs
cr.execute("... WHERE id = ANY(%(x)s)", {"x": (1, 2)})  malformed array literal
```

The two working rows are not two styles of the same thing. `= ANY()` wants a
**list**, which psycopg 3 binds as an array. `IN` works only through
`odoo.libs.sql.builder.SQL`, which gives a **tuple** argument its own branch,
expanding it into `(%s, %s, ...)` with one bound parameter per element and
`(NULL)` for an empty tuple. The container type is load-bearing, in opposite
directions for the two operators.

A workspace sweep on 2026-08-20 found 168 `IN %s` occurrences inside SQL string
literals across the four checkouts. Reading all of them: 105 are `SQL()` with a
tuple and correct; one fills the placeholder with a composed `SQL` subquery and
is correct; 49 bind a name this could not resolve statically, and every one, read
by hand, was a tuple. Two were broken, both unnoticed for the same reason — the
code had never executed under psycopg 3:

- `l10n_ec` appended `AND l10n_latam_document_type_id in %(x)s` with
  `tuple(...)` to a where-string that `account`'s sequence mixin executed. It
  crashed every Ecuadorian move that took a sequence. Nothing caught it because
  `l10n_ec_edi`, which exercises that path, could not install at all.
- `marin`'s year-over-year sales wizard built six `EXTRACT(...) IN %s` conditions
  into a string and called `cr.execute(query, params)`. The wizard had no test;
  the comparison it exists to produce had never once run.

The failure mode is specific: not a slow path or a latent correctness question,
but a hard `psycopg.errors.SyntaxError` on the first execution, hiding wherever a
path is untested.

## Decision

**`IN` over a bound value is built by `SQL()`, with a tuple.** Not by string
formatting, and not by handing the query text to `cr.execute` with parameters
beside it. Where a list is what the caller has, the operator is `= ANY(%s)`,
which takes it directly.

The rule is about the *builder*, not the *spelling*. `IN %s` is correct — it is
what over a hundred call sites use — provided the argument reaches
`SQL.__init__`, the only place that knows to expand it.

## Alternatives considered

**Ban `IN %s` and convert everything to `= ANY()`.** It would rewrite 105
correct call sites to fix two broken ones, and `= ANY()` is not a free
substitute: it needs a list where the tree holds tuples, so each conversion also
changes the container and the empty case. `SQL()` renders an empty tuple as
`(NULL)`; `= ANY([])` is a different expression with different NULL semantics.

**Make the cursor adapt tuples, restoring the psycopg2 behaviour.** It would put
a client-side rewriting layer back in front of a driver chosen for binding
server-side, and make `cr.execute` and `SQL()` disagree about what a tuple means.
The builder is where this knowledge already lives.

**Leave it to review.** Rejected on the evidence: both defects survived review
and one survived a fork-wide rename that touched the file beside it.

## Consequences

A query that needs `IN` cannot be assembled as a bare string; it carries its
parameters to `SQL()`. A small constraint on new code, matching what most of the
tree already does.

The gate cannot see a query assembled into a variable and executed in another
method, which is the shape of both defects. Deciding those statically needs real
dataflow, and the coarse alternative — flag any `IN %s` outside an `SQL()` call —
reports core's own correct `ir_ui_view._get_filter_xmlid_query`, which returns
the text from one method for a `SQL(query, res_ids=tuple(...))` in another. A gate
whose findings include correct code is read as broken and ignored, so this one
reports less and means it. The two variable-assembled shapes are held by tests
instead: `l10n_ec_edi`'s suite, and a new `TestSaleOybWizard` that fails with
`syntax error at or near "$9"` if the wizard regresses.

## Enforcement

`tooling/architecture/sql_in_placeholder.py`, ratcheted `exact` in
`architecture.yml` over four scopes — the core package, the bundled addons tree,
and the `enterprise` and `agromarin` siblings through their own cross-repo
workflows. All four floors are **0**, a real zero rather than a vacuous one:
`test_sql_in_placeholder.py` asserts the gate still reports each shape it is
meant to catch, and `test_every_gate_refuses_an_empty_tree` covers the case where
the scope is not there at all.
