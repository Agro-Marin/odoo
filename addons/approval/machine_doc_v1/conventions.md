# Approval Conventions & Gotchas

## Security Model

### Three-Layer Defense in Depth

| Layer | What It Checks | Bypass |
|-------|---------------|--------|
| 1. `ir.rule` (SQL) | Row-level filtering (read/write/create/unlink domains) | Sudo bypasses |
| 2. Python CRUD access (`_check_access_*`) | WHO can perform the operation | Sudo or managers (the sync engine runs under sudo). Non-manager approvers may write only delegation and decision-note fields on their own row — never `state`/`sequence`/`required` |
| 3. Python business rules (`_check_business_rules_*`, `_check_locked_fields`) | WHAT states allow the operation | Sudo-proof on the request: `_check_locked_fields` (`_LOCKED_FIELDS` half) and `_check_no_forged_computed_fields` bind everyone. On `approval.approver`, create and unlink are equally sudo-proof — their only exemption is `env.su` **plus** the `approver_ids_computation` context — but `_check_business_rules_write` returns early on `env.su` alone, because the workflow itself writes `state` and the decision stamps under sudo |

### Groups

| Group | XML ID | Implies | Permissions |
|-------|--------|---------|-------------|
| Approver | `group_approval_approver` | `base.group_user` | Shows the "My Approvals" menu. It is **not** what grants the right to decide — that comes from being assigned on the request, group or no group. No configuration access |
| Administrator | `group_approval_manager` | `group_approval_approver` | Full CRUD on all models, configuration access |

Both sit under the `res_groups_privilege_approvals` privilege
(`security/res_groups.xml`).

### ACL Summary (ir.model.access.csv)

| Model | Internal User (group_user) | Manager (group_approval_manager) |
|-------|---------------------------|----------------------------------|
| `approval.category` | read | full CRUD |
| `approval.category.approver` | read | full CRUD |
| `approval.request` | full CRUD | (inherits from user) |
| `approval.approver` | full CRUD (ACL level) | (inherits from user) |
| `approval.refusal.reason` | read | full CRUD |
| `approval.template` | read | full CRUD |
| `approval.rule` | read | full CRUD |
| `approval.document.requirement` | read | full CRUD |
| `approval.dashboard` | **none** (0,0,0,0) | full CRUD |
| `approval.metrics` | **none** (0,0,0,0) | full CRUD |
| `approver.performance` | **none** (0,0,0,0) | full CRUD |
| Wizards (decision, delegate) | full CRUD | (inherits from user) |
| `approval.test.document` | **no ACL row at all** | — (reached via sudo/manager in tests) |

**The three analytics models are manager-only.** Their `base.group_user`
row exists but grants nothing — it is there to make the intent explicit
rather than to leave the model unlisted. A plain internal user opening a
dashboard action gets an access error, by design: the dashboard and both
SQL views aggregate across every requester, which is exactly what
`privacy_visibility` restricts on the request itself.

**Important:** `approval.approver` has full CRUD at the ACL level for all users, but
Python CRUD methods (`_check_access_create/write/unlink`) block manual operations.
Only the sync engine (via `approver_ids_computation` context) or sudo/manager can
create/delete approvers — and even then **only while the request is `new`**
(business rule, tightened in 19.0.1.0.13), except during a sync. Refused and
cancelled requests are NOT re-openable this way: reset them to draft first.

### Record Rules

