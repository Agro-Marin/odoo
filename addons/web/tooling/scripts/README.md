# Fast warm-server HOOT runner

A warm-server test runner for the web module's HOOT (JS unit) suites, built to
replace the slow `odoo-bin --test-tags /web:WebSuite.test_X` edit/run loop.

The classic loop pays a **fixed cost on every run**: boot the whole ERP + DB
(`HttpCase`), then build the ESM test bundle, *then* run the (fast) tests. These
scripts pay that cost **once**: they keep one Odoo dev server warm across
invocations and drive Chrome against it with Odoo's own `ChromeBrowser` CDP
driver (imported from `odoo.tests.common` — not reinvented).

Everything here runs with the workspace venv
(`/home/marin/Odoo/venv/p314o19marin/bin/python`, hard-coded in the shebangs).

## Files

| File | What |
|------|------|
| `hoot` | Main CLI: warm-server lifecycle + run suites (+ `--affected`, `--watch`). |
| `hoot-affected` | Print the `@web/...` suites affected by changed JS files. |
| `hoot_lib.py` | Shared library (hash, server lifecycle, Chrome driver, import-graph). |

State/logs are written next to the scripts: `.hoot_state.json` (warm-server
pid/port/db) and `.hoot_logs/` (server + init logs). Both are throwaway.

## Usage

```bash
cd addons/web/tooling/scripts

./hoot '@web/core/domain'            # run one file's suite
./hoot '@web/services' '@web/model'  # several suites
./hoot '@web/core'                   # a whole category (coarse id)
./hoot '@mail/discuss' '@bus'        # ANY addon's suites (see below)
./hoot --affected                    # only suites touched by your git diff
./hoot --affected path/to/file.js    # ...or by explicit changed files
./hoot --watch '@web/core/domain'    # re-run on any web JS change
./hoot --watch --affected            # watch + re-select affected each change

./hoot --status                      # status of ALL warm servers
./hoot --stop [--db hoot_mail]       # stop warm server(s) (keep DB); one DB if --db
./hoot --clean [--db hoot_mail]      # stop warm server(s) AND drop DB(s)
./hoot --restart '@web/core/domain'  # force a fresh server, then run
./hoot -v '@web/core/domain'         # verbose (server + browser logs)
./hoot --help
```

### Any addon, not just web

The suite prefix (`@<addon>/…`) selects the addon, and the runner installs the
matching module into a **per-module-set warm database** so several addons' suites
can run without colliding:

| Suites requested | Modules installed | Warm DB |
|---|---|---|
| `@web/...` (default) | `web` | `hoot_web` |
| `@bus/...` | `bus` | `hoot_bus` |
| `@mail/...` | `mail` (→ pulls `bus`, `html_editor`) | `hoot_mail` |
| `@bus` `@mail` together | `bus` + `mail` | `hoot_bus_mail` |

Each DB gets its own warm server on its own port and its own `.hoot_state_*.json`,
so runs for different addons coexist. `--db <name>` overrides the derived DB (e.g.
reuse `hoot_bus_mail` for `@mail` suites so you skip the ~5-min `mail` install).
A DB that exists but is missing a needed module is topped up automatically.

A suite path is hashed with the **exact** algorithm from
`web/tests/test_js.py::_generate_hash` and passed as an `&id=` filter to
`/web/tests`. HOOT resolves each id against a suite *or* a single test, so a full
test path also works:

```bash
./hoot '@web/core/domain/Basic Properties/empty'   # one test
```

The first invocation creates a dedicated database (`hoot_web`, base + web
installed), boots a threaded server on the first free port in **8085-8089**, and
builds the bundle on first navigation. Every later invocation reuses that warm
server and the cached bundle. Ports 8069 and the `wjsaudit` DB are never touched.

## Affected-suite selection

`hoot-affected` / `hoot --affected` maps changed JS files to the minimal set of
HOOT suites to run, using a conservative ESM import-scan of the fork's `@addon/…`
specifiers (see `web/machine_doc_v1/ESM_BUNDLING.md`):

* a changed `*.test.js` file → its own suite;
* a changed `src` file → every test file that imports it **directly**, plus test
  files that import a `src` file which imports the changed file (**one hop**).

