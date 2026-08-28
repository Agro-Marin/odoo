# base_automation — Conventions & Gotchas

## Naming

| Concept | Name | Notes |
|---------|------|-------|
| Rule definition | `base.automation` | Historical name, keep for compat |
| Node | `ir.actions.server` (extended) | Keep until Phase 3 decision |
| Edge | `predecessor_ids` / `successor_ids` | Transitional — target is `workflow.edge` |
| Execution instance | `automation.runtime` | The right model, wrong scope today |
| Execution step | `automation.runtime.line` | Correct pattern — isolated per execution |
| Visual diagram | — | No model yet; the layout layer is undecided along with the editor |

## Readiness Is `state`, and Only `state`

`automation.runtime.line` deliberately has **no `is_ready` field**. It existed
as a stored computed boolean that read `False` for a line already in state
`ready`, nothing gated on it, and a line could sit `waiting` with `is_ready`
True forever with nothing reconciling the two — which is exactly how a run with
an unresolvable dependency wedged silently. Use
`line._predecessors_satisfied()` when you need to ask whether a step may start.

## A Failed Step Is an Outcome, Not an Exception

`automation.runtime.line.action_execute()` runs the server action inside its own
savepoint and, on failure, rolls that savepoint back, records `error` plus the
message on the line, marks the run `error`, and **returns `False` without
re-raising**. Re-raising unwound the whole transaction and destroyed the
runtime, its lines and the error message — the execution history was erased by
precisely the failures it exists to record. Do not "fix" this back into a raise.

## Predecessors Are Scoped to One Automation

`_check_predecessors_scope` rejects a `predecessor_ids` entry belonging to a
different `base_automation_id`. Such an edge used to be accepted and then
dropped at runtime, leaving the node `waiting` with nothing that could ever
complete it. Correspondingly, `_create_action_lines` decides readiness from the
*resolved* lines, never from the definition's edges.

## Webhook Checks Are Ordered: Authenticate, Then Rate-Limit

`_verify_webhook_request` runs the cheap guards (IP allowlist, payload size),
then authentication (timestamp, signature), and only then the rate limit. The
bucket is shared with the legitimate sender, so spending a token on an
unauthenticated request let anyone holding just the URL lock that sender out.
Header lookups go through `CaseInsensitiveHeaders` because HTTP header names are
case-insensitive and the configured name is free text.

## What NOT to Add to `ir.actions.server`

Do not add fields to `ir.actions.server` that track execution state.
`action_state`, `is_ready`, and `error_message` were mistakes and have been
removed in Phase 1. All execution state belongs on `automation.runtime.line`.

If you need to know "what state is this action in", you are asking the wrong
question — ask "what state is this *execution step* (`runtime.line`) in".

## Removed Transitional Fields (Phase 1 Complete)

`use_workflow_dag` and `auto_execute_workflow` have been **removed** from
`base.automation`. All automations are now DAG-capable. Do not re-add these
fields under any name.

## The `__action_done` Context Key

`context["__action_done"]` is a `dict[base.automation → recordset]` that
prevents the same automation from firing twice on the same record within one
transaction. It is the recursion guard.

Rules:
- In `__action_feedback` mode (during domain evaluation): mutate the dict in-place.
- Normal mode: copy the dict before adding entries (preserves immutability for
  parallel branches).
- Never clear or remove entries from this dict within a transaction.

## `_filter_pre` vs `_filter_post`

| Method | When evaluated | Domain field | Used by |
|--------|---------------|-------------|---------|
| `_filter_pre` | Before write | `filter_pre_domain` | WRITE triggers only |
| `_filter_post` | After event | `filter_domain` | All triggers |
| `_filter_post_export_domain` | After event | `filter_domain` | Returns `(records, domain)` |

`_filter_pre` is evaluated with old values still in the DB.
`_filter_post` is evaluated after the write has committed to memory.

## safe_eval Usage

All domain evaluation (`filter_domain`, `filter_pre_domain`, `record_getter`)
uses `safe_eval.safe_eval()` with a restricted context from `_get_eval_context()`.
Never pass user-controlled strings to Python `eval()`.

The `DOMAIN_FIELDS_RE` regex (not `safe_eval`) is used to extract field names
from domain strings inside compute methods — because compute methods can be
triggered from malicious onchange calls.

## Cron Interval — Only Decreases Automatically

`_update_cron()` only lowers the cron interval when a faster schedule is needed.
It does not automatically increase the interval when short-delay automations are
removed. If the last 1-minute automation is deleted, the cron stays at 1-minute
until manually reset or Odoo restarts. This is acceptable — over-frequent cron
execution is harmless (just slightly wasteful).

## Webhook UUID Rotation

`action_rotate_webhook_uuid()` generates a new UUID, invalidating all existing
webhook URLs for that automation. There is no grace period. Use with caution in
production — notify all external systems before rotating.

## `automation.runtime` Domain Restriction — REMOVED

The `automation_id` domain was removed in Phase 1; any automation can have
runtime instances. This section previously said the restriction was
"intentional … do not work around it", contradicting `models.md` and the code.
Nothing to preserve here — do not reintroduce a domain.

## `_prepare_logging_values` (not `_prepare_loggin_values`)

The correct spelling is `_prepare_logging_values`. Upstream's misspelling
(`_prepare_loggin_values`) is not present in this fork.

## There Is No Visual Editor

Earlier revisions of this file described integrating a `web_flow` module from
`agromarin/` via a `flow.diagram` model and BPMN element mappings. That module was
**deleted as unused** on 2026-04-21 (`agromarin` `60b5a7eef`) and no replacement
was ever written. `vision.md` Decision 1 carries the removal rationale and the
constraints on whatever replaces it.

Two things follow for anyone building the canvas:

* **Nothing stores a node position.** There is no `pos_x`/`pos_y` on
  `ir.actions.server` and no diagram blob anywhere. Coordinate storage is step 0
  of Phase 4, not an afterthought.
* **An edge can carry no attributes.** `predecessor_ids`/`successor_ids` are two
  views of one self-referential many2many, which is why both carry `copy=False`.
  A canvas can *draw* a conditional branch but has nowhere to persist the
  condition until `workflow.edge` lands in Phase 2.

## Test Tags

- `test_automation.py`: `@tagged("post_install", "-at_install")` — correct
- `test_triggers.py`: no `@tagged` — runs at-install, correct for basic model tests
- `test_workflow_dag.py`: no `@tagged` — runs at-install, correct
- `test_webhook_security.py`: `@tagged("post_install", "-at_install")` — calls
  `_verify_webhook_request` directly with plain dicts
- `test_audit_regressions.py`: `@tagged("post_install", "-at_install")`; its
  webhook cases are `HttpCase` **on purpose**. The dict-based tests above cannot
  see a case-sensitive header lookup or a rate limiter placed before
  authentication — both shipped and both were invisible to them. Any change to
  the webhook path needs a real request in its test.

Do not add `@tagged("post_install")` to `test_triggers.py` or
`test_workflow_dag.py` — these tests do not require post-install state.

## Stdout is Empty

All test output goes to `./odoo.log` (set in `conf/odoo.conf`). Always:

```bash
> ./odoo.log && ./odoo/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/base_automation' -u base_automation --stop-after-init --workers=0
grep "tests when loading" ./odoo.log
```
