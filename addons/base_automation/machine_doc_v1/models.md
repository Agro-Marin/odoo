# base_automation — Models

## base.automation (Rule Definition)

The workflow *definition*. Owns the trigger configuration, filter conditions,
and the set of `ir.actions.server` nodes that form the DAG.

### Key Fields

| Field | Type | Purpose |
|-------|------|---------|
| `trigger` | Selection (17 values) | When this workflow fires |
| `model_id` | Many2one `ir.model` | Target model (required) |
| `filter_pre_domain` | Char | Pre-condition: record state *before* write |
| `filter_domain` | Char | Post-condition: record state *after* event |
| `action_server_ids` | One2many `ir.actions.server` | DAG nodes |
| `trigger_field_ids` | Many2many `ir.model.fields` | Write-trigger field watch list |
| `on_change_field_ids` | Many2many `ir.model.fields` | Onchange field watch list |
| `trg_date_id` | Many2one `ir.model.fields` | Date field for time triggers |
| `trg_date_range` | Integer | Delay amount (always positive) |
| `trg_date_range_type` | Selection | minutes / hour / day / month |
| `trg_date_range_mode` | Selection | before / after the trigger date |
| `trg_date_calendar_id` | Many2one `resource.calendar` | Working-day calendar |
| `webhook_uuid` | Char | UUID for webhook URL (rotatable) |
| `record_getter` | Char | Python expression: payload → record |
| `log_webhook_calls` | Boolean | Log webhook calls to `ir.logging` |
| `last_run` | Datetime | Last successful cron execution |
| `use_workflow_dag` | Boolean | **TRANSITIONAL** — see vision.md |
| `auto_execute_workflow` | Boolean | **TRANSITIONAL** — auto-advance DAG |

### Trigger Categories

```
CREATE triggers:   on_create, on_create_or_write, on_priority_set,
                   on_stage_set, on_state_set, on_tag_set, on_user_set

WRITE triggers:    on_write, on_archive, on_unarchive, on_create_or_write,
                   on_priority_set, on_stage_set, on_state_set, on_tag_set,
                   on_user_set

TIME triggers:     on_time, on_time_created, on_time_updated

MAIL triggers:     on_message_received, on_message_sent

MANUAL trigger:    on_hand
WEBHOOK trigger:   on_webhook
ONCHANGE trigger:  on_change  (UI-only, form view onchange)
```

### Constants (module-level)

| Constant | Value | Meaning |
|----------|-------|---------|
| `CRON_INTERVAL_TOLERANCE_PERCENT` | 0.10 | 10% of min delay → cron frequency |
| `DEFAULT_CRON_INTERVAL_MINUTES` | 240 | 4 hours, when no time automations |
| `MIN_CRON_INTERVAL_MINUTES` | 1 | Floor |
| `MAX_CRON_INTERVAL_MINUTES` | 240 | Ceiling |
| `MONTH_APPROXIMATION_DAYS` | 30 | Used for `timedelta` month conversion |

---

## ir.actions.server (extended as DAG Node)

Extended by `models/ir_actions_server.py`. Serves as both the standard Odoo
server action model AND the workflow node definition.

### Added Fields

| Field | Type | Purpose |
|-------|------|---------|
| `base_automation_id` | Many2one `base.automation` | Owning rule |
| `usage` | Selection (extended) | Added `"base_automation"` value |
| `predecessor_ids` | Many2many self | Nodes that must complete before this |
| `successor_ids` | Many2many self | Computed inverse of `predecessor_ids` |
| `action_state` | Selection | **BROKEN — see below** |
| `is_ready` | Boolean (computed, stored) | All predecessors done |
| `error_message` | Text | Last error if `action_state == error` |

### action_state — Known Design Flaw

`action_state` is a field on the **definition** model (`ir.actions.server`),
not on an **execution instance**. This means:

- Two concurrent executions of the same automation corrupt each other's state.
- Sequential re-runs of an automation leave stale state from the previous run.
- Resetting state (`action_reset_workflow()`) mutates the definition, not an
  execution record.

