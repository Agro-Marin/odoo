# Approval Models

## Model Relationship Diagram

```
approval.category                       [inherits mixin.mail.thread, mixin.catalog]
    +-- approver_ids -----> approval.category.approver
    |                           +-- user_id -----> res.users
    |                           +-- approver_ids -> res.users (m2m)
    |                           +-- currency_id -> res.currency
    +-- rule_ids ---------> approval.rule      [inherits mixin.approval.threshold]
    |                           +-- approver_ids -> res.users (m2m)
    |                           +-- currency_id -> res.currency
    +-- document_requirement_ids -> approval.document.requirement
    +-- template_count ----> approval.template (o2m via category_id)
    +-- allowed_user_ids --> res.users (m2m)
    +-- allowed_group_ids -> res.groups (m2m)
    +-- approver_group_id -> res.groups
    +-- escalation_user_id -> res.users
    +-- automation_id ----> base.automation
    +-- sequence_id ------> ir.sequence

approval.request
    +-- category_id -------> approval.category
    +-- request_owner_id --> res.users
    +-- partner_id --------> res.partner
    +-- company_id --------> res.company
    +-- currency_id -------> res.currency   (amount is Monetary in THIS currency;
    |                           rules convert into their own before
    |                           comparing — mixin.approval.threshold)
    +-- approver_ids ------> approval.approver (o2m)
    |                           +-- user_id -----> res.users
    |                           +-- delegate_id -> res.users
    |                           +-- decided_by_user_id -> res.users
    |                           +-- source_rule_id -> approval.rule
    |                           +-- refusal_reason_id -> approval.refusal.reason
    +-- refusal_reason_id -> approval.refusal.reason (canonical, request-level)
    +-- template_id -------> approval.template
    +-- applied_rule_ids --> approval.rule (m2m)
    +-- res_model/res_id --> Any model (Many2oneReference)
    +-- attachment_ids ----> ir.attachment (o2m)
    +-- automation_runtime_id -> automation.runtime

mixin.approval.threshold (Abstract)   — base of approval.rule
    +-- company_id --------> res.company   (empty = applies to every company)
    +-- currency_id -------> res.currency  (required; thresholds are in it)

mixin.approval (Abstract)
    +-- approval_request_id -> approval.request
    +-- approval_state (related)
    +-- pending_approver_ids (related)

approval.refusal.reason
    +-- category_ids ------> approval.category (m2m)

approval.metrics (SQL View)
    +-- category_id -------> approval.category

approver.performance (SQL View)
    +-- user_id -----------> res.users

approval.dashboard (Singleton)
    +-- slowest_category_id -> approval.category
    +-- slowest_approver_id -> res.users
    +-- most_pending_approver_id -> res.users

mail.activity (extended)
    +-- approval_request_id -> approval.request (computed)
    +-- approver_id -------> approval.approver (computed)
```

**Product lines are NOT part of this module.** `approval.request.line`,
`approval.category.product_ids` and `has_product` moved to the separate
`approval_product` module; migration `19.0.1.0.12` hands the records over
and drops the field/view/ACL definitions here.

---

## approval.category

| Key | Value |
|-----|-------|
| Model | `approval.category` |
| File | `models/approval_category.py` |
| Type | Model |
| Inherits | `mixin.mail.thread`, `mixin.catalog` |
| Order | `sequence, id` |
| Multi-company | Yes (`_check_company_auto`) |

`mixin.catalog` (`odoo/odoo/addons/base/models/mixin_catalog.py`) is where
`name` (Char, required, `translate=True`) and `active` come from, along
with a unique-name index that is on by DEFAULT. This model redeclares it
scoped to the company (`_name_src_uniq = name_uniq_index("company_id")`),
so category names are unique per company, archived rows included.

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `company_id` | Many2one(`res.company`) | Yes | No | default=env.company, tracking, index |
| `company_currency_id` | Many2one(`res.currency`) | No | No | related=company_id.currency_id |
| `name` | Char | Yes | Yes | translate (from `mixin.catalog`), unique per company |
| `active` | Boolean | Yes | No | default=True (from `mixin.catalog`), tracking |
| `sequence` | Integer | Yes | No | |
| `sequence_code` | Char | Yes | Yes | unique per company (`_sequence_code_uniq`, nulls not distinct) |
| `sequence_id` | Many2one(`ir.sequence`) | Yes | No | check_company |
| `image` | Binary | Yes | No | default=Folder.png |
| `description` | Char | Yes | No | translate |
| `has_date` | Selection(required/optional/no) | Yes | Yes | default="no", tracking |
| `has_date_deadline` | Selection | Yes | Yes | default="no", tracking |
| `has_date_planned` | Selection | Yes | Yes | default="no", tracking |
| `has_date_range` | Selection | Yes | Yes | default="no", tracking |
| `has_partner` | Selection | Yes | Yes | default="no", tracking |
| `has_payment_method` | Selection | Yes | Yes | default="no", tracking. **DEPRECATED**: no-op (no `payment_method_id` field exists on approval.request); hidden from the category form, kept for schema stability |
| `has_automation` | Selection | Yes | Yes | default="no", tracking |
| `has_quantity` | Selection | Yes | Yes | default="no", tracking |
| `has_amount` | Selection | Yes | Yes | default="no", tracking |
| `has_reference` | Selection | Yes | Yes | default="no", tracking |
| `has_location` | Selection | Yes | Yes | default="no", tracking |
| `has_document` | Selection(required/optional) | Yes | Yes | default="optional", tracking |
| `group_approval` | Selection(`no`="Users" / `exclusive`="Security group") | Yes | Yes | default="no", tracking. Labelled "Approver Source". Only two values, so `!= "no"` and `== "exclusive"` are the same test in `_compute_desired_approvers` — in `exclusive` mode the category list, the manager hook and approver-replacing rules are all bypassed and the group's `all_user_ids` become the approvers, all optional |
| `approver_group_id` | Many2one(`res.groups`) | Yes | No | tracking |
| `approver_group_user_ids` | Many2many(`res.users`) | No | No | related=approver_group_id.all_user_ids — members reachable through implied groups, not just direct ones |
| `allowed_user_ids` | Many2many(`res.users`) | Yes | No | Gate request creation; also the `restricted_users` read audience |
| `allowed_group_ids` | Many2many(`res.groups`) | Yes | No | Gate request creation; also the `restricted_groups` read audience |
| `privacy_visibility` | Selection(private/restricted_users/restricted_groups/employees) | Yes | Yes | **default="private"**, tracking. Additive READ audience (ir.rule based) — the default adds NO audience beyond requester/approvers/delegates/managers |
| `approval_minimum` | Integer | Yes | Yes | default=1, tracking |
| `approval_type` | Selection([general]) | Yes | No | tracking, extensible |
| `target_model` | Selection([]) | Yes | No | tracking, extensible |
| `approve_sequentially` | Boolean | Yes | No | tracking |
| `approver_ids` | One2many(`approval.category.approver`) | Yes | No | |
| `document_requirement_ids` | One2many(`approval.document.requirement`) | Yes | No | |
| `rule_ids` | One2many(`approval.rule`) | Yes | No | |
| `rule_count` | Integer | No | No | compute |
| `template_count` | Integer | No | No | compute |
| `invalid_minimum` | Boolean | No | No | compute |
| `invalid_minimum_warning` | Char | No | No | compute |
| `count_request_to_validate` | Integer | No | No | compute |
| `color` | Integer | Yes | No | |
| `kanban_dashboard` | Text | No | No | compute (JSON) |
| `show_on_dashboard` | Boolean | Yes | No | default=True |
| `approval_deadline_hours` | Integer | Yes | No | default=48, tracking |
| `escalate_overdue` | Boolean | Yes | No | default=False, tracking (legacy flag; the dedicated overdue cron was removed, escalation runs via `cron_smart_escalation`) |
| `escalation_user_id` | Many2one(`res.users`) | Yes | No | tracking |
| `auto_expire_hours` | Integer | Yes | No | default=0, tracking |
| `sla_target_hours` | Integer | Yes | No | default=0, tracking |
| `sla_warning_pct` | Integer | Yes | No | default=80, tracking |
| `consent_approval_hours` | Integer | Yes | No | default=0, tracking |
| `automation_id` | Many2one(`base.automation`) | Yes | No | |