| Rule | Model | Scope | Domain |
|------|-------|-------|--------|
| Multi-company | category, category_approver, refusal_reason, rule, template | Global | `company_id in company_ids + [False]` — the `+ [False]` is what lets a company-less rule apply everywhere (`mixin.approval.threshold.company_id`) |
| Multi-company | request, approver, metrics, performance | Global | `company_id in company_ids` |
| User read | request | group_user | Owner OR approver OR delegate |
| User read | approver | group_user | Own request's owner OR self OR delegate OR **co-approver on the same request** (`request_id.approver_ids.user_id`/`.delegate_id`) — approvers can see who else is on the chain, which is what makes the sequential position legible |
| Visibility read (additive) | request, approver | group_user | `category_id.privacy_visibility` audiences: `restricted_users` (in `allowed_user_ids`), `restricted_groups` (in `allowed_group_ids.all_user_ids`), `employees` (everyone). `private` adds no extra audience. Read-only; same-group rules OR together so these only WIDEN visibility |
| User write | request | group_user | Owner OR approver OR delegate |
| User write | approver | group_user | Self OR delegate |
| User create | request | group_user | Owner = current user |
| User unlink | request | group_user | Owner = current user AND state = new |
| Manager read | request, approver | group_approval_manager | All |
| Manager write/create | request, approver | group_approval_manager | All |
| Manager unlink | request | group_approval_manager | state = new only (submitted/terminal requests are audit trail) |
| Manager unlink | approver | group_approval_manager | All — the single `approval_approver_manager_write` rule carries `perm_unlink`. The row-level gate is open here on purpose: the state gate is the Python business rule (`_check_business_rules_unlink`, draft only), which no rule and no sudo bypasses |

---

## How to Extend Approval for a New Domain

### Step 1: Extend category selection fields

```python
# In your module's model that extends approval.category:
class ApprovalCategory(models.Model):
    _inherit = "approval.category"

    approval_type = fields.Selection(
        selection_add=[("purchase", "Purchase Order")],
    )
    target_model = fields.Selection(
        selection_add=[("purchase.order", "Purchase Order")],
    )
```

### Step 2: Inherit the mixin in your model

```python
class PurchaseOrder(models.Model):
    _inherit = ["purchase.order", "mixin.approval"]

    def _get_domain_approval_category(self):
        return [("approval_type", "=", "purchase")]

    def _get_approval_required_fields(self):
        return ["partner_id", "order_line"]

    def _get_approval_reason_html(self):
        return f"<p>Purchase order {escape(self.name)}</p>"

    def _prepare_approval_request_values(self, category):
        vals = super()._prepare_approval_request_values(category)
        vals["amount"] = self.amount_total
        vals["partner_id"] = self.partner_id.id
        return vals

    # Override the PER-TRANSITION hooks, never the dispatcher.
    def _on_approval_approved(self):
        self.button_confirm()

    def _on_approval_refused(self):
        self.state = "rejected"
```

**Do not override `_on_approval_state_changed`.** It is the dispatcher;
overriding it and calling `super()` was how every satellite ended up
posting two chatter messages for one decision — the base dispatches to
`_on_approval_approved`, which posts a generic "Approval granted", and
the satellite's richer message then landed on top of it. Override the
per-transition hook instead (`_on_approval_approved`,
`_on_approval_refused`, `_on_approval_cancelled`, `_on_approval_revoked`,
`_on_approval_reset`) and omit `super()` when your message replaces the
generic one.

**Do not override `_get_approval_category` either.** The mixin owns the
whole selection algorithm — search the candidate domain, narrowed to the
document's own company plus company-less categories, in `sequence, id`
order, and return the first category whose `_is_applicable_for` accepts
the document. An EMPTY domain short-circuits to `False` without calling
`_raise_approval_category_not_configured()`: "this document type has no
approval configured" is not the same failure as "it does, and nothing
matched". Supply only the parts that vary:

| Seam | Supply when |
|------|-------------|
| `_get_domain_approval_category()` | always — which categories are candidates |
| `approval.category._is_applicable_for(document)` | your categories carry matching criteria (amount, partner, product…). Fall through to `super()` for documents you do not own, and be **fail-closed**: a category with no criteria configured must match nothing |
| `_get_approval_category_fallback(categories)` | approval can be triggered by a flag *outside* the category criteria and needs a generic category to route to |
| `_raise_approval_category_not_configured()` | "no category exists" is a configuration error worth naming, not "no approval needed" |
| `_raise_approval_category_not_matched(categories)` | same, for "categories exist but none matched this document" |

