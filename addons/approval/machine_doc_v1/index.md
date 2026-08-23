# Approval Module -- Machine Documentation v1

## Purpose

Multi-level approval workflow engine: configurable categories, sequential/parallel
approval chains, banded routing by amount/quantity, conditional rules, delegation,
consent-based auto-approval, SLA tracking, smart escalation with priority-based
reminders, approver-requested mid-flow changes, cancel / reset-to-draft recovery,
approval mixin for source document integration, and comprehensive analytics
dashboards.

## Module Metadata

| Key | Value |
|-----|-------|
| Technical name | `approval` |
| Version | 19.0.1.0.25 (matches `__manifest__.py`) |
| Category | Human Resources/Approvals |
| Dependencies | `base_automation`, `base_sql_report`, `mail` |
| Conflicts | `approvals` (upstream module — the two cannot coexist, and NOTHING enforces it: this fork's loader reads no `excludes` manifest key, so the one that used to sit here was inert) |
| Application | Yes |
| License | LGPL-3 |
| Python models | 11 own + 5 extensions, across 22 files in `models/`, + 2 wizards + 3 report models |
| Views | 16 XML files (10 `views/` + 4 `report/` + 2 `wizard/`) |
| Wizards | 2 transient models |
| Reports | 4 (2 SQL views + 1 singleton dashboard + 1 QWeb PDF) |
| Cron jobs | 3 (escalation, auto-expire, consent) |
| Test files | 30 (+ `common.py` shared fixtures) |
| JS files | 16 (7 src + 9 tests) |
| Migrations | 18 script directories between 19.0.1.0.1 and .24. The missing numbers (.9, .15, .16, .18, .19, .20) **were** released — the manifest bumped through them; they simply needed no script |

## File Inventory

### Models (`models/`)

| File | Models | Purpose |
|------|--------|---------|
| `approval_category.py` | `approval.category` | Category blueprint: field visibility, privacy visibility, approval minimums, escalation, SLA, consent, dashboard |
| `approval_category_approver.py` | `approval.category.approver` | M2M with attrs between category and users (required, sequence) |
| `approval_request.py` | `approval.request` | Core request: fields, CRUD, smart-copy defaults, `ESCALATION_RULES` constant |
| `approval_request_compute.py` | extends `approval.request` | All compute methods (state, SLA, deadline, prediction, terminal-date stamps) |
| `approval_request_action.py` | extends `approval.request` | Search, onchange, actions (approve/refuse/confirm/cancel/reset-to-draft/withdraw/request-change/bulk) |
| `approval_request_validation.py` | extends `approval.request` | Access control + business rule validation (write/unlink/confirm/locked-fields/reset checks) |
| `approval_request_helper.py` | extends `approval.request` | Private helpers (`_sync_approvers`, `_force_terminal`, `_TERMINAL_STATES`, locking, notifications, escalation config) |
| `approval_request_cron.py` | extends `approval.request` | Cron: smart_escalation, auto_expire, consent_approval |
| `approval_approver.py` | `approval.approver` | Individual approver: state, delegation, CRUD access control |
| `mixin_approval.py` | `mixin.approval` (Abstract) | Mixin for source documents (PO, SO, etc.) to integrate with approvals |
| `mixin_approval_threshold.py` | `mixin.approval.threshold` (Abstract) | Base of `approval.rule`: `company_id` + `currency_id`, `_convert_request_amount()` (a request's amount is converted into the record's currency before any comparison) and `_intervals_overlap()` |
| `approval_refusal_reason.py` | `approval.refusal.reason` | Predefined refusal reasons with usage tracking |
| `approval_rule.py` | `approval.rule` | Conditional rules on amount / quantity / date range / priority: add approvers, REPLACE approvers (the former `approval.tier`, as `operator = between` + `action_type = set_approvers`), auto-approve, auto-refuse |
| `approval_template.py` | `approval.template` | Request templates with smart defaults |
| `approval_document_requirement.py` | `approval.document.requirement` | Required document types per category. A LABEL model since 19.0.1.0.23: the confirm-time check reads `ir.attachment.approval_requirement_id`, not the file name |
| `approval_test_document.py` | `approval.test.document` | Test-only model implementing mixin.approval |
| `approval_utils.py` | — (no model) | Module-level helpers shared across the split files: `is_approval_manager(env)` and `boolean_search_domain()` (the `search=` builder behind `is_overdue`, `is_delegated`, `is_pending_my_review`) |
| `ir_attachment.py` | extends `ir.attachment` | `approval_requirement_id` — which required document a file IS — and blocks deletion of attachments on finalized requests |
| `mail_activity.py` | extends `mail.activity` | Adds approval_request_id and approver_id computed fields |
| `mail_activity_type.py` | extends `mail.activity.type` | Registers approval activity type metadata |
| `res_groups.py` | extends `res.groups` | Drops the escalation-manager memo when group membership moves from the GROUP side |
| `res_users.py` | extends `res.users` | `_is_approval_manager` seam, archive handover (SM-7), memo invalidation |

### Wizards (`wizard/`)

| File | Model | Purpose |
|------|-------|---------|
| `approval_decision_wizard.py` | `approval.decision.wizard` | Refuse (structured reason + note) or request a change (field + required note). Approving is 1-click and never opens the wizard |
| `approval_delegate_wizard.py` | `approval.delegate.wizard` | Delegate pending approvals to another user for a date range |

### Reports (`report/`)

| File | Model | Type | Purpose |
|------|-------|------|---------|
| `approval_metrics.py` | `approval.metrics` | SQL View (`mixin.sql.report`) | Aggregated stats: approval rate, avg/median time, SLA compliance, cancelled count |
| `approver_performance.py` | `approver.performance` | SQL View (`mixin.sql.report`) | Per-approver: response time, approval rate, workload |
| `approval_dashboard.py` | `approval.dashboard` | Singleton | Real-time KPIs: today, trends, bottlenecks, velocity, user metrics |
| `approval_request_report.xml` | — | QWeb PDF | `action_report_approval_request` — printable request sheet, bound to `approval.request` as a report action. The template lives in `views/approval_request_template.xml`; the form's Print button gates on `state == "approved"` only (see `test_print_button.py`) |

### Tests (`tests/`)

| File | Coverage Area |
|------|---------------|
| `common.py` | `ApprovalCommon` base class (shared users/category/request fixtures) + product helpers |
| `test_approvals.py` | Core approval lifecycle, state transitions (`TestRequest`) |
| `test_approver_computation.py` | _sync_approvers, category changes, band matching |
| `test_sequential_approval.py` | Sequential workflow, ordering, locking |
| `test_group_approval.py` | Approver source modes (no = Specific Users / exclusive = Security Group) |
| `test_delegation.py` | Delegation lifecycle, effective approver |
| `test_decision_wizard.py` | Wizard refuse / request-change with reasons and notes |
| `test_bulk_operations.py` | Bulk approve/refuse from list view |
| `test_security.py` | Access control: write, unlink, approver CRUD, record-rule visibility |
| `test_deadline_escalation.py` | Smart escalation cron, priority-based reminders |
| `test_auto_expire.py` | Auto-cancel expired pending requests |
| `test_consent_approval.py` | Consent-based auto-approval after timeout |
| `test_auto_action_rules.py` | Auto-approve/auto-refuse conditional rules |
| `test_conditional_rules.py` | Rule evaluation, approver injection, live re-routing of a submitted request (`TestLiveRerouting`), routing-input lifecycle (`TestRoutingFieldLifecycle`) |
| `test_approver_replacement.py` | Approver-replacing rules: band matching, overlap validation, minimum override, batched constraints |
| `test_document_requirements.py` | Required document validation on confirm, through the structural attachment link |
| `test_sla_tracking.py` | SLA status computation, compliance tracking |
| `test_lifecycle.py` | Cancelled state, reset-to-draft, forced-terminal paths, locked fields, delegation fan-in (19.0.1.0.7) |
| `test_request_change.py` | Approver-requested mid-flow edit (`pending_change_field`), and re-routing at re-submit (`TestRequestChangeReroutes`) |
| `test_approval_mixin.py` | Mixin integration with test document model |
| `test_rate_limit.py` | `_approval_rate_limit_exceeded()` across currencies (the multi-currency conversion in the submission throttle) |
| `test_print_button.py` | Print-button visibility on the request form arch |
| `test_dashboard.py` | Dashboard singleton, KPIs, bottleneck detection |
| `test_analytics_accuracy.py` | SQL view accuracy, metric calculations |
| `test_insights_perf_snapshot.py` | Outcome prediction, category snapshots (+ batched-query regression) |
| `test_audit_2_security_state.py` | Second-round security/state audit regressions |
| `test_audit_3_attribution_cleanup.py` | Third-round audit: decision attribution under delegation, decision-funnel scoping, change-request close-out, manual-approver preservation, escalation lookup, document-requirement language, batched round-opening |
| `test_audit_4_invariants.py` | Fourth-round audit: invariants that must hold across the whole lifecycle (pending-review predicate, decision funnels) |
| `test_multi_company.py` | Multi-company isolation across every company_id-scoped model |
| `test_fixes.py` | Attachment unlink protection, mail-activity search operators, category-approver falsy checks |
| `test_ui.py` | Tour-based UI tests |

Former `test_audit_regressions.py` and `test_audit_round3_regressions.py`
(incident-named regression dumps, C1..M9 / A3-1..A3-19) were fully
dissolved: every test was relocated into its feature-area file above
(e.g. band regressions into `test_approver_replacement.py`, delegation
regressions into `test_delegation.py`) so a maintainer editing a model
finds ALL of its tests in one place instead of archaeology across
incident files. `test_fix_coverage.py` was dissolved the same way
(escalation-hook tests into `test_deadline_escalation.py`, the
action-locking test into `test_lifecycle.py`, activity-idempotency
into `test_approvals.py`).

### Data (`data/`)

| File | Content |
|------|---------|
| `ir_config_parameter_data.xml` | Sequence defaults for approver ordering: `approval.sequence.` `manager` 9, `tier` 10 (the approver-replacing rules — the key keeps its old name), `group` 500, `manual` 1000. There is **no** `approval.sequence.category` — category approvers carry the sequence entered on the category form |
| `approval_category_data.xml` | Default approval categories (General, Business Trip, etc.) |
| `mail_activity_type_data.xml` | 2 activity types: approval + change request |
| `mail_message_subtype_data.xml` | Approval state change subtype |
| `ir_cron_data.xml` | 3 scheduled actions |
| `approval_refusal_reason_data.xml` | 12 refusal reasons, incl. system reasons `refusal_reason_parent_cancelled`, `refusal_reason_auto_rule`, `refusal_reason_data_migration` |

### Static (`static/src/`)

| File | Purpose |
|------|---------|
| `common/activity_model_patch.js` | Activity model patch for approval data |
| `common/approver_model.js` | Approver OWL model |
| `web/activity_patch.js` | Activity component patch for approve/refuse buttons |
| `web/activity_list_popover_item_patch.js` | Activity popover patch |
| `web/approval.js` | Approval form component |
| `views/kanban/approvals_category_kanban_controller.js` | Category kanban controller |
| `views/kanban/approvals_category_kanban_view.js` | Category kanban view registration |
| `scss/approval.scss` + `approval.dark.scss` | Approval styles |
| `scss/approval_dashboard.scss` + `approval_dashboard.dark.scss` | Dashboard styles |

### Security (`security/`)

| File | Content |
|------|---------|
| `res_groups.xml` | 2 groups — `group_approval_approver`, `group_approval_manager` — under one `res.groups.privilege` (`res_groups_privilege_approvals`) |
| `ir_rule.xml` | Record rules: multi-company, ownership, per-category `privacy_visibility` read audiences |
| `ir.model.access.csv` | ACL for every shipped model except `approval.test.document`, which has none — the test model is reached through sudo or a manager |

## Directory Structure

```
approval/
+-- __manifest__.py
+-- __init__.py
+-- models/
|   +-- approval_category.py          # Category blueprint
|   +-- approval_category_approver.py # Category-approver M2M
|   +-- approval_request.py           # Core fields + CRUD + smart copy
|   +-- approval_request_compute.py   # Compute methods (split file)
|   +-- approval_request_action.py    # Actions (split file)
|   +-- approval_request_validation.py# Access control (split file)
|   +-- approval_request_helper.py    # Helpers (split file)
|   +-- approval_request_cron.py      # Cron jobs (split file)
|   +-- approval_approver.py          # Approver records
|   +-- mixin_approval.py             # Source document mixin
|   +-- mixin_approval_threshold.py   # Currency-aware threshold base
|   +-- approval_refusal_reason.py    # Refusal reasons
|   +-- approval_rule.py              # Conditional rules
|   +-- approval_template.py          # Request templates
|   +-- approval_document_requirement.py # Required documents
|   +-- approval_test_document.py     # Test-only mixin consumer
|   +-- approval_utils.py             # Module-level helpers (no model)
|   +-- ir_attachment.py              # Attachment protection
|   +-- mail_activity.py              # Activity extensions
|   +-- mail_activity_type.py         # Activity type metadata
|   +-- res_groups.py                 # Escalation-memo invalidation
|   +-- res_users.py                  # Manager seam + archive handover
+-- wizard/
|   +-- approval_decision_wizard.py   # Refuse / request-change
|   +-- approval_delegate_wizard.py   # Delegation setup
+-- report/
|   +-- approval_metrics.py           # SQL view: category stats
|   +-- approver_performance.py       # SQL view: approver stats
|   +-- approval_dashboard.py         # Singleton: real-time KPIs
|   +-- approval_request_report.xml   # QWeb PDF report action
+-- migrations/                       # 18 script directories (19.0.1.0.1 .. .24)
+-- tests/                            # 30 test modules + common.py
+-- views/                            # 11 XML view files
+-- data/                             # 6 XML data files
+-- demo/                             # 3 XML demo files
+-- security/                         # Groups, rules, ACL
+-- static/                           # JS, SCSS, images
```

## Key Statistics

| Metric | Count |
|--------|-------|
| Python files (non-test, incl. `__init__`/`__manifest__`) | 32 |
| Python test files | 30 (+ `common.py`) |
| XML files (non-static) | 27 |
| XML files (static templates) | 4 |
| JS files | 16 |
| SCSS files | 4 |
| ORM models (new) | 11 in `models/` + 2 wizards + 3 report models |
| ORM models (extended) | 5 (ir.attachment, mail.activity, mail.activity.type, res.groups, res.users) |
| Abstract models | 2 (mixin.approval, mixin.approval.threshold) |
| SQL view models | 2 |
| Transient models | 2 |
| Test-only models | 1 |
| Cron jobs | 3 |
| Migration script directories | 18 |

Re-measure rather than trusting these: `find . -name '*.py' -not -path './tests/*'
-not -path './migrations/*' -not -path '*__pycache__*' -not -path './machine_doc_v1/*'
| wc -l`, `ls tests/test_*.py | wc -l`, `ls migrations | wc -l`.

## Reading Order

1. **models.md** -- All models, fields, relationships, state machines
2. `approval_category.py` -- Category blueprint (understand config first)
3. `approval_request.py` -- Core fields and CRUD
4. `approval_request_compute.py` -- State machine (`_compute_state`)
5. `approval_request_helper.py` -- `_sync_approvers` / `_force_terminal` (workflow engine)
6. `approval_approver.py` -- Approver lifecycle and access control
7. `approval_request_action.py` -- User-facing actions (`_apply_decision` funnel)
8. `approval_request_validation.py` -- Security layer + locked fields
9. `approval_rule.py` -- Dynamic routing: adding, replacing, auto-deciding
10. `mixin_approval.py` -- Source document integration pattern

## Architecture Notes

### Split Model Pattern
`approval.request` is split across 6 files using `_inherit = "approval.request"`:
- `approval_request.py` -- Fields, CRUD, smart-copy defaults
- `approval_request_compute.py` -- Compute methods
- `approval_request_action.py` -- Actions and search
- `approval_request_validation.py` -- Access control + business rules
- `approval_request_helper.py` -- Private helpers
- `approval_request_cron.py` -- Scheduled actions

### State Machine (since 19.0.1.0.7)
Request states: `new`, `pending`, `approved`, `refused`, `cancelled`.
`_TERMINAL_STATES = frozenset({"approved", "refused", "cancelled"})` (helper file).
`refused` = an approver said no; `cancelled` = retracted/expired, nobody decided.
That difference is a reporting contract, not just prose: the sibling
`_DECISION_STATES = frozenset({"approved", "refused"})` is what every
approval-RATE denominator divides by (`approval.metrics.approval_rate`,
`approval.dashboard.overall_approval_rate`, `_compute_outcome_prediction`),
so a retraction never counts as a vote against a request.
All three terminals are recoverable via `action_reset_to_draft()` — the two
failure terminals by the owner or a manager, and `approved` by a manager only
(a guarded override for when the deciding approver is no longer available).
The former `revision`/`cancel` states are gone; mid-flow edits go through the
request-a-change flow (`pending_change_field`) which keeps the request `pending`.

### Decision Funnels
- Approver decisions (`action_approve`/`action_refuse`) funnel through
  `_apply_decision()` -- one shared sequence for lock, cache refresh,
  delegation-aware approver resolution, state write, chatter audit,
  chain advancement, activity cleanup and terminal notification.
- Non-decision terminations (owner cancel, auto-expire, parent cascade,
  auto-refuse rules use their own write path) funnel through
  `_force_terminal()`, which flips only NON-terminal approver rows and
  stamps refusal metadata.

### Approver Sync Engine
`_sync_approvers()` in `approval_request_helper.py` is the central approver
computation method. It is NOT a computed field (creates/updates related records).
Called from `create()`, `write()` (whenever a field in
`_get_approver_sync_trigger_fields()` is written — `category_id`,
`request_owner_id` and every routing input the rules declare),
`action_confirm()` and `action_reset_to_draft()`. The confirm-time call is
what makes the CATEGORY's current configuration authoritative: every other
trigger is a write to the request, so a draft that already existed when an
approver was added to (or removed from) the category would otherwise confirm
with the set computed at its creation. The pure "who should approve" decision step is
extracted to `_compute_desired_approvers()` (unit-testable, no writes).
Sources: category approvers, conditional rules (adding or replacing), security groups,
HR manager (via extension hook).

### Security Design
Two-layer validation on all CRUD:
1. **Access control** (WHO): bypassed by sudo/manager
2. **Business rules** (WHAT state): sudo-proof, with one deliberate
   exception — `approval.approver._check_business_rules_write`, which the
   workflow's own sudo writes must pass through (see conventions.md).
   Includes the server-side locked-fields rule (`_check_locked_fields`),
   which freezes two sets once the request leaves draft (2026-07-03 audit):
   - `_LOCKED_FIELDS` — decision values + identity: `amount`,
     `currency_id`, `quantity`, the five date fields, `partner_id`,
     `reference`, `location`, `reason`, `request_owner_id`,
     `company_id`, and the source-document link `res_model`/`res_id`.
     Frozen for EVERYONE (sudo included). `date`/`reason` reopen via
     the request-a-change flow.
   - `_SYSTEM_LOCKED_FIELDS` — system-managed: `approval_minimum`
     (the threshold), `name`, `date_confirmed`, `category_snapshot`.
     Frozen against NON-sudo (user/RPC) writers only; the privileged
     writers are `action_confirm` (while still `new`), reset-to-draft
     (sudo), and the approver sync (sudo). Confirmation-time writes pass
     because state is still `new`.
   - `priority` is intentionally NOT frozen — a framework field, editable
     in every state.
   - A third, state-independent set: `_COMPUTE_ONLY_FIELDS` —
     `state`, `date_approval_granted`, `date_refused`, `date_cancelled`,
     `approval_deadline`, `res_model_id`. `_check_no_forged_computed_fields`
     rejects these in ANY state, draft included, because they are outputs
     of the workflow: writing `state` directly would forge a decision that
     no approver row backs, and the terminal-date stamps are what the
     analytics treat as proof one happened.

### Name / Numbering
The `name` column stays empty (language-neutral) until `action_confirm()`
assigns the category sequence consecutive; drafts display a translated
"New" placeholder via `display_name` only. Discarded drafts never burn
sequence numbers; reset-then-reconfirmed requests keep their number.

### Quick Approve (removed)
The token/HMAC quick-approve feature was removed in 19.0.1.0.2 (replaced by
Telegram bot integration in separate `telegram_bot_*` modules). This module
ships no controllers and no post-init hook.

## Extension Points

- `_get_additional_approvers()` -- Add custom approvers (e.g., HR manager)
- `_get_escalation_manager(approver)` -- Supply the manager for escalation (approval_hr)
- `_check_withdraw_allowed()` / `_raise_withdraw_blocked()` -- Block withdrawal (e.g., linked invoices)
- `_check_reset_allowed()` -- Veto reset-to-draft (base blocks released source docs)
- `_can_consent_approve()` -- Veto consent auto-approval per request
- `_refuse_approval_request()` -- Cooperative rollback of documents created from the approval
- `_on_approval_state_changed()` -- React to approval decisions in source docs
- `_get_domain_approval_category()` -- Map document types to categories
- `_get_category_required_field_mapping()` -- Add required field validation
- `_get_fields_locked()` -- Extend the post-submit frozen field set
- `_approval_rate_limit_exceeded()` -- Submission throttle on the mixin: "has this
  user filed more than N documents, or more than X in value, in the last H hours?"
  Multi-currency by construction — the caller's thresholds are in company currency
  and are converted per counterparty currency before comparison. Used by
  approval_purchase / approval_sale
- `_get_fields_approval_protected()` -- Fields on the SOURCE document that the mixin's
  `write()` freezes while an approval is in flight
- `approval_type` / `target_model` -- Selection fields extended by other modules