### Key Methods

| Method | Purpose |
|--------|---------|
| `create()` | Always auto-creates the ir.sequence from sequence_code |
| `write()` | Syncs sequence_code and company_id to ir.sequence |
| `_compute_kanban_dashboard()` | Batched _read_group for dashboard JSON |
| `_compute_minimum_validity()` | Validates minimum vs available approvers |
| `create_request()` | Opens new request form with defaults |
| `_get_view_request()` | Base helper for all dashboard view actions |

### Constraints

| Method | Rule |
|--------|------|
| `_constrains_approval_minimum` | minimum >= count(required approvers) |
| `_constrains_approver_ids` | No duplicate users in approver list |
| `_constrains_approve_sequentially` | Sequential requires minimum >= 1 |
| `_constrains_consent_sequential` | Consent auto-approval cannot be combined with sequential approval |
| `_constrains_approval_minimum_vs_group` | In `exclusive` mode the minimum cannot exceed the security group's member count — the group IS the approver list, so a higher minimum is unreachable |
| `_constrains_group_approval` | Group approval requires a security group (with members in exclusive mode) |

### SQL constraints

| Name | Rule |
|------|------|
| `_name_src_uniq` | `name` unique per `company_id` (redeclares `mixin.catalog`'s default whole-table index with a company scope; archived rows keep their name reserved) |
| `_sequence_code_uniq` | `unique nulls not distinct (sequence_code, company_id)` |

---

## approval.category.approver

| Key | Value |
|-----|-------|
| Model | `approval.category.approver` |
| File | `models/approval_category_approver.py` |
| Type | Model |
| Order | `sequence` |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `category_id` | Many2one(`approval.category`) | Yes | Yes | ondelete=cascade |
| `existing_user_ids` | Many2many(`res.users`) | No | No | compute |
| `user_id` | Many2one(`res.users`) | Yes | Yes | ondelete=cascade, index |
| `sequence` | Integer | Yes | No | default=10 |
| `required` | Boolean | Yes | No | default=False |

---

## approval.request

| Key | Value |
|-----|-------|
| Model | `approval.request` |
| Files | `approval_request.py`, `approval_request_compute.py`, `approval_request_action.py`, `approval_request_validation.py`, `approval_request_helper.py`, `approval_request_cron.py` |
| Type | Model |
| Inherits | `mixin.mail.thread.main.attachment`, `mixin.mail.activity` |
| Chatter access | `_mail_post_access = "read"` — read rights are enough to post, so an approver who can see a request can comment on it without holding write |
| Order | `create_date desc, id desc` |
| Multi-company | Yes (`_check_company_auto`) |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `company_id` | Many2one(`res.company`) | Yes | No | default=env.company, index |
| `category_id` | Many2one(`approval.category`) | Yes | Yes | index, allowed-user/group domain |
| `category_image` | Binary | No | No | related |
| `request_owner_id` | Many2one(`res.users`) | Yes | Yes | default=env.user, check_company, index |
| `partner_id` | Many2one(`res.partner`) | Yes | No | check_company, index=btree_not_null |
| `name` | Char | Yes | No | tracking, copy=False. **Empty until `action_confirm` assigns the sequence consecutive**; drafts show a translated "New" placeholder via `display_name` only |
| `priority` | Selection(0-3) | Yes | Yes | default="1", tracking, index (the escalation cron filters on `(state, priority)` every 4 hours) |
| `last_reminder_date` | Datetime | Yes | No | readonly, copy=False |
| `reminder_count` | Integer | Yes | No | default=0, readonly, copy=False |
| `escalated_to_manager` | Boolean | Yes | No | default=False, readonly, copy=False |
| `date` | Datetime | Yes | No | |
| `date_start` | Datetime | Yes | No | |
| `date_end` | Datetime | Yes | No | |
| `date_deadline` | Datetime | Yes | No | |
| `date_planned` | Datetime | Yes | No | |
| `date_confirmed` | Datetime | Yes | No | index (cleared by reset-to-draft) |
| `date_approval_granted` | Datetime | Yes | No | compute, store, index, copy=False, cleared whenever the request is not in the state it records |
| `date_refused` | Datetime | Yes | No | compute, store, index, copy=False, cleared whenever the request is not in the state it records |
| `date_cancelled` | Datetime | Yes | No | compute, store, index, copy=False, cleared whenever the request is not in the state it records |
| `refusal_reason_id` | Many2one(`approval.refusal.reason`) | Yes | No | readonly, copy=False, tracking. Canonical reason of the terminal refusal (wizard, cascade or auto-rule) |
| `refusal_note` | Text | Yes | No | readonly, copy=False, tracking |
| `pending_change_field` | Selection(date/reason) | Yes | No | readonly, copy=False. Field the requester must update before approval can resume |
| `location` | Char | Yes | No | |
| `reference` | Char | Yes | No | |
| `reason` | Html | Yes | No | |
| `quantity` | Float | Yes | No | |
| `amount` | **Monetary** | Yes | No | Expressed in `currency_id`, NOT company currency |
| `currency_id` | Many2one(`res.currency`) | Yes | **Yes** | default=env.company.currency_id. The unit of `amount`; rules convert into their OWN currency before comparing (`mixin.approval.threshold._convert_request_amount`), and it is in `_LOCKED_FIELDS` — changing it after submit would move every threshold the decision was made against |
| `approver_ids` | One2many(`approval.approver`) | Yes | No | check_company |
| `user_ids` | Many2many(`res.users`) | No | No | compute |
| `state` | Selection(new/pending/approved/refused/cancelled) | Yes | No | compute, store, default="new", tracking, group_expand, index |
| `user_approver_state` | Selection(new/pending/waiting/approved/refused/cancelled) | No | No | compute (context=uid) — mirrors the six `approval.approver` states |
| `has_access_to_request` | Boolean | No | No | compute (context=uid) |
| `is_pending_my_review` | Boolean | No | No | compute (context=uid), search (via `boolean_search_domain`). Delegation-aware "is this in my queue right now" — backs the review inbox |
| `can_change_request_owner` | Boolean | No | No | compute |
| `has_*` | Selection | No | No | 12 related fields from category (incl. deprecated `has_payment_method`; there is no `has_product` — see `approval_product`) |
| `approval_minimum` | Integer | Yes | No | default=1, readonly, copy=True. Effective minimum (an approver-replacing rule's override, or the category default) |
| `approve_sequentially` | Boolean | No | No | related |
| `group_approval` | Selection | No | No | related |
| `approver_group_id` | Many2one | No | No | related |
| `approval_type` | Selection | Yes | No | related, store |
| `target_model` | Selection | Yes | No | related, store |
| `approval_progress` | Float | No | No | compute |
| `pending_approver_ids` | Many2many(`res.users`) | No | No | compute |
| `approval_deadline` | Datetime | Yes | No | compute, store, index. Reads `approval_deadline_hours` from `category_snapshot` via `_get_snapshot_config` (live category fallback) |
| `is_overdue` | Boolean | No | No | compute, search |
| `hours_until_deadline` | Float | No | No | compute |
| `sla_status` | Selection(on_track/at_risk/breached/met/no_sla) | **No** | No | compute, search=`_search_sla_status` (SQL). Non-stored: value tracks the wall clock |
| `sla_elapsed_hours` | Float | No | No | compute |
| `sla_remaining_hours` | Float | No | No | compute |
| `can_withdraw` | Boolean | No | No | compute (context=uid) |
| `template_id` | Many2one(`approval.template`) | Yes | No | readonly, copy=False, index=btree_not_null |
| `applied_rule_ids` | Many2many(`approval.rule`) | Yes | No | readonly, copy=False (cleared by reset-to-draft) |
| `category_snapshot` | Json | Yes | No | readonly, copy=False (built at confirm; cleared by reset-to-draft) |
| `predicted_outcome` | Selection(approve/refuse/uncertain) | No | No | compute (batched, memoised per category+partner; historic amounts converted into the request's currency before matching) |
| `prediction_confidence` | Float | No | No | compute |
| `res_model` | Char | Yes | No | readonly, index |
| `res_id` | Many2oneReference | Yes | No | model_field=res_model, readonly |
| `res_model_id` | Many2one(`ir.model`) | Yes | No | compute, store |
| `res_name` | Char | No | No | compute (batched per model) |
| `attachment_ids` | One2many(`ir.attachment`) | Yes | No | domain=[res_model=approval.request] |
| `count_attachment` | Integer | No | No | compute |
| `automation_id` | Many2one | No | No | related |
| `automation_runtime_id` | Many2one(`automation.runtime`) | Yes | No | index=btree_not_null |

Removed in 19.0.1.0.7 (or earlier): `revision_count`, `cloned_from_id`,
`approver_compute_ms`, the quick-approve token/QR fields, the stored
`sla_status` column (migration drops it). Removed in 19.0.1.0.12:
`line_ids` and `has_product` — product lines are now `approval_product`.

### State Machine

```
new --(action_confirm)--> pending --> approved            (terminal)
                             |   \--> refused             (terminal)
                             \-----> cancelled            (terminal)

refused / cancelled --(action_reset_to_draft: owner or manager)--> new
approved            --(action_reset_to_draft: manager only)------> new
```

State is a **stored computed field** based on `approver_ids.state`
(`_compute_state`, priority order):
- No approvers => `new`
- Any approver `refused` => `refused`
- Any approver `cancelled` => `cancelled`
- Any approver `new` => `new`
- approved_count >= `approval_minimum` (NOT clamped to len(approvers)) AND all required approved => `approved`
- Otherwise => `pending`

`refused` outranks `cancelled` so a real decision is never masked.
`_TERMINAL_STATES = frozenset({"approved", "refused", "cancelled"})`
(class attribute in `approval_request_helper.py`). The source-document
notification is NOT fired from the compute; the transitioning action
calls `_notify_if_terminal_transition()` explicitly.

An approver's request-a-change keeps the state `pending` and sets
`pending_change_field`; approve/refuse/consent are blocked until the
requester re-submits (`action_resubmit`).

### Key Methods (across all split files)

| Method | File | Purpose |
|--------|------|---------|
| `create()` | request.py | Approval minimum from category, subscribe owner, sync approvers (no name assignment — deferred to confirm) |
| `write()` | request.py | Access check, forged-compute and locked-fields business rules, category-change guard, owner re-subscription, sync approvers when a field in `_get_approver_sync_trigger_fields()` is written |
| `copy_data()` / `copy()` | request.py | Duplicate with smart defaults from owner history (`_smart_clone_defaults`) + "Duplicated from" log |
| `unlink()` | request.py | Two-layer validation (access + business rules: draft only) |
| `_compute_display_name()` | compute.py | Translated "New" placeholder for unnumbered drafts |
| `_compute_state()` | compute.py | Core state machine (no side effects) |
| `_compute_sla_status()` / `_search_sla_status()` | compute.py | Non-stored SLA status + SQL search (CASE mirrors the compute) |
| `_compute_approval_deadline()` / `_get_snapshot_config()` | compute.py | Deadline from config frozen at confirm |
| `_compute_date_approval_granted/refused/cancelled()` | compute.py | Append-only terminal-date stamps (cleared on state=`new`) |
| `_compute_outcome_prediction()` | compute.py | Historical pattern-based prediction (batched) |
| `action_confirm()` | action.py | Draft only: validate, assign sequence name, snapshot, stamp date_confirmed, auto-rules, start workflow |
| `action_approve()` | action.py | Guard pending-change, then `_apply_decision("approve")` |
| `action_refuse()` | action.py | Header path opens decision wizard; inline path `_apply_decision("refuse")` |
| `_apply_decision()` | action.py | **Single decision funnel**: lock, cache refresh, delegation-aware resolution, state write, chatter, chain advance, activity cleanup, terminal notify, refusal rollback hook |
| `_get_current_pending_approver()` | action.py | Delegation-aware pending-approver resolution (single source for header/bulk/wizard) |
| `action_cancel()` | action.py | Owner/manager, pending only → `_force_terminal("cancelled")` |
| `action_reset_to_draft()` | action.py | any terminal state → new; clears decision metadata, date_confirmed, snapshot, escalation counters, applied rules; re-syncs approvers; keeps name. refused/cancelled: owner or manager. approved: **manager only** + `_check_withdraw_allowed()` (descendant-document guard) + notifies source document of the exit |
| `_check_owner_or_manager()` | action.py | Access layer (WHO) for owner-side lifecycle actions |
| `action_request_change()` / `action_resubmit()` | action.py | Request-a-change flow (set/clear `pending_change_field`) |
| `action_withdraw()` | action.py | Withdraw approval (approved row → pending; explicit exit-from-approved notification) |
| `_refuse_cascade()` | action.py | Parent-document cancellation → `_force_terminal("refused")` with `refusal_reason_parent_cancelled` |
| `action_approve_bulk()` / `action_refuse_bulk()` | action.py | Bulk decisions via `_action_bulk_decision` (delegation-aware, skip_wizard) |
| `action_view_to_review()` | action.py | Pending-review inbox, includes requests delegated TO the user |
| `_refuse_approval_request()` | action.py | No-op anchor for cooperative document rollback (account/purchase/sale override) |
| `_sync_approvers()` | helper.py | **Core engine**: reconcile approver rows from all sources (write step) |
| `_compute_desired_approvers()` | helper.py | Pure decision step of the sync (no writes, unit-testable) |
| `_force_terminal()` | helper.py | Non-decision termination funnel (cancel/expire/cascade); preserves terminal approver rows, stamps refusal metadata |
| `_notify_if_terminal_transition()` | helper.py | Fire source-doc hook once on entering a terminal state |
| `_lock_for_approval_action()` | helper.py | SELECT FOR UPDATE to prevent race conditions |
| `_update_next_approvers_state()` | helper.py | Sequential propagation; anchors on min (sequence,id) of the acting rows; never re-promotes terminal rows |
| `_check_auto_action_rules()` | helper.py | Auto-approve/refuse rules; auto-refuse stamps `refusal_reason_auto_rule` metadata |
| `_find_matching_replacement()` | helper.py | The first `set_approvers` rule this request falls into, by `(sequence, id)` (via prefetched `category_id.rule_ids`) |
| `_get_additional_approvers()` | helper.py | Extension hook + add_approver rule evaluation (via prefetched `rule_ids`) |
| `_get_escalation_rules()` | helper.py | `ESCALATION_RULES` defaults + `approval.escalation.<priority>.<kind>` ir.config_parameter overrides |
| `_get_escalation_manager()` | helper.py | Hook: manager to escalate to (base returns empty; approval_hr overrides) |
| `_build_category_snapshot()` | helper.py | Audit snapshot incl. `effective_*` keys and the matched replacing rule |
| `_notify_source_document_state_change()` | helper.py | Calls mixin hook on source doc (registry isinstance check) |
| `_check_access_write()` | validation.py | Owner OR assigned approver write access |
| `_check_locked_fields()` | validation.py | **Business rule, never bypassed**: value fields frozen outside draft; `pending_change_field` selectively reopens date/reason, and only for the requester (owner/manager/sudo) |
| `_check_no_forged_computed_fields()` | validation.py | Rejects direct writes to `_COMPUTE_ONLY_FIELDS` (`state`, the three terminal-date stamps, `approval_deadline`, `res_model_id`) in **every** state, draft included — these are workflow outputs, not inputs |
| `_check_access_approver_ids()` | validation.py | Per-command access validation |
| `_check_confirm()` | validation.py | Pre-confirm: approvers, documents (distinct-match), required fields |
| `_check_reset_allowed()` | validation.py | Hook: veto reset-to-draft (base blocks released source-doc links) |
| `cron_smart_escalation()` | cron.py | Priority-based reminder schedule (batched, limit 500/priority; skips requests with `pending_change_field` set; per-request savepoint) |
| `_reconcile_delegation_activities()` | cron.py | Runs first on every escalation tick: repoints an approval To-Do at the effective approver when a delegation was set (or lifted) after the round had already opened, closing the duplicate. Without it the activity stays in the principal's inbox for the life of the delegation |
| `cron_auto_expire()` | cron.py | **Cancel** (not refuse) requests past `auto_expire_hours` via `_force_terminal` |
| `cron_consent_approval()` | cron.py | Auto-approve after consent window; skips sequential categories, refused approvers, `pending_change_field`, `_can_consent_approve()` vetoes |

### Constraints

| Method | Rule |
|--------|------|
| `_check_date_consistency` | date_end > date_start |
| `_check_approver_ids` | No duplicate approvers per request (id-set based). Fires only when writing through `request.approver_ids`; the real guarantee is the `approval_approver_request_user_uniq` SQL constraint |
| `_check_category_access` | Owner must be allowed by category |
| `_check_category_change` | No category change after confirmation (form saves; direct writes guarded in `write()` via `_raise_category_change_blocked`) |

### Escalation Rules (constant `ESCALATION_RULES`, `approval_request.py`)

Defaults; each value overridable via ir.config_parameter
`approval.escalation.<priority>.<first_reminder|escalation>` (hours),
resolved by `_get_escalation_rules()`:

| Priority | First Reminder | Escalation |
|----------|---------------|------------|
| Urgent (3) | 4 hours | 8 hours |
| High (2) | 24 hours | 48 hours |
| Normal (1) | 48 hours | 96 hours |
| Low (0) | 72 hours | 168 hours |

---

## approval.approver

| Key | Value |
|-----|-------|
| Model | `approval.approver` |
| File | `models/approval_approver.py` |
| Type | Model |
| Order | `sequence, id` |
| Multi-company | Yes (`_check_company_auto`) |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `request_id` | Many2one(`approval.request`) | Yes | Yes | ondelete=cascade, check_company, index |
| `company_id` | Many2one(`res.company`) | Yes | No | related, store, index |
| `existing_request_user_ids` | Many2many(`res.users`) | No | No | compute |
| `user_id` | Many2one(`res.users`) | Yes | Yes | check_company, index |
| `sequence` | Integer | Yes | No | default=10 |
| `state` | Selection(new/pending/waiting/approved/refused/cancelled) | Yes | No | default="new", readonly, index |
| `required` | Boolean | Yes | No | default=False, readonly |
| `pending_since` | Datetime | Yes | No | readonly, copy=False, index=btree_not_null. Stamped by `_stamp_pending_since` (from `create`/`write`, so all five promotion paths are covered) when the row ENTERS `pending`; cleared by reset-to-draft. With `decision_date` it gives each approver's OWN turnaround instead of the request's age since `date_confirmed` |
| `source_synced` | Boolean | Yes | No | readonly, copy=False. Exact sync provenance since 19.0.1.0.13: set on every row `_sync_approvers` creates. A synced row whose source stopped producing it is DELETED on re-sync rather than kept as a phantom manual approver |
| `source_rule_id` | Many2one(`approval.rule`) | Yes | No | readonly, copy=False, index=btree_not_null. Which `add_approver` rule injected this row |
| `decision_date` | Datetime | Yes | No | readonly, copy=False, index. Stamped by `_apply_decision` on a GENUINE approve/refuse; cleared on withdraw/reset. NULL for non-decision flips. Drives the performance analytics |
| `decided_by_user_id` | Many2one(`res.users`) | Yes | No | readonly, copy=False, index. WHO exercised the slot (`user_id` is WHOSE it is) — the delegate inside an active delegation window. Stamped and cleared beside `decision_date`; both analytics consumers key on `COALESCE(decided_by_user_id, user_id)` |
| `can_edit` | Boolean | No | No | compute (context=uid) |
| `can_edit_user_id` | Boolean | No | No | compute (context=uid) |
| `delegate_id` | Many2one(`res.users`) | Yes | No | check_company, copy=False |
| `delegate_start_date` | Date | Yes | No | copy=False |
| `delegate_end_date` | Date | Yes | No | copy=False |
| `is_delegated` | Boolean | **No** | No | compute, search=`_search_is_delegated`, copy=False. Non-stored: "today" is resolved in the SLOT OWNER's timezone (`user_id.tz`, `@api.depends` includes it), not the server's. The compute buckets the recordset by tz (`_delegation_today_by_tz`); the search inverts that into one OR-branch per distinct `res.users.tz` value, built by `_delegation_date_buckets()` and memoised in `env.cr.cache` under `approval_delegation_tz_buckets` (dropped by `res.users.write` on a `tz` change) |
| `note` | Text | Yes | No | Decision note (approve/refuse context) |
| `refusal_reason_id` | Many2one(`approval.refusal.reason`) | Yes | No | |

### Key Methods

| Method | Purpose |
|--------|---------|
| `action_approve()` | 1-click approve — delegates to `request_id.action_approve(self)`, never opens the wizard |
| `action_refuse()` | Opens decision wizard (or direct refuse with skip_wizard context) |
| `_get_effective_approver()` | Returns delegate if delegation window active, else user_id |
| `_create_activity()` | Schedule mail activity for approver to-do, assigned to the **effective approver** (delegate when active); idempotent per effective-user+request |
| `_check_access_create/write/unlink()` | Access control layer. Write is field-scoped for non-managers: delegation fields by the original `user_id` only; decision-note fields (`refusal_reason_id`, `note`) by the effective approver; `state`/`sequence`/`required`/`request_id` are workflow-managed (manager/sudo only) |
| `_check_business_rules_create/unlink()` | Business rules layer: DRAFT only since 19.0.1.0.13 (relaxed only by `env.su` + `approver_ids_computation` sync context) — rows on decided requests are state-transition vehicles and are re-cycled via reset-to-draft |
| `_check_delegation_dates` (constraint) | Delegation requires both dates, end >= start |
| `_check_delegate_identity` (constraint) | Delegate must not be the approver themselves, the request owner, or a co-approver on the same request |

---

## mixin.approval.threshold (Abstract)

| Key | Value |
|-----|-------|
| Model | `mixin.approval.threshold` |
| File | `models/mixin_approval_threshold.py` |
| Type | AbstractModel |
| Inherited by | `approval.rule` |

The currency layer for every numeric threshold in the module. Both routing
models compare a request's `amount` against a configured number, and both
may live on a category shared across companies with different currencies —
so the comparison is never raw.

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `company_id` | Many2one(`res.company`) | Yes | No | default=env.company, index. **Empty means "applies to every company"** — that is how a shared category carries global rules (see `approval.request._rule_applies_to_company`) |
| `currency_id` | Many2one(`res.currency`) | Yes | **Yes** | default=env.company.currency_id. The currency the record's thresholds are expressed in |

### Key Methods

| Method | Purpose |
|--------|---------|
| `_convert_request_amount(request)` | Converts `request.amount` from `request.currency_id` into this record's `currency_id` before any threshold comparison. Rate date is `request.date` → `request.date_confirmed` → today; rate company is `request.company_id` → the record's → `env.company`. Identity short-circuit when the currencies match |
| `_intervals_overlap(bounds_a, bounds_b)` (static) | Half-open/closed-aware interval overlap, used by `approval.rule._check_replacement_overlap` and `_check_auto_action_conflict` |

---

## mixin.approval (Abstract)

| Key | Value |
|-----|-------|
| Model | `mixin.approval` |
| File | `models/mixin_approval.py` |
| Type | AbstractModel |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `approval_request_id` | Many2one(`approval.request`) | Yes | No | copy=False, readonly, index, tracking |
| `approval_state` | Selection | Yes | No | related, store (new/pending/approved/refused/cancelled) |
| `date_approval_granted` | Datetime | Yes | No | related, store, tracking |
| `approval_progress` | Float | No | No | related |
| `pending_approver_ids` | Many2many(`res.users`) | No | No | related |
| `date_approval_requested` | Datetime | Yes | No | related (=date_confirmed), store, tracking |
| `approval_user_ids` | Many2many(`res.users`) | No | No | related |
| `approval_required` | Boolean | No | No | compute (memoised per domain+company) |
| `can_request_approval` | Boolean | No | No | compute |

### Key Methods (Override Points)

| Method | Purpose |
|--------|---------|
| `action_create_approval_request()` | Create + submit approval request, link bidirectionally |
| `action_refuse_approval()` | Reverse cascade: parent cancelled → `_refuse_cascade()` on the linked request |
| `action_view_approval_request()` | Open the linked request form |
| `_clear_refused_approval_link()` | Release a refused/cancelled link so a reopened document can request a fresh approval |
| `_get_domain_approval_category()` | **Override**: domain to find category |
| `_get_approval_required_fields()` | **Override**: required fields before approval |
| `_get_approval_request_name()` | **Override**: customize request name |
| `_prepare_approval_request_values()` | **Override**: customize request creation values |
| `_on_approval_state_changed()` | **Dispatcher — do NOT override.** Routes to `_on_approval_approved` / `_on_approval_refused` / `_on_approval_cancelled` / `_on_approval_revoked` / `_on_approval_reset`. Base posts a chatter note per state; for the `pending` revocation it also schedules a To-Do for the responsible user on activity-enabled models. See conventions.md |
| `_get_approval_category()` | Find matching category (uses domain + company). Owns the whole selection algorithm; supply `_get_domain_approval_category()`, `approval.category._is_applicable_for()`, `_get_approval_category_fallback()` and the two `_raise_*` hooks instead of overriding it |
| `_approval_side_effect(failure_note)` | Context manager wrapping any document-advancing call made from a hook: savepoint + `UserError`/`ValidationError` catch + chatter note. Hooks run inside the approver's transaction — do not hand-roll this |
| `_approval_decider_names(state)` | The filter-and-join over `approver_ids` that opens a decision message |
| `write()` / `_get_approval_protected_fields()` | Freezes the listed source-document fields while an approval is in flight |
| `unlink()` | Blocks deleting a document with a live approval |
| `_check_can_request_approval()` / `_compute_can_request_approval()` | Gate on the "Request Approval" button |
| `_before_approval_request_submit(approval)` | Hook between request creation and auto-confirm |
| `_get_approval_submitted_action()` / `_get_approval_request_view_action()` | Client actions returned after submit / when opening the request |

### Submission Rate Limiting

`_approval_rate_limit_exceeded(*, hours, max_count, max_amount,
under_threshold_amount, excluded_states=("cancel",))` answers "has this
document's creator filed too many, or too much, in the last `hours`?" —
a satellite calls it from its own approval-required predicate
(approval_purchase, approval_sale).

It is **multi-currency by construction**: the caller's thresholds are
expressed in company currency, and the method converts
`under_threshold_amount` into each counterparty currency present in the
window before comparing, rather than summing mixed-currency totals. The
window is scoped to `(company_id, create_uid, create_date >= now - hours,
state not in excluded_states)` and excludes the record itself. Rate date
comes from `_approval_rate_limit_rate_date()` (override to pin it).
Covered by `tests/test_rate_limit.py`.

---

## approval.refusal.reason

| Key | Value |
|-----|-------|
| Model | `approval.refusal.reason` |
| File | `models/approval_refusal_reason.py` |
| Type | Model |
| Inherits | `mixin.catalog` (`name` required+translate, `active`); `_name_src_uniq` rescoped to `company_id` |
| Order | `sequence, name` |
| Multi-company | Yes (`_check_company_auto`) |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `company_id` | Many2one(`res.company`) | Yes | No | default=False, index |
| `name` | Char | Yes | Yes | translate |
| `active` | Boolean | Yes | No | default=True |
| `sequence` | Integer | Yes | No | default=10 |
| `description` | Text | Yes | No | translate |
| `category_ids` | Many2many(`approval.category`) | Yes | No | check_company |
| `usage_count` | Integer | No | No | compute |

System reasons shipped in data: `refusal_reason_parent_cancelled` (cascade
refusals), `refusal_reason_auto_rule` (auto-refuse rules),
`refusal_reason_data_migration`.

---

## approval.rule

| Key | Value |
|-----|-------|
| Model | `approval.rule` |
| File | `models/approval_rule.py` |
| Type | Model |
| Inherits | `mixin.approval.threshold` (supplies `company_id` + `currency_id`) |
| Order | `category_id, sequence, id` |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `name` | Char | Yes | Yes | |
| `active` | Boolean | Yes | No | default=True |
| `sequence` | Integer | Yes | No | default=10 |
| `company_id` | Many2one(`res.company`) | Yes | No | from `mixin.approval.threshold`; empty = every company |
| `currency_id` | Many2one(`res.currency`) | Yes | **Yes** | from `mixin.approval.threshold`; `threshold` is expressed in it |
| `category_id` | Many2one(`approval.category`) | Yes | Yes | ondelete=cascade, index |
| `condition_field` | Selection(amount/quantity/date_range_days/priority) | Yes | Yes | |
| `operator` | Selection(gt/gte/lt/lte/eq/neq) | Yes | Yes | |
| `threshold` | Float | Yes | Yes | |
| `action_type` | Selection(add_approver/auto_approve/auto_refuse) | Yes | Yes | default="add_approver" |
| `approver_ids` | Many2many(`res.users`) | Yes | No | |
| `approver_required` | Boolean | Yes | No | default=True |
| `approver_sequence` | Integer | Yes | No | default=5 |

### Constraints

- `_name_category_uniq`: unique nulls not distinct (name, category_id, company_id)

### Key Methods

| Method | Purpose |
|--------|---------|
| `_evaluate(request)` | Check if condition matches request |
| `_get_field_value(request)` | Extract numeric value using match/case; `amount` goes through `_convert_request_amount()` so the comparison happens in the rule's currency |
| `_compare(value, threshold)` | Apply operator |
| `_get_approver_tuples()` | Return (user_id, required, sequence) list |

---

## approval.template

| Key | Value |
|-----|-------|
| Model | `approval.template` |
| File | `models/approval_template.py` |
| Type | Model |
| Inherits | `mixin.catalog` (`name` required+translate, `active`); `_name_src_uniq` rescoped to `company_id` |
| Order | `sequence, name` |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `name` | Char | Yes | Yes | translate |
| `active` | Boolean | Yes | No | default=True |
| `sequence` | Integer | Yes | No | default=10 |
| `description` | Text | Yes | No | translate |
| `category_id` | Many2one(`approval.category`) | Yes | Yes | ondelete=cascade, index |
| `company_id` | Many2one(`res.company`) | Yes | No | default=env.company, index |
| `default_reason` | Html | Yes | No | translate |
| `default_amount` | Float | Yes | No | |
| `default_quantity` | Float | Yes | No | |
| `default_location` | Char | Yes | No | |
| `default_partner_id` | Many2one(`res.partner`) | Yes | No | |
| `default_reference` | Char | Yes | No | |
| `default_priority` | Selection(0-3) | Yes | No | default="1" |
| `has_*` | Selection | No | No | 5 related fields from category |
| `usage_count` | Integer | No | No | compute |

### Key Methods

| Method | Purpose |
|--------|---------|
| `action_create_request()` | Open form with template defaults in context |
| `action_view_requests()` | View requests from this template |

---

## Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `name` | Char | Yes | Yes | |
| `active` | Boolean | Yes | No | default=True |
| `category_id` | Many2one(`approval.category`) | Yes | Yes | ondelete=cascade, index |
| `company_id` | Many2one(`res.company`) | Yes | No | from `mixin.approval.threshold`; empty = every company |
| `currency_id` | Many2one(`res.currency`) | Yes | **Yes** | from `mixin.approval.threshold`; `threshold_min`/`threshold_max` are expressed in it |
| `threshold_field` | Selection(amount/quantity) | Yes | Yes | default="amount" |
| `threshold_min` | Float | Yes | Yes | |
| `threshold_max` | Float | Yes | No | default=0 (0=unlimited) |
| `approver_ids` | Many2many(`res.users`) | Yes | Yes | |
| `approver_required` | Boolean | Yes | No | default=True |
| `approval_minimum` | Integer | Yes | No | default=1 |

### Constraints

- `_name_category_uniq`: unique(name, category_id)
- `_check_thresholds`: max > min (or max=0)
- `_check_no_overlap`: No overlapping ranges per category+field

### Key Methods

| Method | Purpose |
|--------|---------|
| `_matches(value)` | Check if value in [min, max) — takes the output of `_get_threshold_value`, never a raw `request.amount` |
| `_overlaps(other)` | Check range overlap (delegates to `_intervals_overlap`) |

---

## approval.document.requirement

| Key | Value |
|-----|-------|
| Model | `approval.document.requirement` |
| File | `models/approval_document_requirement.py` |
| Type | Model |
| Order | `category_id, sequence` |

### Fields

| Field | Type | Stored | Required | Key Attributes |
|-------|------|--------|----------|----------------|
| `name` | Char | Yes | Yes | |
| `category_id` | Many2one(`approval.category`) | Yes | Yes | ondelete=cascade, index |
| `sequence` | Integer | Yes | No | default=10 |
| `required` | Boolean | Yes | No | default=True |
| `description` | Text | Yes | No | |

### Constraints

- `_name_src_uniq`: `name_uniq_index("category_id", nulls_distinct=True)` — UNIQUE over the `en_US` source term, not the jsonb document

`_check_name_unique_per_language` is **gone** (19.0.1.0.23), along with
`_name_variants`. It existed because the confirm-time check matched
attachments by NAME, so two requirements sharing a name in any installed
translation made the matching ambiguous. The link is structural now —
`ir.attachment.approval_requirement_id`, set by the requester — so the name
is a label and two requirements may share a translation freely.

---

## approval.test.document (Test-Only)

| Key | Value |
|-----|-------|
| Model | `approval.test.document` |
| File | `models/approval_test_document.py` |
| Type | Model |
| Inherits | `mixin.mail.thread`, `mixin.approval` |

### Fields

| Field | Type | Key Attributes |
|-------|------|----------------|
| `name` | Char | required, tracking |
| `description` | Text | |
| `amount` | Float | tracking |
| `partner_id` | Many2one(`res.partner`) | tracking |
| `state` | Selection(draft/confirmed/approved/rejected) | default="draft", tracking |
| `company_id` | Many2one(`res.company`) | default=env.company |
| `hook_call_count` | Integer | default=0 |
| `last_approval_state` | Char | |
| `test_category_id` | Many2one(`approval.category`) | |

---

## approval.decision.wizard (Transient)

| Key | Value |
|-----|-------|
| Model | `approval.decision.wizard` |
| File | `wizard/approval_decision_wizard.py` |
| Type | TransientModel |

Captures the approver's input when **refusing** or **requesting a change**.
Approving is a 1-click action that never opens this wizard.

### Fields

| Field | Type | Key Attributes |
|-------|------|----------------|
| `approver_id` | Many2one(`approval.approver`) | required, readonly |
| `request_id` | Many2one(`approval.request`) | compute from approver_id, precompute, store, readonly, required |
| `user_id` | Many2one(`res.users`) | related |
| `decision_type` | Selection(refuse/change) | required, readonly |
| `refusal_reason_id` | Many2one(`approval.refusal.reason`) | required for refuse (validated in action) |
| `refusal_reason_description` | Text | related (read-only guidance banner) |
| `change_field` | Selection(date/reason) | field the requester must update |
| `note` | Text | optional on refuse; required on change |
| `request_name` | Char | related |
| `request_owner_id` | Many2one | related |
| `category_id` | Many2one | related |

### Key Methods

| Method | Purpose |
|--------|---------|
| `_check_decision_allowed()` | Approver still pending + current user is the effective approver (delegation-aware) |
| `action_confirm_refuse()` | Require reason; persist reason+note on approver row AND request (canonical `refusal_reason_id`/`refusal_note`); then inline `action_refuse` |
| `action_confirm_change()` | Require field+note; set `pending_change_field` via `action_request_change`; schedule change-request To-Do for the requester |
| `action_cancel()` | Close the wizard (no decision) |

---

## approval.delegate.wizard (Transient)

| Key | Value |
|-----|-------|
| Model | `approval.delegate.wizard` |
| File | `wizard/approval_delegate_wizard.py` |
| Type | TransientModel |

### Fields

| Field | Type | Key Attributes |
|-------|------|----------------|
| `user_id` | Many2one(`res.users`) | required, readonly, default=env.user |
| `delegate_id` | Many2one(`res.users`) | required |
| `start_date` | Date | required, default=today |
| `end_date` | Date | required |
| `apply_to` | Selection(pending/all_future) | required, default="pending" |
| `allowed_company_ids` | Many2many(`res.company`) | default=`env.companies`. The wizard's own copy of the active company set, so `delegate_id`'s domain can reference it. `approval.approver.delegate_id` is `check_company=True` and would reject a foreign delegate anyway — this leaf turns that into a filtered dropdown instead of a raw constraint error |
| `pending_count` | Integer | compute |
| `waiting_count` | Integer | compute |

### Key Methods

| Method | Purpose |
|--------|---------|
| `action_confirm()` | Apply delegation to matching approvers, notify delegate |

---

## approval.metrics (SQL View)

| Key | Value |
|-----|-------|
| Model | `approval.metrics` |
| File | `report/approval_metrics.py` |
| Type | Model, `_auto = False`, `_inherit = "mixin.sql.report"` |
| Order | `category_id, avg_approval_hours` |

The model does **not** write `_table_query` itself. `mixin.sql.report`
(`odoo/addons/base_sql_report`) owns `_table_query` / `_build_table_query`
and assembles the statement from four overrides this model supplies:
`_get_select_fields()`, `_get_from_tables()`, `_get_where_conditions()`,
`_get_group_by_fields()`. Add a field here and you must add its SELECT
entry there — nothing links them automatically.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `category_id` | Many2one(`approval.category`) | Grouped by category |
| `company_id` | Many2one(`res.company`) | Grouped by company |
| `total_requests` | Integer | Total submitted |
| `approved_count` | Integer | state = approved |
| `rejected_count` | Integer | state = refused |
| `pending_count` | Integer | state = pending |
| `cancelled_count` | Integer | state = cancelled (labelled "Cancelled", not "Refused") |
| `approval_rate` | Float | Approved / DECIDED (%). Denominator is `approval.request._DECISION_STATES` (approved + refused) — a cancelled request was retracted or expired, so nobody decided it. Counting cancellations made a category with 4 approvals, 4 retractions and zero refusals report 50%. |
| `avg_approval_hours` | Float | AVG(approved - confirmed) in hours |
| `median_approval_hours` | Float | PERCENTILE_CONT(0.5) in hours |
| `sla_target_hours` | Float | From category config (`sla_target_hours`) |
| `sla_compliant_count` | Integer | Approved within SLA |
| `sla_compliance_rate` | Float | Compliant / approved (%) |

---

## approver.performance (SQL View)

| Key | Value |
|-----|-------|
| Model | `approver.performance` |
| File | `report/approver_performance.py` |
| Type | Model, `_auto = False`, `_inherit = "mixin.sql.report"` (same four overrides as `approval.metrics`) |
| Order | `avg_response_hours` |

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | Many2one(`res.users`) | Grouped by the deciding actor: `COALESCE(decided_by_user_id, user_id)` |
| `company_id` | Many2one(`res.company`) | Grouped by company |
| `total_approvals` | Integer | GENUINE decisions (approver rows with `decision_date` set) |
| `approved_count` | Integer | Approvals with `decision_date` set |
| `refused_count` | Integer | Refusals with `decision_date` set (cascade/consent flips excluded) |
| `pending_count` | Integer | Currently pending |
| `avg_response_hours` | Float | `AVG(a.decision_date − COALESCE(a.pending_since, ar.date_confirmed))` in hours — the clock starts when the ROW entered `pending`, so a sequential approver is not billed for the queue ahead of them. `date_confirmed` is only the fallback for rows predating `pending_since` |
| `approval_rate` | Float | Approved / decided (%), genuine decisions only |

> The view keys on `approval.approver.decision_date` (stamped only in
> `_apply_decision`). Rows flipped to refused/cancelled by a sequential/
> cascade close-out, consent auto-approval, or expiration have no
> `decision_date` and are excluded — so an approver's rate is not tanked
> by refusals they never made, and response time is per-approver
> (2026-07-03 audit, majors #6 & #8).
>
> Rows are attributed to whoever ACTUALLY decided, not to the slot owner.
> Under delegation those differ, and grouping on `user_id` alone credited
> the delegated decision, and its response time, to the absent principal
> while the delegate who did the work scored nothing (measured 16.0h on
> the principal, 0.0h on the delegate; 2026-08-11 audit). `pending_count`
> deliberately still follows the assignee through the COALESCE fallback:
> an undecided row has no actor, and "how much is queued on this person"
> is a property of the slot. `approval.dashboard.my_avg_response_hours`
> matches on the same expression.

---

## approval.dashboard (Singleton)

| Key | Value |
|-----|-------|
| Model | `approval.dashboard` |
| File | `report/approval_dashboard.py` |
| Type | Model |

### Fields

`name` is the only stored column (the singleton's label); everything below
is computed and non-stored, recalculated per read.

| Group | Fields |
|-------|--------|
| Today | `pending_today`, `approved_today`, `refused_today`, `submitted_today`, `avg_response_time_hours` |
| Meta | `last_refresh` |
| Trends | `trend_7days`, `trend_15days`, `trend_30days`, `trend_*_display` |
| Bottlenecks | `slowest_category_id`, `slowest_category_hours`, `slowest_approver_id`, `slowest_approver_hours`, `most_pending_approver_id`, `most_pending_count` |
| All-time | `total_requests_all_time`, `total_pending_all_time`, `overall_approval_rate`, `avg_approval_time_all_time` |
| User | `my_pending_count`, `my_pending_urgent_count`, `my_avg_response_hours` |
| Velocity | `requests_per_day_7d/15d/30d`, `approvals_per_day_7d/15d/30d`, `avg_response_hours_7d/15d/30d`, `median_approval_hours` |

### Key Methods

| Method | Purpose |
|--------|---------|
| `get_dashboard()` | Singleton pattern: search or create |
| `action_refresh()` | Invalidate cache + reload |
| `_calculate_avg_response_time_sql()` | Efficient SQL AVG calculation |

---

## Extended Models

### ir.attachment (extended)

| File | `models/ir_attachment.py` |
|------|--------------------------|
| Hook | `_unlink_approved_approval_request()` via `@api.ondelete` |
| Rule | Blocks deletion of attachments on finalized requests |

### mail.activity (extended)

| File | `models/mail_activity.py` |
|------|--------------------------|
| Fields | `approval_request_id` (compute+search), `approver_id` (compute) |
| Method | `_to_store_defaults()` adds approver state to Store |

### mail.activity.type (extended)

| File | `models/mail_activity_type.py` |
|------|-------------------------------|
| Method | `_get_model_info_by_xmlid()` registers approval activity type |

### res.groups (extended)

| File | `models/res_groups.py` |
|------|------------------------|
| Method | `write()` — when `user_ids`, `implied_ids` or `all_user_ids` move, calls `approval.request._invalidate_escalation_manager_cache()` |
| Why | The default escalation manager is memoised per (transaction, company) by group membership. Membership can change from the GROUP side, which no `res.users` hook sees, and the memo would then hand escalations to someone who no longer holds the privilege |

### res.users (extended)

| File | `models/res_users.py` |
|------|-----------------------|
| Methods | `_is_approval_manager()` — the manager seam every access check goes through (`approval_utils.is_approval_manager`); `write()` — drops the delegation tz-bucket memo on a `tz` change, the escalation-manager memo on `group_ids`/`active`, and triggers the archive handover; `_approval_handover_on_archive()` — SM-7, reassigns the archived user's live `pending`/`waiting` rows (see architecture.md, *Departure Handover*) |
