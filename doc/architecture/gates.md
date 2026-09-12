# The gates — what is mechanically enforced, and what that is worth

> Referenced by [`ARCHITECTURE.md`](ARCHITECTURE.md). The architecture is in
> [`module.md`](module.md) and [`runtime.md`](runtime.md); this file is the
> operator's manual for the machinery that keeps them true.

**The `tooling/` tree — the layer contracts, the surface pins, the count
ratchets and their 84 floors, the HOOT warm runner, the sibling-repo lint
runner — was removed on 2026-09-11.** Nothing below refers to it. What is
enforced now is the standard tools on their pinned versions, the pytest tiers,
`test_lint`, and the DB-backed suites; every one runs by hand, and there is no
CI.

## Running the checks

```bash
ruff check odoo/ --no-cache                    # core package, hard zero
ruff check tests/ --no-cache                   # hard zero
ruff format --check tests/
npx eslint .                                   # whole repo
npx tsc --project tsconfig.json --noEmit       # whole repo
npx prettier --list-different "**/*.scss"
pytest                                         # Tier 1, from the repo root
pytest odoo/orm/tests odoo/http/tests odoo/db/tests odoo/tools/tests \
    tests/service tests/framework              # Tier 2, separate process
python odoo-bin -d <db> -i test_lint --test-enable --stop-after-init
```

`mypy` is measured with mypy alone installed (`ignore_missing_imports`
resolves `lxml`, `psycopg`, `dateutil` to `Any`), never in the shared venv,
over `odoo.orm`, `odoo.db`, `odoo.libs`, `odoo.http`, `odoo.service`,
`odoo.modules`, and separately `odoo.tools`, `odoo.cli`, `odoo.tests`.

**`test_lint`** holds the rules no general linter knows — SQL-injection
shapes, gettext discipline, N+1 query shapes, manifest and XML conventions,
record-field order. Its floors live in
`odoo/addons/test_lint/tests/floors.json`, one integer per gate; a gate with
no entry is a hard zero. `assert_ratchet` is exact: a count above the floor
fails, and a count below it fails until the floor is lowered in the same
change.

## What is not enforced any more

The eight layer contracts (`libs-is-dependency-free`, `db-is-orm-agnostic`,
`orm-components-are-pure-python`, the façade boundary, …) were held at zero by
`layer_check.py` and are now held by nothing but review. The same is true of
the public-surface pins (`env`, `pool`, the model member surface, the JS
extension surface), the cycle checks, the naming vocabulary, and every count
floor — function and class length, `computectx`, `fieldhooks`, `jsprivate`,
`translations`. Where a page in this directory states a figure or a contract
as *checked*, read it as *stated*: the checker that derived it is gone, and
the figure is as of the day it was last measured.

**DB-backed integration suites** — run against PostgreSQL 18, **each against
its own database**:

```bash
python odoo-bin --addons-path=odoo/addons,addons -d <db> -i <module> \
    --test-enable --test-tags /<module> --stop-after-init
```

The suites run this way, and what each covers: `base` (less the excluded
`TestReportsRendering` and `TestIrModelFieldsTranslation`), `test_http`,
`test_orm`, `mrp`, `certificate`, `stock`, `rpc`, `crm`, `data_recycle`,
`mixin_report_sql` with `test_mixin_report_sql`, `test_read_group`,
`test_access_rights`, `hr_work_entry` with `hr_work_entry_holidays`,
`hr_holidays`, the three `extract` branches, `test_base_order`,
`approval` with `test_approval`, `api_ai`, `project_hr`, `exchange`,
`date_range`, `account_coa`, `test_performance_compare`, `mail`, `test_mail`,
`mail_group` and `speech`. `rpc`, `mail`, `test_mail`, `mail_group` and `speech`
run **with** the HTTP server, because their `HttpCase` classes are the only
end-to-end coverage of what they test and none is a tour; the rest run
`--no-http`.

`test_orm` — **1,239 test methods** under its `tests/` directory — is the addon
written to test the ORM. Above all `test_domain_evaluator_parity.py`: the only
check that a `Domain` means the same to `search()` (SQL) and `filtered_domain()`
(the in-memory predicate), with a generative suite asserting the two evaluators
agree *or both refuse*. No DB-free tier can see a SQL/predicate divergence.

Running `test_orm` paid for itself on the first run:
`TestBackendDifferential.test_divergence_ilike_unaccent` asserted PostgreSQL's
`ilike` folds `Café` onto `cafe` without checking the `unaccent` extension is
installed. Every developer database inherits it from `db_template`; a bare
`template0` does not. It now skips on `registry.has_unaccent`.

Running `mrp` repaired a suite nobody ran: `3bcf5d144f9` deleted
`stock.move.availability` having found "no consumer anywhere in the workspace",
missed `addons/mrp/tests/test_order.py`, which asserts on it, and left that test
erroring — every assertion after the failing line unexecuted.