Both `_raise_*` hooks are no-ops in the base, so the documented contract
of `_get_approval_category` — return False, don't raise — still holds for
consumers that do not opt in.

**Anything that runs inside `_on_approval_*` runs inside the approver's
`action_approve` transaction**, and the core deliberately does not
swallow exceptions from it. If your hook advances the document
(`action_confirm`, `action_post`, `button_validate`), put it inside
`_approval_side_effect()`, which supplies the savepoint, the
`UserError`/`ValidationError` catch and the chatter note:

```python
def _on_approval_approved(self):
    ...
    with self._approval_side_effect(
        self.env._(
            "Approval was granted but the order could not be auto-confirmed: %(error)s"
        ),
    ):
        self.action_confirm()
```

Do not hand-roll the savepoint. Without it a failure leaves the
document's partial writes in the transaction, or poisons it so your own
warning `message_post` fails and propagates — killing the approval with
an error addressed to the wrong person. approval_stock shipped exactly
that bug (a failed auto-validate committing half-applied stock moves)
because the guard was a convention each satellite re-implemented rather
than something the mixin provided.

`_approval_decider_names(state)` is the matching helper for the other
line every hook repeats — the filter-and-join over `approver_ids` that
opens the decision message. Pass the state you mean (`"approved"`,
`"refused"`).

### Step 3: Add views for the approval button

```xml
<record id="purchase_order_form_inherit_approval" model="ir.ui.view">
    <field name="name">purchase.order.form.approval</field>
    <field name="model">purchase.order</field>
    <field name="inherit_id" ref="purchase.purchase_order_form"/>
    <field name="arch" type="xml">
        <xpath expr="//button[@name='button_confirm']" position="before">
            <button name="action_create_approval_request"
                    string="Request Approval"
                    type="object"
                    invisible="not can_request_approval"/>
            <button name="action_view_approval_request"
                    string="View Approval"
                    type="object"
                    invisible="not approval_request_id"/>
        </xpath>
    </field>
</record>
```

### Step 4 (optional): Block withdrawal when documents are linked

```python
class ApprovalRequest(models.Model):
    _inherit = "approval.request"

    def _check_withdraw_allowed(self):
        super()._check_withdraw_allowed()
        if self.res_model == "purchase.order" and self.res_id:
            po = self.env["purchase.order"].browse(self.res_id)
            # Shared message/count formatting for all satellites:
            self._raise_withdraw_blocked(po.invoice_ids, "invoice/bill")
```

### Step 5 (optional): Add custom approvers via extension hook

```python
class ApprovalRequest(models.Model):
    _inherit = "approval.request"

    def _get_additional_approvers(self):
        result = super()._get_additional_approvers()
        # Add the employee's manager as first approver
        if self.request_owner_id.employee_id.parent_id.user_id:
            manager = self.request_owner_id.employee_id.parent_id.user_id
            result.append((manager.id, True, self._get_sequence_manager()))
        return result
```

### Step 6 (optional): Freeze additional value fields after submit

```python
class ApprovalRequest(models.Model):
    _inherit = "approval.request"

    def _get_fields_locked(self):
        return super()._get_fields_locked() | {"bank_account_id"}
```

---

## Common Pitfalls

### 1. Writing approver state directly without the decision funnel

**Wrong:**
```python
approver.write({"state": "approved"})
```

**Right:** use `request.action_approve()` / `action_refuse()` (or, for
non-decision terminations, `request._force_terminal(...)`). The funnel
`_apply_decision()` handles locking (`_lock_for_approval_action`), cache
invalidation, delegation resolution, chain advancement, activity
cleanup and the source-document notification. If you must write states
in custom code, lock first and call
`_update_next_approvers_state()` / `_notify_if_terminal_transition()`
yourself.

### 2. Creating/deleting approvers without context

