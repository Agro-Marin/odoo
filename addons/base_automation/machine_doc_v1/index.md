# base_automation — Machine Documentation v1

## Purpose

`base_automation` is the **workflow engine** for this Odoo fork. It is being
evolved into an n8n-style visual workflow manager: DAG-based, per-execution
isolated, with typed nodes and full execution history.

This is a **strategic core module**. It sits at the intersection of the ORM
trigger system and async infrastructure. Upstream Odoo removed their workflow
engine in v11; this module fills that gap with a modern design.

**The engine exists; the canvas does not.** Nodes, edges, cycle and scope
constraints, topological ordering, per-execution runtimes and per-step state are
all implemented. There is no visual editor and no library chosen for one — see
[`vision.md`](vision.md) Decision 1, reopened 2026-08-26.

## Files at a Glance

| File | Purpose |
|------|---------|
| `models/base_automation.py` | Rule definition, trigger system, ORM patching, cron |
| `models/ir_actions_server.py` | Node extension: DAG edges (`predecessor_ids` / `successor_ids`), cycle and scope constraints, `_sorted_by_dependency` |
| `models/automation_runtime.py` | Per-execution instance: state, progress, line orchestration |
| `models/automation_runtime_line.py` | Per-step execution state within a runtime instance |
| `models/ir_cron.py` | Thin bridge: cron → `action_open_automation()` |
| `controllers/main.py` | Webhook HTTP endpoint (`/web/hook/<uuid>`) |
| `tests/test_automation.py` | Core trigger tests (`@tagged post_install`) |
| `tests/test_triggers.py` | All trigger types (no `@tagged`, runs at-install) |
| `tests/test_workflow_dag.py` | DAG dependency and orchestration (no `@tagged`) |
| `tests/test_mail_composer.py` | Mail trigger tests |
| `tests/test_webhook_security.py` | Webhook authentication and rate limiting (`@tagged post_install`) |
| `tests/test_webhook_decrypt_budget.py` | Webhook payload decryption budget |
| `tests/test_inbound_access_log.py` | Inbound access logging |
| `tests/test_audit_regressions.py` | Regressions from the audit, webhook cases as `HttpCase` (`@tagged post_install`) |

## Related Modules

None. Earlier revisions listed a `web_flow` module in `agromarin/` as the visual
DAG editor. It was **deleted as unused** by `agromarin` `60b5a7eef` (2026-04-21)
four months before this line was corrected — see [`vision.md`](vision.md)
Decision 1 for the removal rationale, which constrains its replacement.

## Read Next

- [`models.md`](models.md) — All models, fields, relationships, known issues
- [`architecture.md`](architecture.md) — Trigger system, hook patching, execution flow
- [`vision.md`](vision.md) — n8n target, phased roadmap, design decisions
- [`conventions.md`](conventions.md) — Naming, patterns, gotchas, what NOT to do