`test_read_group` (123 test methods, the only coverage of the five
`read_group/` units) and `test_access_rights` (55, record rules and ACLs) were
both green before anyone ran them — 123 of 123 and 52 of 52 with one
environment skip — so neither is a repair; they are coverage that existed and
ran nowhere. **A suite outside the set is a suite nobody runs.**

Method counts, not line counts. A suite's size is an argument about what the
set is missing, and raw lines churn on every edit inside it without moving that
argument — `test_orm` lost 68 lines between two runs an hour apart while its method
count did not move — quoted as method, not as a size, because the size is
stated once above and a second copy of it drifts.


### The limits of "enforced"

**The integration suites are the only thing that runs addon tests in Python.**
The boundary checkers are structural and DB-free: they read import graphs,
call graphs, reached-member sets and documents. A change can satisfy every one
of them, and Tier 1 and Tier 2, and still be wrong — renaming `OrmCore`'s slots
(`cache`/`engine` → `_cache`/`_engine`) broke two DB-backed addon tests in
2026-08 while every gate and both DB-free tiers stayed green. Read a green
boundary run as "the structure holds", never as "the framework works".

**The JS suites run through `WebSuite` and `MobileWebSuite`** in
`addons/web/tests/test_js.py`, addon tests like any other — but an integration
run that is `--stop-after-init` and `--no-http` skips both classes at
`setUpClass` and reports them as skipped, never as a pass and never as a
failure. They must run **under both presets**, desktop and mobile, because the
two presets select by tag and neither set is a superset of the other. Gate each
pass on its own passed-test **count** as well as on the exit code: a suite
contributing zero tests under a preset is not an error to the runner, so a
plan that narrowed to nothing would otherwise read as PASS. The cost of not doing so was not hypothetical: a `mobile`-tagged test in
`@web/ui/dialog_service` sat failing from the day it landed, invisible because
the desktop preset skips it by tag and nothing else ran it at all, and
`@hr/m2x_avatar_employee` failed 6 of 11 for as long as nothing ran it.

A suite outside the set is a suite nobody runs. When you add a test addon, run
it — **with its own database.** The suites interfere: `test_http`
depends on `mail`, whose `res_partner_views.xml` inherits
`base.view_res_partner_filter` anchored on `<filter name="inactive">`, and
base's `test_hard_reset_from_file_still_works` overwrites that view with a
minimal `<search>`. The write re-validates the children, so `-i base` is 5/5
green while `-i base,test_http` raises `ValidationError`.


## Known boundary exceptions

**None that are debt.** Two pinned rules, both
`core-does-not-depend-on-addons`, both scoped to `odoo.service`:
`service/_threaded.py` and `service/_worker.py` call `IrCron._process_jobs` /
`IrJob._process_jobs`, `@staticmethod` entry points that open their own cursor
because they run *before* a registry exists for the database, so there is no
`env` to route through. Both imports are deferred to call time, and no override
of either exists anywhere in `odoo`/`enterprise`/`agromarin`. Pinned rather than
allow-listed so they stay visible in every report.

The eight original contracts remain clean at zero. The exceptions the checker's
first run surfaced have all been paid down:

| Was | Now |
|---|---|
| Asset pipeline (`esbuild`, `esm_bridges`, `esm_graph`, `esm_registry`) in `libs/` | relocated to `odoo/tools/assets/`, being Odoo-coupled. `asset_log` remains in `libs/` and is genuinely dependency-free. `constants` was kept beside it on the same reasoning and should not have been — it held 24 import-map asset paths (two into the optional `spreadsheet` and `survey` addons), the ORM prefetch and vacuum limits, and the `ir.cron`/`ir.job` NOTIFY channel names, with every consumer in `tools/`, `orm/`, `addons/base` or an addon tree. `libs-is-dependency-free` was green throughout, because a string literal produces no import edge. Split 2026-08-09 into `tools/assets/constants.py`, `orm/primitives.py` and `tools/constants.py`; the import-map builder moved to `tools/assets/import_map.py` |
| `libs/filesystem/osutil.py` imported `odoo.release` | the Windows service name is passed in by the caller |
| Layer-1 → Layer-2 deferred `BaseModel` imports in `orm/domain/ast.py` and `orm/fields/relational/` (since split into `_base`, `many2one`, `one2many`, `many2many`) | replaced by the `orm/_recordset.py` injection seam; what remains is `if TYPE_CHECKING:`-guarded annotation, which never executes |
| `MODULE_UNINSTALL_FLAG` in `addons/base/models/ir_model_common` | moved to `orm/primitives` (the ORM's `unlink` branches on it), re-exported from the addon for the `ir_model*` / `ir_module` code that sets it |
| `format_number`, `intersperse`, `split`, `parse_grouping` in `addons/base/models/res_lang`, reached twice from `tools/formatting.py` | moved to `libs/locale/number_format`; locale data arrives through a `LocaleConventions` **Protocol**, so `libs/` stays dependency-free while the addon's `LangData` satisfies it structurally |
