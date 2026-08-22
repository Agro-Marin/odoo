# ADR-0052: A count of an x2many is a field, not a compute

- **Status:** Accepted
- **Date:** 2026-08-19

## Context

Counting the records in a One2many or Many2many is one of the most repeated
shapes in the tree. An AST sweep of `odoo/addons`, `addons`, and the sibling
enterprise and agromarin repositories on 2026-08-19 found 636 compute methods
assigning a counter field, spelled three ways: 292 with
`_read_group(..., ["__count"])`, 255 with `len(record.x_ids)`, 40 with
`search_count()` inside a loop over `self`. The split aligns with nothing — not
the module, not the width of the relation, not the author.
`addons/analytic/models/analytic_plan.py` carries two of the three within eight
lines of each other.

`coding_guidelines.rst` §11.1 and §11.2 already prescribe the aggregate — the
worked example *is* the `_read_group` count, and the table bans
`len(search(domain))`. Neither names `len(record.x_ids)`, which is why 255 sites
walk past the rule without appearing to break it.

The reason to care is not the extra query, because there isn't one.
`One2many.read` does not count — it issues a `search_fetch` over the whole
prefetch set, instantiates every matching line as a record, and groups them in
Python. One query returning *every line of every record*, ordered by the
comodel's `_order`, feeding a recordset built only to have `len()` taken of it.
Measured on 80 records of 250 lines, best of five:

    len(record.child_ids)              86.1 ms
    search_count() per record          18.3 ms   (80 queries)
    _read_group(..., ["__count"])       4.8 ms

The `len()` form is 18x the aggregate and 4.7x slower than the N+1 loop §11.1
bans — width beats round trips well before list-view scale. Decomposed at the
same size: `GROUP BY` 3.3 ms of SQL, ordered id fetch 9.7 ms, whole ORM path
89.7 ms — roughly 80 ms is Python materialising rows that exist to be discarded.

That would argue for converting the 255 sites, except the ranking inverts on a
warm cache. A form view has read the lines already, and then `len()` is a
dictionary lookup while the aggregate is a fresh round trip:

    len(record.child_ids)               0.66 ms
    _read_group(..., ["__count"])       4.45 ms

Neither strategy wins outright. The correct rule is conditional on cache state,
and on whether the record has been saved at all — a `NewId` has its lines in
cache and in no table, the honest reason so many are written with `len()`. A rule
that conditional, restated 636 times, will not be applied consistently, and today
it is applied consistently in neither direction: none of the 292 aggregate sites
checks the cache first.

## Decision

**A count of an x2many is declared, not computed.** `fields.Count("line_ids")`
replaces the compute, and the strategy becomes an implementation detail of the
field rather than a decision taken 636 times.

    line_count = fields.Count("line_ids")

`count_of` names a One2many or Many2many on the same model. The field is an
`Integer`; not stored, readonly, not copied by default, depending on the field it
counts. Per call it chooses:

1. a record with a `NewId`, or one whose counted field is already in cache →
   `len()`, both correct and cheaper;
2. anything else → one `_read_group` for a One2many, one `GROUP BY` over the
   relation table for a Many2many;
3. a relation with no batched form — a One2many whose inverse is computed rather
   than stored, so there is no column to group by — degrades to `len()`, decided
   once at setup and readable as `counts_in_database`.

**The count equals `len()`, it does not approximate it.** It carries the counted
field's `domain`, its `context`, the `active_test` predicate
`_RelationalMulti._make_corecords` applies on read, and — for a Many2many — the
`bypass_search_access` flag `Many2many.read` passes to `_search`. Where the
counted value can differ between an `active_test=True` context and an
`active_test=False` one, the field declares `active_test` in its
`depends_context`, because a number cannot be shared between them the way the
x2many's own cache of ids can.

**No new ORM mechanism.** `Field.setup_related` already assigns a field-bound
compute and returns explicit dependencies from `get_depends`; `Count` does the
same for a different job.

## Alternatives considered

**A lint rule, or a ratchet, banning `len(record.x_ids)` in a compute.**
Rejected on the measurement: it would push 255 sites toward a form 6.7x slower on
every warm cache, and it cannot express "unless the field is already loaded" as a
source-level rule. A gate remains useful *after* this record, to find the sites —
not to dictate what they become.

**A `BaseModel` helper, `self._count_x2many("line_ids")`.** It leaves the
counter field, its `@api.depends` and its five lines of boilerplate at every
site, so the thing deduplicated is the smallest part of the shape. It also cannot
set `depends_context`, because by then the field has been declared.

**`fields.Integer(count_of="line_ids")` rather than a class.** The attribute
would exist on every Integer and be meaningful on almost none, and the setup-time
validation would have to be conditional. A distinct class states the requirement
in the constructor.

**Convert everything to `_read_group` by hand and add nothing.** What 292 sites
did. Defensible per site, and it produced the split: the same decision taken
independently lands three ways, and the two conditions that matter most — an
unsaved record, a warm cache — are handled by approximately none of them.

**Leave `len()` alone and make `One2many.read` cheaper.** Out of reach: the read
must produce the ids, because that is what the field's value *is*. The saving
comes from not needing the ids, which only the caller knows.

## Consequences

- One implementation of the cache and `NewId` branches instead of 636 sites that
  each could have them and mostly do not.
- Counters become declarations, so `count_of` is machine-readable: which model
  counts which relation is a fact about the field, not about a method body.
- A Count over a relation with no batched form is not an error. It degrades and
  says so — the difference between a field slower than it could be and one that
  raises in production. `code_mapping_ids` on the account model, whose inverse is
  computed with a `search=`, is the case that put the branch in.
- The 292 existing `_read_group` computes are not wrong and are not in debt.
  Converting one is a readability and warm-cache improvement, not a fix.
- Multi-hop counters — `len(record.parent_id.line_ids)` — are outside this
  record. `count_of` names a field on the model, and 22 sites do not.
- A stored Count takes the default context and stores one number, exactly as the
  stored `len()` counters it replaces already do; it declares no
  `depends_context`, because a stored value cannot vary by one.

## Enforcement

`odoo/orm/fields/count.py` validates its own declaration at registry setup: a
missing `count_of`, a `count_of` naming a field that does not exist, a `count_of`
naming something that is not an x2many, and `related=` are each a refusal, so a
malformed Count fails at load rather than at read.

Equality with `len()` is what the decision rests on, so it is what the tests
assert: `odoo/addons/test_orm/tests/test_count_field.py` computes every Count on
a model beside the `len()` expression it replaces and compares them, over the
One2many, the Many2many, a field with a `domain`, a field pinning
`active_test=False`, archived lines, a `NewId`, an in-memory edit, a warm cache,
a partially warm cache and a relation with no batched form. The query-shape
claims are pinned there too, with `assertQueryCount`.

Nothing yet counts the 295 sites that still spell it the old way. That is a
ratchet in the shape of the ones under `tooling/architecture/`, deliberately not
part of this record: the rule it would enforce is "declare the counter", not
"use `_read_group`", and it needs this field to exist first.