**This field is slated for removal.** All execution state will move to
`automation.runtime.line`. Do not add new logic that depends on `action_state`.
The field exists to support the current prove-the-concept DAG UI while
`automation.runtime` is wired up as the canonical execution model.

### Edge Model — Current vs Target

Current: `predecessor_ids` / `successor_ids` are a self-referential Many2many
with no condition field. Edges are untyped (always execute on success).

Target: a `workflow.edge` model with `source_id`, `target_id`, `condition`
(always / on_success / on_error / expression), and `label`. This enables
conditional branching (IF nodes).

---

## automation.runtime (Execution Instance)

A single *run* of a workflow. Stores isolated execution context and drives
step-by-step progress through the DAG.

### Current Scope Restriction

`automation_id` has domain `[("model_name", "=", "base.automation")]`.
This restricts `automation.runtime` to automations whose target model is
`base.automation` itself — i.e., meta-workflows that orchestrate other
automations. This is **intentional by design**: the special carve-out in
`_check_action_server_model` for `model_name == "base.automation"` enables
cross-model server actions within such automations, making it the natural
container for orchestration workflows.

In the target architecture, every automation trigger (not just `on_hand`)
creates an `automation.runtime` instance and the domain restriction is lifted.

### Key Fields

| Field | Type | Purpose |
|-------|------|---------|
| `automation_id` | Many2one `base.automation` | The rule being executed |
| `partner_id` | Many2one `res.partner` | Primary partner context |
| `diff_partner_id` | Many2one `res.partner` | Secondary partner context |
| `company_id` | Many2one `res.company` | Company isolation |
| `multicompany_id` | Many2one `res.company` | Target company for cross-company ops |
| `currency_id` | Many2one `res.currency` | Monetary context |
| `amount` | Monetary | Operation amount |
| `reference` | Char | External reference |
| `date` | Date | Reference date |
| `state` | Selection | draft / in_progress / done / cancel |
| `line_ids` | One2many `automation.runtime.line` | Execution steps |
| `progress` | Integer (computed) | 0–100% completion |
| `progress_display` | Char (computed) | "3/5 steps" |

### State Machine

```
draft → in_progress → done
              ↓
           cancel
```

`action_start()`: creates `automation.runtime.line` records from the
automation's `action_server_ids`, sets first-in-sequence to `ready`.

`action_next_step()`: executes next `ready` line, auto-marks `done` if all
lines complete.

---

## automation.runtime.line (Execution Step)

One node's execution state within an `automation.runtime` instance.
Fully isolated per-execution — no shared state with the definition.

### Key Fields

| Field | Type | Purpose |
|-------|------|---------|
| `runtime_id` | Many2one `automation.runtime` | Parent execution |
| `action_id` | Many2one `ir.actions.server` | Node being executed |
| `name` | Char | Copied from action at creation |
| `sequence` | Integer | Execution order |
| `state` | Selection | waiting/ready/in_progress/done/cancel/error |
| `error_message` | Text | Error details |
| `predecessor_ids` | Many2many self | DAG dependency at execution level |
| `successor_ids` | Many2many self | Computed inverse |
| `is_ready` | Boolean (computed, stored) | All predecessors done |
| `created_record_ref` | Reference | Record created by this step |

### DAG Resolution

`action_mark_done()`: marks self done, then for each successor checks if all
its predecessors are done — if so, calls `successor.action_mark_ready()`.
This is the correct per-instance DAG propagation pattern (contrast with
`ir.actions.server.action_mark_done()` which mutates the global definition).

---

## flow.diagram (in web_flow)

Lives in `addons_custom/web_flow/models/flow_diagram.py`.
Stores BPMN 2.0 XML diagrams associated with any model/record.

| Field | Type | Purpose |
|-------|------|---------|
| `res_model` | Char | Model this diagram documents |
| `res_id` | Integer | Specific record (0 = model-level) |
| `diagram_xml` | Text | BPMN 2.0 XML content |
| `element_mappings` | Text (JSON) | BPMN element ID → Odoo record ID |

In the target architecture, `flow.diagram` becomes the *visual layout* layer
for `base.automation` workflows: one diagram per automation rule, with BPMN
elements mapped to `ir.actions.server` node IDs and `workflow.edge` IDs.