The suite name is derived exactly as `tests/_framework/start.hoot.js`
(`_suiteNameFromSpecifier`) does, e.g. `web/static/tests/core/domain.test.js` →
`@web/core/domain`, so the ids match what the real test loader registers.

With no arguments the changed set is `git diff --name-only HEAD` inside
`addons/odoo`, filtered to files under a `static/` tree.

## `--watch`

`--watch` polls the mtimes of every `*.js` under each addon's `static/src` and
`static/tests` (1s interval) and re-runs on change. Combine with `--affected` to
re-select the affected suites from just the files that changed. Ctrl-C exits.
(Simple mtime poll — no esbuild watch integration; the warm server rebuilds the
bundle itself when source changes.)

## Measured speedup

Numbers below were measured on this dev box (fast NVMe/CPU, so the absolute ERP
boot here is ~10-13s; on slower/CI environments the boot dominates far more and
the warm win is proportionally larger).

| Scenario | Classic `odoo-bin --test-tags` | Warm `hoot` |
|----------|-------------------------------|-------------|
| One-time DB create (base+web) | — | ~10 s (once) |
| Warm server cold boot | — | ~12 s (once, first invocation) |
| `@web/services` (233 tests), same work | **25.5 s** (boot+bundle+test every run) | **~17 s** (2nd+ run) |
| `@web/core` (1405 tests) | **40 s** (`test_core`) | **~37 s** |
| **Iterate on `core/domain.js` (49 tests)** | **40 s** — classic can only run the whole `test_core` method | **~5 s** — run just `@web/core/domain` |

The headline win is the **edit loop on a single file**: the classic harness's
finest granularity is a `WebSuite.test_*` *method* (e.g. `test_core` = the entire
`@web/core` category, 40 s), whereas the warm runner drives a single file's suite
(`@web/core/domain`, ~5 s) with **zero** per-run ERP boot or bundle rebuild —
roughly an 8x loop speedup here, and much more where booting the ERP costs the
30-60 s+ described in the original loop.

## How it works (short version)

1. `hoot_lib.boot_server` starts one `odoo-bin` (threaded, `workers=0`) on a
   free 8085-8089 port and records it in `.hoot_state.json`. Later runs detect
   the live pid + HTTP port and reuse it.
2. `run_suites` authenticates over HTTP (admin/admin) to get a `session_id`,
   then instantiates `odoo.tests.common.ChromeBrowser` through a tiny shim
   (it only needs `_logger`, `browser_size`, `touch_enabled`, `fetch_proxy`),
   sets the session cookie, and navigates to
   `/web/tests?headless&loglevel=2&preset=…&timeout=…&id=<hash>…`.
3. Success/failure is detected exactly as the real suite does: the
   `[HOOT] Test suite succeeded` signal + the `unit_test_error_checker`. Console
   output is captured to report pass/fail counts and failed test names.

Nothing in Odoo core is modified; `ChromeBrowser` is imported and driven as-is.

## CI entry points (gated runs through `odoo-bin`)

The warm runner is for the local edit/run loop. CI runs the same suites through
`odoo-bin --test-tags`, driven by a `test_js.py` per addon that reuses
`web/tests/test_js.py::HOOTCommon` and selects that addon's `@…` suites:

| Addon | File | Tag | Selects |
|---|---|---|---|
| web | `web/tests/test_js.py` | `web_js` | `@web/*` (+ `@html_editor`), granular methods + coverage walk |
| bus | `bus/tests/test_js.py` | `bus_js` | `@bus` (one selector covers the whole tree) |
| mail | `mail/tests/test_js.py` | `mail_js` | `@mail/*`, fanned out + coverage walk |

```bash
# CI-style (boots the ERP; slow — use the warm runner above for the dev loop):
odoo-bin -c <conf> -d <db> -i bus  --test-enable --test-tags '/bus:BusSuite.test_bus_desktop'   --stop-after-init
odoo-bin -c <conf> -d <db> -i mail --test-enable --test-tags 'mail_js'                           --stop-after-init
```

Each `test_suite_filters_cover_every_test_file` walk fails the build if a new
`static/tests` directory is added without being wired into a run method, so
suites can never silently stop running (the failure mode that once lost 13 web
test files).
