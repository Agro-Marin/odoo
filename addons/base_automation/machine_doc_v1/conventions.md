# base_automation — Conventions & Gotchas

## Naming

| Concept | Name | Notes |
|---------|------|-------|
| Rule definition | `base.automation` | Historical name, keep for compat |
| Node | `ir.actions.server` (extended) | Keep until Phase 3 decision |
| Edge | `predecessor_ids` / `successor_ids` | Transitional — target is `workflow.edge` |
| Execution instance | `automation.runtime` | The right model, wrong scope today |
| Execution step | `automation.runtime.line` | Correct pattern — isolated per execution |
| Visual diagram | `flow.diagram` | In `web_flow`, BPMN XML + element_mappings |

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

## `automation.runtime` Domain Restriction

`automation_id` domain is `[("model_name", "=", "base.automation")]`.
This is **intentional** — `automation.runtime` currently serves meta-workflows
only. The domain will be removed in Phase 1. Do not work around it by changing
the domain until Phase 1 is ready.

## `_prepare_logging_values` (not `_prepare_loggin_values`)

The correct spelling is `_prepare_logging_values` (fixed in PR #63). If you
see `_prepare_loggin_values` anywhere, it is a leftover that needs updating.

## web_flow Integration — Current State

`web_flow` is in `addons_custom/` and has no dependency on `base_automation`.
It is a standalone visual framework that can render any DAG-shaped data.

The integration between `web_flow` and `base_automation` does not yet exist as
code — it is architectural intent. When building the integration:

1. `flow.diagram.res_model = "base.automation"`, `res_id = automation.id`
2. `element_mappings` JSON maps BPMN shape IDs → `ir.actions.server` IDs
   and BPMN edge IDs → `workflow.edge` IDs (Phase 2)
3. The automation form view embeds the BPMN modeler via OWL widget

## Test Tags

- `test_automation.py`: `@tagged("post_install", "-at_install")` — correct
- `test_triggers.py`: no `@tagged` — runs at-install, correct for basic model tests
- `test_workflow_dag.py`: no `@tagged` — runs at-install, correct

Do not add `@tagged("post_install")` to `test_triggers.py` or
`test_workflow_dag.py` — these tests do not require post-install state.

## Stdout is Empty

All test output goes to `./odoo.log` (set in `conf/odoo.conf`). Always:

```bash
> ./odoo.log && ./core/odoo-bin -c ./conf/odoo.conf -d test_db \
    --test-tags '/base_automation' -u base_automation --stop-after-init --workers=0
grep "tests when loading" ./odoo.log
```
