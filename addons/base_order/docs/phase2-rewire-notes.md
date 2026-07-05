# Phase 2 review notes — behavioral divergences introduced by base_order extraction

Things Phase 2 (rewire sale/purchase) must double-check against the original bodies.

## Task 4 — `_update_order_line_info` (order.mixin)
- **quantity-0-no-line branch**: the generic returns
  `_get_catalog_removed_line_price(product)` (sale's pricelist price). Purchase's
  original fell through and returned `pol.price_unit_discounted_taxexc` on an
  EMPTY recordset (== 0.0). After rewiring, purchase's catalog will return the
  seller price instead of 0 in this edge case. Verify this is acceptable, or have
  purchase override the hook to return 0.
- Sale's `request.update_context(catalog_skip_tracking=True)` was moved to the
  `_prepare_catalog_update()` hook (no-op in base). Sale must override it in
  Phase 2, else catalog line updates will start tracking.

## Task 8 — line `write()` qty tracking (order.line.fields.mixin)
- Generic `_collect_qty_changes` does NOT reproduce purchase's extra guard for
  `qty_transferred` (skip when `context.accrual_entry_date` is set). Purchase must
  override `_collect_qty_changes` or gate inside `_post_quantity_changes`, else
  qty_transferred changes post during accrual entries. product_qty path is faithful.
- Generic posts AFTER super().write() (purchase's order); sale originally posted
  BEFORE super via `_update_line_quantity`. Message content is identical (old/new
  captured pre-write). Verify sale chatter ordering is unaffected.

## Task 9/10 — plan gap-list inaccuracies confirmed
- product_uom_qty + _compute_product_uom_qty already existed in
  order.line.amount.mixin (B3 was already done). product_qty/price_unit/discount
  fields also already there. Only product_qty compute, product_uom_id compute,
  allowed_uom_ids field+compute, product_name_translated, product_is_archived were
  real gaps.
- B7 translated-name lang reuses `_get_line_description_lang()` (same source as the
  name compute in both models) instead of a separate `_line_translation_lang` hook.

## Task 12 — `_should_update_price` (order.line.amount.mixin)
- Generic uses sale's `has_baseline = self._origin.id or old_auto_price`. Purchase's
  original used only `if old_auto:`. Edge case: existing line with price_unit_auto==0
  → generic treats as having a baseline (compares vs 0), purchase treated as new line.
  Verify purchase pricing unaffected (price_unit_auto==0 is unusual/free product).
- force_recompute param kept; base reads `context.force_price_recomputation` (sale's
  key; purchase never sets it → no effect).

## Task 13 — `_compute_price_and_discount` + price_unit_auto (order.line.amount.mixin)
- `price_unit_auto` is now a COMPUTED field (compute=_compute_price_and_discount,
  store, precompute) matching purchase. Sale's original was a PLAIN field set
  imperatively. Making it computed is a superset (the method still sets it), but
  verify sale doesn't rely on price_unit_auto NOT recomputing on depends triggers.
- Sale's real `_compute_price_and_discount` is ~145 lines (combo, fiscal position,
  separate discount block). Phase 2 sale must fold ALL of that into
  `_get_auto_price_and_discount()` returning (auto_price, auto_discount), OR override
  the whole compute. The generic skeleton matches purchase's clean version.

## Task 14/15 — invoice (order.invoice.mixin) + NEW account.move.line extension
- **NEW FILE** base_order/models/account_move_line.py adds `is_downpayment` (Boolean)
  to account.move.line. Both sale AND purchase declared this identically (it is NOT
  in `account`). Phase 2: DELETE the `is_downpayment` field decl from
  sale/models/account_move_line.py and purchase/models/account_move_line.py (keep
  their model-specific link fields sale_line_ids / purchase_line_ids).
- Generic `_create_invoices` is a faithful 4-phase skeleton but drops several
  divergent details that Phase 2 sale/purchase must restore via hook overrides:
  * sale: down-payment section line + down-payment quantity negation (in
    `_prepare_invoice_line_commands` / `_get_invoiceable_lines`); resequencing when
    grouping (`_get_invoice_line_sequence`); `message_post_with_source` origin link
    (via `_post_create_invoices`); grouped-vals also merge payment_reference/ref
    (generic only merges invoice_origin — override `_group_invoice_vals`).
  * purchase: pending_section carry-over in line building; per-vals `with_company`
    create; attachment linking (via `_post_create_invoices`); `create_invoice`
    should become a thin wrapper delegating to `super()._create_invoices()`.
  * negative-move switch: generic switches unconditionally (purchase's behavior);
    sale gated on `final` + `env.protecting([team_id])`. Verify sale non-final
    invoices with negative totals aren't wrongly switched — sale may override.
  * sale's access path uses sudo create (kept); verify billing-permission flow.

## Post-Phase-1 inventory audit (2026-07-04) — additional lifts

A full same-name cross-reference of sale/purchase order+line methods and fields
against the mixins found gaps the original spec missed. Lifted:

- **`is_late` + `_search_is_late` + `_get_domain_is_late` (order.mixin).**
  Generic domain is sale's 3-term version (incl. `date_planned != False` —
  needed so negation covers undated orders; purchase only ever uses the domain
  positively, so semantics are unchanged). Hook `_get_is_late_search_domain
  (domain, positive)` defaults to `domain`/`~domain` (sale); **purchase must
  override it** with its line-level `qty_transferred < product_qty` SQL wrap.
  `date_planned` itself stays concrete: sale's is a non-storable compute
  ("depends on today()"), purchase's is stored/editable/indexed.
- **`_get_product_catalog_lines_data` skeleton (order.line.fields.mixin).**
  The order mixin already *called* it (`_default_order_line_values`) without
  defining it. Generic: 3-branch driver + multi-line quantity aggregation +
  `{'quantity': 0}` empty branch. Hooks `_get_catalog_single_line_data` /
  `_get_catalog_multi_line_data` are NotImplementedError — **both sale and
  purchase must implement them in Phase 2** (sale: pricelist price, combo
  readOnly, uomDisplayName always; purchase: seller `_get_product_price_and_data`
  payload, conditional uomDisplayName).
- **`product_template_attribute_value_ids` (order.line.fields.mixin).**
  Byte-identical related field in both; delete both concrete declarations.
- **`_prepare_down_payment_line_section_values` (order.invoice.mixin).**
  Common 3-key subset (sale's exact body). **Purchase must override** to add
  `name=_("Down Payments")` and `sequence=(last line's)+1` on top of super().

Audited and ruled **concrete-only** (do NOT try to lift in Phase 2):

- `date_planned` field + `_compute_date_planned` (order): field attributes and
  aggregation diverge (sale: min of line lead-time projections, non-stored;
  purchase: stored min of line `date_planned`).
- line `_get_date_planned`: **same name, incompatible signatures** (sale:
  instance method using `customer_lead`; purchase: `@api.model` taking
  `(seller, po)`). Name collision only — never generic. Beware if a future
  mixin method wants to call it.
- `_get_mail_template`: divergent return contract (sale returns a
  `mail.template` record, purchase returns a template *id*) and divergent
  branching. Phase-2+ opportunity: normalize purchase to return a record, then
  lift a `_get_mail_template_xmlid()` hook — do it as its own change, not
  during the rewire.
- `product_no_variant_attribute_value_ids`: sale is a stored compute
  (`_compute_custom_attribute_values`), purchase a plain M2M.
- Comodel-bound fields: `line_ids`, `order_id`, `parent_id`, `tag_ids`
  (crm.tag vs srm.tag), `duplicated_order_ids`.
- Reminder (spec B7): purchase's `translated_product_name` field +
  `_compute_translated_product_name` must be **renamed** to the mixin's
  `product_name_translated` / `_compute_product_name_translated` during rewire.

## Bridge fields added to the test model (NOT in mixins — concrete-only by design)
- line: company_id, currency_id, state, partner_id, locked,
  product_type, product_categ_id, parent_id  (all related-from-order or product,
  matching sale/purchase concrete decls). These are the fields the mixins expect
  the concrete model to supply — confirms the "Requires ... from concrete model"
  docstrings are accurate.
