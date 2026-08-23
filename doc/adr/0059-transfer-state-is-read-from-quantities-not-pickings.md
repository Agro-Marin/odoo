# ADR-0059: `transfer_state` is read from the quantities, not the pickings

- **Status:** Accepted
- **Date:** 2026-08-22

## Context

`mixin.order.stock` computed the order-level `transfer_state` from the states of
the related pickings: no pickings meant `False`, all pickings `done` meant
`done`, some `done` meant `partial`, anything else `to do`.

Two things were wrong with that, and both were visible in the tree.

The **selection could not be produced by its own compute.** `TRANSFER_STATE`
declares five values, `no` and `over done` among them. The picking-driven
compute emits three of them plus `False`. `over done` was unreachable, and `no`
— the value that says "nothing to transfer" — was represented by an empty
field, which is also what an unset field looks like.

The **question it answered was not the question being asked.** A picking
reaching `done` says an operation was processed, not that the ordered quantity
arrived. A receipt validated for 3 of 5 units is `done` as a picking and
`partial` as a receipt, and no arrangement of picking states can distinguish an
over-receipt from an exact one — the quantities are the only place that
information exists.

Downstream, `agromarin/marin` had already concluded this and shipped its own
answer: a line-level `transfer_state` computed from `qty_transferred` against
`product_qty`, rolled up to the order by a mixin of its own, overriding
`_compute_transfer_state` on both `sale.order` and `purchase.order`. The result
was that this repository and its consumer disagreed about what the same stored
field meant, and which answer a database held depended on whether `agromarin`
was on the addons path. `purchase_stock`'s own
`test_transfer_state_no_picking` asserted the empty value, in its docstring and
in an `assertFalse`, while the deployed system produced `no`.

The rollup itself was duplicated a third time. `mixin.order.invoice` already
summarised per-line states into an order-level one — a batched `_read_group`
plus a conditional second one to tell a zero-quantity `no` from a not-yet `no` —
and marin's mixin was that algorithm again, with a different priority bolted on.

## Decision

`transfer_state` is computed per line from the quantities, and the order-level
value is a rollup of the line values.

`mixin.order.line.stock` gains the line-level `transfer_state`, the structural
twin of `mixin.order.line.invoice`'s `invoice_state`: same five states, same
quantity comparison, same contract that concrete models override the wording
and nothing else.

The gathering step both rollups share moves to `mixin.order.state.rollup` in
`base_order`. Only the gathering: each caller keeps its own resolution loop,
because two things about the resolution are specific to invoicing. It defers a
lone `to do` to `_resolve_invoice_state_to_do()`, so `sale` can downgrade an
order whose remaining lines cannot be invoiced alone, and transfers have no
such notion. And it opts into resolving the two meanings of a line-level `no`,
which costs a second query and only invoicing can need: a transferred-policy
line with nothing received is `no` while its quantity is not, whereas a
transfer line reaches `no` only by having a zero quantity — `state` on the line
is `related` to the order's, so every line of a confirmed order is itself
confirmed. For `transfer_state` that query would answer a question that cannot
arise, and it is not run.

The priority the two loops apply is otherwise the same, and ADR-0060 is where
it is argued: `partial` outranks `to do`, and an order with something finished
and something outstanding is `partial`.

`force_fully_delivered` and `force_fully_invoiced`, with their four actions,
move up from marin to `mixin.order.stock` and `mixin.order.invoice`. Purchase
gains the invoice flag it never had.

Pickings keep one say. Under a multi-step route the first steps move nothing to
the customer, so the quantities alone read `to do` after a pick is validated;
that is progress the lines cannot see, and it is reported as `partial`. It can
only raise `to do` — never lower a state the quantities have earned.

## Alternatives considered

**Leave the picking-driven compute and let marin keep overriding it.** This is
the status quo, and it is what a reviewer who finds the override will propose
restoring. It was rejected because the disagreement is not stylistic: the two
implementations write different values into the same stored column, so the
meaning of `transfer_state` depended on the addons path, and a test in this
repository asserted one answer while the deployed system produced the other.
Nothing detects that, because CI checks this repository out alone.

**Adopt marin's rollup wholesale.** Rejected on two counts. It short-circuited
to `to do` whenever the order carried no invoice or picking yet, overriding a
line-level `no` that had correctly worked out there was nothing to do — a
confirmed purchase order on the *on received quantities* policy reported "to
invoice" before anything had been received. And it collapsed every mixed state
to `partial`, including `{no, to do}`, where nothing has been transferred at
all.

**Adopt marin's `partial`-beats-`to do` priority for `invoice_state` too.** The
priority is right for transfers, where `{done, to do}` means one line finished
and another not started and `partial` is the only honest answer. Adopting it
for invoicing would also settle an inconsistency there — `{done, pending-no}`
resolves to `partial` while `{done, to do}` resolves to `to do`, though both
describe the same situation. It was not extended to invoicing because `sale`'s `_resolve_invoice_state_to_do()` fires
only when `to do` wins, and under the new priority `to do` wins only when it is
the *sole* state — at which point the hook's `"no" in states` guard is false.
The auxiliary-line downgrade would have become dead code, and
`stock_delivery`'s `test_03_invoiced_status` tests it.
`invoice_state`'s priority is therefore unchanged; only its gathering moved.

**Put the shared rollup in `base_order_stock`.** It would have been closer to
the new caller, but `mixin.order.invoice` needs it and `base_order` does not
depend on `stock`. The engine lives at the layer both callers can reach.

## Consequences

`over done` and `no` are reachable at both levels, so the filters and
decorations written against them mean something. Over-delivery is visible where
it previously read as `done`.

From this decision on, a draft order reports `no` rather than an empty value.
Anything comparing `transfer_state` to a falsy value sees a truthy `"no"`
instead; the one such assertion in this repository at the time was updated.

`transfer_state` changed meaning without changing shape, so nothing in the
column tells stale rows from fresh ones and the ORM has no reason to recompute
them. `base_order_stock` 19.0.1.1.0 carries a post-migration that flags the
field for recompute on the models inheriting `mixin.order.stock`, and only
those: the line-level field is new, and a newly created stored computed column
is queued for computation by the ORM itself.

One user-visible behaviour change reaches marin: a confirmed purchase order
under the *on received quantities* policy with nothing received reports
`invoice_state = no` rather than `to do`. That is the corrected answer — there
is nothing to bill until goods arrive — but it removes such orders from any
"to invoice" filter until a receipt lands.

`agromarin/marin` loses two mixins, six computes, five fields and six actions,
and the fork stops carrying three copies of one rollup.

## Enforcement

No new gate. The decision is pinned by tests rather than by a checker, because
what it constrains is a computed value and not a code shape:
`purchase_stock/tests/test_purchase_stock_advanced.py` covers over-receipt, the
mixed-line `partial`, the force flag surviving a recompute, and section lines;
`sale_stock/tests/test_sale_stock.py::test_transfer_state` covers the multi-step
route where the pickings still raise `to do` to `partial`;
`stock_delivery/tests/test_delivery_stock_move.py` pins the invoice-side hook
this record deliberately left alone.

A checker is conceivable and was not written: the property worth gating is that
every value a selection declares is reachable from its compute, which is a
whole-tree question about `fields.Selection` and its compute's assignments, not
something specific to this decision. If that gate is ever built, this record is
one of its cases rather than its argument.
