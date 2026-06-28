# ADR-0007: DB-backed integration test gate

- **Status:** Accepted
- **Date:** 2026-06-25

## Context

The fork has an excellent *static* safety net — six architectural boundary
contracts (ADR-0001…0005) and, now, drift-zero count ratchets (ADR-0006) — and a
fast *DB-free* unit tier (`unit_tests.yml` runs `orm/components`,
`_field_access`, and the `model_test_env` self-tests). But **no CI workflow ran a
single `TransactionCase` or `HttpCase`.** The entire traditional, database-backed
suite — every test in `odoo/addons/*/tests/` that needs a real registry and real
SQL — never executed on a pull request.

That is a large hole precisely because of how much this fork has restructured.
The ORM was decomposed into layers, `sql_db.py` into `db/`, `http.py` into
`http/`, and the cache/compute engine into injected components. Static checks
prove the *import graph* is acyclic and the layers don't reach across; ratchets
prove types and lint don't regress. Neither proves the decomposed pieces still
*behave* correctly when wired together against PostgreSQL — exactly the property
most at risk during aggressive refactoring. A regression in
`orm/runtime`, `orm/models`, `modules/loading`, or `http/` could merge green.

## Decision

Add `integration_tests.yml`: a workflow that boots a real **PostgreSQL 18**
service, builds and installs the `odoo_rust` extension, installs the runtime
requirements, and runs the **`base` module's test suite** end-to-end with
`odoo-bin --test-enable --test-tags /base --stop-after-init`.

Scope is a deliberate framework **smoke**, not the whole suite. The `base` suite
exercises the registry, environment, fields, domains, module loading, and access
rules against real SQL — the highest-value-per-minute coverage of the decomposed
core. The workflow parameterises `INSTALL` / `TEST_TAGS` so coverage can broaden
(`test_orm`, `test_http`, …) once timing is understood.

The database is created with `--db-template=template0`, because Odoo only applies
its `ENCODING 'unicode' LC_COLLATE 'C'` creation path on `template0`
(`odoo/service/db.py`); PostgreSQL 18's default `template1` locale would
otherwise yield non-deterministic ordering. Test failures fail the job directly:
`odoo-bin` propagates the assertion report's result as the process exit code
(`odoo/cli/server.py`), so no log-scraping is needed.

## Consequences

- Behavioural regressions in the framework core are caught on the PR that
  introduces them, not in a downstream environment. This is the safety net that
  makes the deeper in-layer refactors (dissolving the BaseModel mixins, the
  `Environment` and `Field` god-objects) tractable to land incrementally.
- New cost: the lane is heavier than the DB-free tiers (Rust build + full
  requirements + a PostgreSQL service), bounded here at 30 minutes. It is scoped
  to a smoke for that reason and triggered only on changes under the framework
  paths and `base`.
- A smoke is not full coverage. The `INSTALL`/`TEST_TAGS` knobs make broadening
  explicit and reviewable rather than silently partial.

## Enforcement

`integration_tests.yml` runs on every PR touching `odoo/orm`, `odoo/db`,
`odoo/http`, `odoo/service`, `odoo/modules`, `odoo/addons/base`, or the Rust
crate, and blocks on any test failure. Reproduce locally with a disposable
`postgres:18` and the `odoo-bin` invocation in the workflow (note the
`--db-template=template0` requirement for C collation).
