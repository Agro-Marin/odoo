# ADR-0007: DB-backed integration test gate

- **Status:** Accepted
- **Date:** 2026-06-25

## Context

The fork has a strong *static* net — the boundary contracts of ADRs 0001–0005,
the count ratchets of ADR-0006 — and a fast DB-free unit tier (`unit_tests.yml`
runs `orm/components`, `_field_access` and the `model_test_env` self-tests).
**No workflow ran a single `TransactionCase` or `HttpCase`.** Every test needing
a real registry and real SQL never executed on a pull request.

That gap matters in proportion to how much has been restructured: the ORM into
layers, `sql_db.py` into `db/`, `http.py` into `http/`, the cache/compute engine
into injected components. Static checks prove the import graph is acyclic;
ratchets prove types and lint do not regress. Neither proves the pieces still
behave when wired together against PostgreSQL. A regression in `orm/runtime`,
`orm/models`, `modules/loading` or `http/` could merge green.

## Decision

Add `integration_tests.yml`: boot PostgreSQL 18, build and install `odoo_rust`,
install the runtime requirements, run the `base` suite with
`odoo-bin --test-enable --test-tags /base --stop-after-init`.

Scope is a deliberate framework **smoke**. `base` exercises the registry,
environment, fields, domains, module loading and access rules against real SQL
— the highest coverage per minute of the decomposed core. `INSTALL` /
`TEST_TAGS` are parameterised so coverage can broaden once timing is understood.

The database is created with `--db-template=template0`: Odoo applies its
`ENCODING 'unicode' LC_COLLATE 'C'` creation path only on `template0`
(`odoo/service/db/lifecycle.py`; it was service/db.py when this was written —
see ADR-0014), and PostgreSQL 18's default `template1` locale would give
non-deterministic ordering. `odoo-bin` propagates the assertion report as its
exit code (`odoo/cli/server.py`), so no log-scraping is needed.

## Consequences

- Behavioural regressions in the core are caught on the PR that introduces
  them. This is what makes the deeper in-layer refactors — dissolving the
  BaseModel mixins, the `Environment` and `Field` god-objects — landable
  incrementally.
- Cost: heavier than the DB-free tiers (Rust build, full requirements, a
  PostgreSQL service), bounded at 30 minutes, hence the smoke scope and the
  path filter.
- A smoke is not full coverage. The `INSTALL`/`TEST_TAGS` knobs make broadening
  explicit rather than silently partial.

## Enforcement

`integration_tests.yml` runs on every PR touching `odoo/orm`, `odoo/db`,
`odoo/http`, `odoo/service`, `odoo/modules`, `odoo/addons/base` or the Rust
crate, and blocks on any failure. Reproduce with a disposable `postgres:18` and
the workflow's `odoo-bin` invocation, including `--db-template=template0`.

## Amendments

### 2026-08-07 — the lane has broadened, using the knobs this decision added

`integration_tests.yml` runs two suites: `base` (less `TestReportsRendering`
and `TestIrModelFieldsTranslation`) and `test_http`, each against its own
database (`-d ci_smoke`, `-d ci_http`). Separate databases are load-bearing —
the suites interfere, and `doc/architecture/ARCHITECTURE.md` records the
`res_partner_views.xml` / `test_hard_reset_from_file_still_works` collision that
proves it. Recorded, not corrected: this is the decision working as intended.
`--db-template=template0` is still passed by both runs.

### 2026-08-07 — the architecture front door moved to `doc/architecture/`

This record cited the front door at the path it held inside the core package
until 2026-08-07. That page described the whole repository — its gate catalog
covers `addons/**` JS and the repo-wide `eslint`/`tsc` ratchets — while filed
one level below its own scope. Widening `doc_link_gate.py` to the set found 15
broken references. The set is now one flat directory, `doc/architecture/`.
Corrected in place: the Consequences pointer to where the suite-interference
collision is recorded.
