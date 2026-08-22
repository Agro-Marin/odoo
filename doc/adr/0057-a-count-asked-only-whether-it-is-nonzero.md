# ADR-0057: A count asked only whether it is nonzero takes a limit

- **Status:** Accepted
- **Date:** 2026-08-21

## Context

`search_count(domain)` scans every matching row so it can say how many there
are. A large share of its callers want only to know whether there is at least
one:

```python
if not self.search_count([]):
    _logger.error("No language is active.")
```

That counts every language in the database to decide whether the count is zero.
`search_count` already takes a `limit`, and with one the query stops at the first
row.

Measured on this fork against `ir.model.fields` at 8,001 rows, best of twenty
with the cache invalidated between runs:

```
search_count([])            0.248 ms
search_count([], limit=1)   0.053 ms     4.7x
```

The ratio is not the argument — the shape of the curve is. One is O(rows), the
other O(1). The same call against a production `account.move.line` costs whatever
that table has grown to, and a development database is where that cost is
invisible.

An AST sweep on 2026-08-21 found **83 such calls** outside tests across the four
checkouts: 3 in the framework core, 42 in the bundled addons, 26 in `enterprise`,
12 in `agromarin`. Every one passes no limit and every one has its result
consumed by an `if`, a `not`, a `bool()`, or a comparison against `0`.

Two things make this a record rather than a cleanup commit. The shape keeps being
written — it reads naturally, and nothing in review distinguishes it from a call
that wants the number. And a handful sit inside a `for record in self:` loop in a
compute, where the table scan is paid once per record; `test_lint E8507` sees the
loop but not the scan, and ADR-0052's gate sees the loop but prescribes
`fields.Count`, which cannot express a filtered domain.

## Decision

**A count whose result is used only as a truth value passes `limit=1`.**

The rewrite is one keyword and the semantics are identical: `limit=1` makes the
result 0 or 1, and `== 0`, `> 0`, `not`, `bool()` and an `if` test cannot tell
the difference.

Where the number itself is wanted, `search_count` without a limit is correct and
stays.

## Alternatives considered

**Rewrite them as `bool(search(domain, limit=1))`.** The same query with more
words, and it materialises a recordset to throw away.

**Leave it to review.** Rejected on the evidence: 83 sites, several in `base`,
one counting every row of a table to write a log line.

**Fix all 83 in one sweep.** Rejected as the FIRST move, not on principle. The
sites span four repositories and dozens of modules, each wanting its own test run
to verify; a sweep that large lands unverified or not at all. The gate goes in
first at today's count so nothing new can be added, and the floor comes down
behind it at the pace each module can be verified (ADR-0006).

## Consequences

New code cannot add one of these without moving a floor, which is the point.

The gate cannot see a count used inside a larger boolean expression —
`vals and self.search_count(domain)` — because the VALUE escapes there and
`limit=1` would hand a `1` to whatever consumes it. Thirteen sites in the tree
are that shape. They are real debt and need reading, so they are left out of the
floor rather than put into it as findings that cannot be acted on without opening
the file.

## Enforcement

`tooling/architecture/py_count_as_boolean.py`, ratcheted in `architecture.yml`
over four scopes — the core package, the bundled addons tree, and the
`enterprise` and `agromarin` siblings through their own cross-repo workflows.
The floors start at the counts above and are `exact` on the odoo side,
`--mode no-increase` for the siblings, per the scoping in
`doc/architecture/gates.md`.

`test_py_count_as_boolean.py` pins each shape it must catch and each it must
leave alone, including the boolean-expression exclusion and the already-limited
form.