**Wrong:**
```python
self.env["approval.approver"].create({"request_id": request.id, "user_id": user.id})
```

This will be blocked by `_check_access_create()` — for regular users
unconditionally (H9), and by `_check_business_rules_create()` on any request
that is not `new` — managers and sudo included (only `env.su` **plus** the
`approver_ids_computation` context is exempt). Approvers are managed by
`_sync_approvers()`.

**Right:** Configure the category, its rules, or override `_get_additional_approvers()`.

### 3. Editing value fields after submission

`amount`, `currency_id`, `quantity`, `date*`, `partner_id`, `reference`,
`location`, `reason`, `request_owner_id`, `company_id` and the source
link `res_model`/`res_id` are frozen once the request leaves draft —
enforced server-side by `_check_locked_fields()` (never bypassed, sudo
included), not just by form readonly. `currency_id` is in the set for the
same reason `amount` is: every rule threshold was evaluated
against the amount converted FROM it, so moving it after submit would
silently re-price the decision. The only sanctioned reopening is
the request-a-change flow: while `pending_change_field` is set, exactly
the flagged field (date fields or reason) is writable again — and only
for the REQUESTER (owner, manager or sudo), never for an approver, who
would otherwise be able to move a value their co-approvers already
signed. Applying the change resets those earlier approvals: `action_
resubmit()` reopens a fresh decision round (see architecture.md). To
change anything else, reset a refused/cancelled request to draft.

### 4. Forgetting to cancel activities on terminal states

When a request reaches a terminal state (approved, refused, cancelled), leftover
activities for other pending approvers must be cleaned up. `_apply_decision()`
and `_force_terminal()` handle this; if you write custom state transitions,
call `_cancel_activities()`.

### 5. Modifying category after confirmation

Category changes are blocked after `action_confirm()` by both a constraint
(`_check_category_change`, form saves) and a guard in `write()` (direct ORM
writes) — both raise via the shared `_raise_category_change_blocked()`.
The block applies to any state other than `new`: to change the category,
either create a new request, or (for refused/cancelled requests) use
`action_reset_to_draft()` — back in draft the category is editable again.

### 6. Assuming request owner can modify approvers

Request owners **cannot** add, remove, or modify approver records. All approver
management flows through `_sync_approvers()`. The owner's role is limited to:
- Creating the request
- Filling in fields (draft only — see locked fields)
- Confirming (action_confirm)
- Re-submitting after a requested change (action_resubmit)
- Cancelling a pending request (action_cancel)
- Reopening a refused/cancelled request (action_reset_to_draft)

### 7. Ignoring delegation when checking approvers

**Wrong:**
```python
approver = request.approver_ids.filtered(lambda a: a.user_id == current_user)
```

**Right:**
```python
approver = request._get_current_pending_approver()  # pending rows for env.user
# or, for arbitrary states:
approver = request.approver_ids.filtered(
    lambda a: a._get_effective_approver() == current_user
)
```

`_get_current_pending_approver()` is the single delegation-aware resolution
helper used by the header buttons, bulk actions and wizard defaults.

### 8. Not handling the `approver_ids_computation` context

When `_sync_approvers()` creates/deletes approvers via `Command.create()`/`Command.delete()`,
it runs the write under **`sudo()`** and sets `context(approver_ids_computation=True)`.
The context key alone is NOT a bypass — RPC clients control the context dict, so a
context-only escape hatch let any internal user forge approver rows. `_skip_check_access()`
therefore keys only on `env.su`/manager; the business rules (`_check_business_rules_create/unlink`
and `_check_approver_ids_business_rules`) require **both** `env.su` AND the context key.
If you add custom access/business checks on `approval.approver`, gate any
`approver_ids_computation` exemption on `self.env.su` too.

### 9. Expecting the compute to notify source documents

