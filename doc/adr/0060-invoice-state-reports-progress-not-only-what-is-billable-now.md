# ADR-0060: `invoice_state` reports progress, not only what is billable now

- **Status:** Accepted
- **Date:** 2026-08-22

## Context

The order-level `invoice_state` summarises the states of an order's lines.
`mixin.order.invoice` resolved them by the priority
`over done` > `to do` > `partial` > `done` > `no`, and that priority made the
field answer a narrower question than its five values suggest.

Two orders that are not alike read the same. A confirmed order whose products
bill on received quantities, with nothing received, has every line at `no` and
so reported `no` — the same value as an order whose lines carry no quantity and
will never be billed at all. One is waiting on a delivery; the other is
finished. The field could not tell them apart, though the data can: a line is
`no` with a quantity when nothing has arrived yet, and `no` without one when
nothing ever will.

Two orders that *are* alike read differently. `{done, pending-no}` resolved to
`partial` while `{done, to do}` resolved to `to do`, though both describe one
line finished and another not. The inconsistency was in the priority itself,
not in the data.

And any order with a single outstanding line reported `to do` however much of
it had already been billed, so "nothing billed yet" and "half billed" were one
value.

`agromarin/marin` had reached the first of these conclusions and bolted a
cruder rule onto purchase alone: if the order carried no bill yet, report
`to do`. That ignored the lines entirely, so an order whose lines could never
be billed still claimed to be billable — and marin's own
`test_14_invoice_state_no_when_every_line_is_no`, asserting the opposite,
failed for as long as the rule existed.

## Decision

`invoice_state` reports how far billing has progressed.

`partial` outranks `to do`. An order with something billed and something
outstanding is `partial`, whether or not any individual line is.

A line-level `no` that still carries a quantity counts as outstanding: it means
"not yet", and the order is `to do` rather than `no`. A `no` line with no
quantity means "never" and does not hold the order back. Telling the two apart
is the `nothing_may_be_pending` lookup in `mixin.order.state.rollup`, which
`invoice_state` opts into; the ambiguous set widens from `{done, no}` to any
order carrying a `no` line, which adds ids to a query that was already batched
rather than adding a query.

`no` therefore means one thing only: nothing will ever be billed here.

The rule lives in `mixin.order.invoice._resolve_invoice_state()` and applies to
sale and purchase alike. `transfer_state` resolves the same way (ADR-0059),
minus the pending term, which a transfer line cannot hold.

## Alternatives considered

**Keep the existing priority.** It is what upstream ships and what eight tests
across `sale`, `sale_stock` and `stock_delivery` assert, so it is what a
reviewer will propose restoring. Rejected because those assertions encode a
convention rather than a requirement: none of them turns on the difference
being reported, and the convention costs the field its ability to distinguish
an order awaiting goods from one that is finished.

**Apply the rule to purchase only.** Implemented first, and it works: the rule
went in `purchase.order._resolve_invoice_state()` and left every sale test
untouched. Rejected because the field means the same thing on both documents,
and the sale/purchase asymmetry it reinstates is the one ADR-0059 had just
removed. The eight sale tests were updated instead.

**Adopt marin's rule as written** — no bill yet, therefore `to do`. Rejected:
it never consults the lines, so it reports billable work for an order that has
none, which is what broke marin's own test. The decision above keeps the
intent and takes the answer from the lines.

**Let `sale`'s auxiliary-line downgrade keep overriding everything.**
`_resolve_invoice_state_to_do()` reports `no` when the only invoiceable lines
cannot be invoiced alone — a delivery fee, a discount. Under the new priority
it is consulted only when nothing has been billed, which is the case it was
written for; from this decision on, an order that has been part-billed reports
`partial` where it previously reported `no`. Keeping the old reach would have
meant an order with a posted invoice describing itself as having nothing to
invoice.

## Consequences

Orders move between buckets, and call sites that asked for `to do` alone stop
matching orders that are now `partial`. Six were widened to accept both: the
sales-team and website "orders to invoice" actions, `project.project`'s
`has_any_so_to_invoice`, the purchase portal's "Waiting for Bill" badge, and
the "To Invoice" and "Waiting Bills" search filters. Call sites phrased as
exclusions — `not in ('no', 'done', 'over done')` — needed nothing, and the
several already spelling `in ('to do', 'no', 'partial')` show the tree had
mostly reached this reading already.

`purchase.bill.match` displays a confirmed order's real amount rather than
`0.00` while it waits for goods, because that display keys off `invoice_state
== 'no'`. A vendor bill arriving ahead of the delivery now matches against a
figure instead of a zero.

Line-level `invoice_state` is unchanged, so anything reading a line — including
`sale_mrp`'s kit check, which searches `sale.order.line` — is unaffected.

## Enforcement

No new gate; the decision constrains a computed value rather than a code shape,
and is pinned by the tests that assert each branch:
`sale/tests/test_sale_order.py`'s two discount-line tests cover the auxiliary
downgrade surviving when nothing is billed and giving way to `partial` when
something is; `sale/tests/test_sale_to_invoice.py` and
`sale_stock/tests/test_sale_stock.py` cover mixed states after a delivery;
`purchase/tests/test_purchase_invoice.py` covers a confirmed order awaiting
goods; and `agromarin/marin`'s `test_14_invoice_state_no_when_every_line_is_no`
covers the zero-quantity case that must stay `no` — the one that failed under
the rule this record replaces.

The gap worth naming: a call site that filters on `invoice_state == 'to do'`
and means "has something to invoice" is now wrong, and nothing detects it.
Six were found by reading every reference in the tree. A checker would have to
understand intent, which is why the widened spellings were chosen over a lint
rule.