`_compute_state()` has NO side effects. The `_on_approval_state_changed()`
hook fires from the transitioning action via
`_notify_if_terminal_transition(old_state)`. If you add a new code path
that drives a request into a terminal state, you own the notification.

---

## Test Commands

Run from the **workspace root** (`~/Odoo`), with the venv interpreter —
the paths and the config file are the ones described in the root
`CLAUDE.md`. `<db>` should be named so it says whose it is; several
sessions share these checkouts.

```bash
# Fresh database + install + full approval suite.
# Create it THROUGH Odoo, not createdb: p314o19m.conf sets
# db_template = tpl_p314o19marin, which already carries pg_trgm,
# unaccent, vector and postgis.
p314o19m/bin/python odoo/odoo-bin -c p314o19m.conf -d <db> \
    -i approval --test-tags '/approval' --stop-after-init

# Re-run on an existing database
p314o19m/bin/python odoo/odoo-bin -c p314o19m.conf -d <db> \
    -u approval --test-tags '/approval' --stop-after-init

# Specific class / method
... --test-tags '/approval:TestCancelFlow' --stop-after-init
... --test-tags '/approval:TestCancelFlow.test_owner_can_cancel_pending' --stop-after-init

# Port 8069 is shared. Either pass --http-port <n> or, as above,
# --stop-after-init so nothing binds. Redirect to a log to grep:
... > /tmp/approval.log 2>&1
grep "tests when loading" /tmp/approval.log
grep -E "ERROR|FAIL:" /tmp/approval.log | tail -20

# Teardown
psql -U marin -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='<db>';"
dropdb -U marin <db>
```

Baseline: **506 tests, 0 failed, 0 errors** across the 29 test modules
(re-measured 2026-08-12 on a fresh install, ~90s).

JS tests use the warm HOOT runner, not `odoo-bin`. Suite ids are
`@approval/<basename without .test.js>`:

```bash
cd odoo/tooling/hoot
./hoot '@approval/category_kanban'       # or @approval/activity_patch
./hoot --affected ../../addons/approval/static/tests/<file>.test.js
```

Name the files explicitly — a bare `--affected` picks up whatever other
sessions have left in the shared worktree.

New test files should inherit `tests.common.ApprovalCommon` (shared
owner/approver/manager users + `_make_category` / `_make_request`
factories) instead of rebuilding user fixtures.

---

## "When Modifying X, Also Update Y"

| When You Modify... | Also Update... |
|---------------------|---------------|
| `approval.category` approver_ids | PENDING requests are frozen (their approver set is the audit trail); DRAFTS pick the change up at `action_confirm()`, which re-syncs against the current category configuration |
| `approval.category` fields (has_*, approval_minimum) | Existing drafts are not rewritten on the spot, but `approval_minimum` is re-derived from the category at `action_confirm()`; `has_*` are related fields, so they follow immediately |
| `_compute_state()` logic | The action methods that call `_notify_if_terminal_transition()` -- the compute itself must stay side-effect free |
| `_compute_sla_status()` logic | `_search_sla_status()` -- its SQL CASE mirrors the compute exactly; update both together |
| `_sync_approvers()` / `_compute_desired_approvers()` sources | `_merge_approver_to_staging()` merge rules (required OR, sequence MIN); rows always stage 'new' (sync is draft-only) |
| `_get_additional_approvers()` override | Must return `list[tuple[int, bool, int]]` (user_id, required, sequence) |
| `ESCALATION_RULES` constant (`approval_request.py`) | `_get_escalation_rules()` overlays `approval.escalation.<priority>.<kind>` system parameters on top of it -- do not restate the numbers elsewhere |
| `action_confirm()` validation | `_check_confirm()` which calls `_check_enough_approvers()`, `_check_has_document_has_attachment()`, `_check_category_required_fields()` |
| `_LOCKED_FIELDS` / `_get_locked_fields()` | `_PENDING_CHANGE_EDITABLE` (fields reopened by the change flow) and the form view `readonly` attrs |
| `approval_type` / `target_model` selection | Both are on `approval.category` with `selection_add` -- extend there, not on request (request uses related) |
| Approver CRUD access checks | Both `approval_request_validation.py` (`_check_access_approver_ids`) AND `approval_approver.py` (`_check_access_create/write/unlink`) -- they enforce the same rules at different levels |
| `_check_withdraw_allowed()` override | Use `_raise_withdraw_blocked()` for the canonical message; provide clear reasons why withdrawal is blocked |
| New category fields for validation | Extend `_get_category_required_field_mapping()` in `approval_request_validation.py` (note: base intentionally does NOT map `has_payment_method`) |
| Terminal transitions added in new code | Route through `_apply_decision()` (decisions) or `_force_terminal()` (non-decisions) so metadata, activities and notifications stay consistent |
| SQL views (`approval_metrics`, `approver_performance`) | Both are `_auto = False` + `mixin.sql.report`, which builds the statement at query time from `_get_select_fields()` / `_get_from_tables()` / `_get_where_conditions()` / `_get_group_by_fields()`. A new field needs its own SELECT entry — the field list and the query are not linked |
| `approval.request.amount` or any threshold | `amount` is **Monetary** in `currency_id`. Never compare it to a rule threshold directly — go through `mixin.approval.threshold._convert_request_amount()`, which converts into the rule's own currency |
| Cron schedule or logic | Update `data/ir_cron_data.xml` AND the Python method (3 crons; the file is `noupdate="1"`, removals need a migration -- see 19.0.1.0.7) |
| Stored columns removed/de-stored | Add a migration (cf. 19.0.1.0.7: dropped `approver_compute_ms`, stale `sla_status` column, cleared stored draft-name placeholders) |

---

## Context Keys

| Key | Set By | Effect |
|-----|--------|--------|
| `approver_ids_computation` | `_sync_approvers()` (under `sudo()`) | Together with `env.su`, relaxes the state business-rules on `approval.approver` CRUD. Ignored without `env.su` — the key is client-forgeable via RPC context, so it is never a bypass on its own |
| `skip_wizard` | Bulk operations, crons, mixin, tests | Bypasses decision wizard, performs action directly |
| `requested_change_field` | Decision wizard (`action_confirm_change`) | Field name ('date'/'reason') consumed by `action_request_change()` inline path |
| `default_category_id` | Category kanban "New Request" | Pre-fills category on request form |
| `default_approver_id` / `default_decision_type` | `_get_decision_wizard_action()` | Pre-fills the decision wizard (decision_type: 'refuse' or 'change'). Only these two — the wizard's `request_id` is a precomputed stored compute off `approver_id`, so there is no `default_request_id` |
| `approval_acting_user_id` | `_notify_source_document_state_change()` | Carries the deciding user's id into the source document's `_on_approval_*` hook, which runs under `sudo()`. Read it to attribute a satellite's own chatter message to the approver rather than to OdooBot |

---

## Split Model Pattern

`approval.request` is split across 6 files for maintainability. All use `_inherit = "approval.request"`:

| File | Responsibility | Method Prefix |
|------|---------------|---------------|
| `approval_request.py` | Fields, CRUD, smart-copy, `ESCALATION_RULES` | `create`, `write`, `unlink`, `copy` |
| `approval_request_compute.py` | All `@api.depends` methods + field searches | `_compute_*`, `_search_sla_status` |
| `approval_request_action.py` | User-facing actions, search, onchange, `_apply_decision` | `action_*` |
| `approval_request_validation.py` | Access control + business rules (incl. locked fields) | `_check_*` |
| `approval_request_helper.py` | Private helpers, `_sync_approvers`, `_force_terminal`, `_TERMINAL_STATES` | `_sync_*`, `_get_*`, `_merge_*`, `_force_*` |
| `approval_request_cron.py` | Scheduled actions | `cron_*` |

When adding a new method, place it in the file matching its responsibility.
