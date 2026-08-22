# Fast warm-server HOOT runner

A warm-server test runner for the web module's HOOT (JS unit) suites, built to
replace the slow `odoo-bin --test-tags /web:WebSuite.test_X` edit/run loop.

The classic loop pays a **fixed cost on every run**: boot the whole ERP + DB
(`HttpCase`), then build the ESM test bundle, *then* run the (fast) tests. These
scripts pay that cost **once**: they keep one Odoo dev server warm across
invocations and drive Chrome against it with Odoo's own `ChromeBrowser` CDP
driver (imported from `odoo.tests.common` — not reinvented).

Everything here runs with the workspace venv: the CLI shebangs are
self-locating trampolines that pick the single venv under `<workspace>/venv/`
(override with `$ODOO_VENV_PYTHON`; config resolution follows the
`config/<venv-name>.conf` convention, override with `$ODOO_CONF`).

## Files

| File | What |
|------|------|
| `hoot` | Main CLI: warm-server lifecycle + run suites (+ `--affected`, `--watch`). |
| `hoot-affected` | Print the `@web/...` suites affected by changed JS files. |
| `hoot_lib.py` | Shared library (hash, server lifecycle, Chrome driver, import-graph). |

State/logs are written next to the scripts: `.hoot_state.json` (warm-server
pid/port/db) and `.hoot_logs/` (server + init logs, plus the `.port_*.lock` and
`.boot_*.lock` files the runner `flock`s). All throwaway — but delete a `.lock`
only when nothing is running, since removing one a live process holds open lets
the next process lock a fresh inode and pick a port, or boot a db, that is
already taken.

## Usage

```bash
cd tooling/hoot

./hoot '@web/core/domain'            # run one file's suite
./hoot '@web/services' '@web/model'  # several suites
./hoot '@web/core'                   # a whole category (coarse id)
./hoot '@mail/discuss' '@bus'        # ANY addon's suites (see below)
./hoot --affected                    # only suites touched by your git diff
./hoot --affected path/to/file.js    # ...or by explicit changed files
./hoot --affected --downstream       # ...plus affected suites in OTHER addons
./hoot --isolate '@web/ui' '@web/model'   # one page load per suite, as CI runs them
./hoot --watch '@web/core/domain'    # re-run on any web JS change
./hoot --watch --affected            # watch + re-select affected each change

./hoot --preset mobile '@web/webclient'   # mobile-tagged tests (see below)

./hoot --status                      # status of ALL warm servers
./hoot --stop [--db hoot_mail]       # stop ONE warm server (keep its DB)
./hoot --clean [--db hoot_mail]      # stop ONE warm server AND drop its DB
                                     #   (and its filestore)
./hoot --stop --all                  # stop EVERY warm server (all sessions),
                                     #   orphans included (see Orphans below)
./hoot --restart '@web/core/domain'  # force a fresh server, then run
./hoot -v '@web/core/domain'         # verbose (server + browser logs)
./hoot --help
```

### Presets (`--preset desktop|mobile`)

Runs default to `desktop`. The preset is more than a URL flag: the runner also
resizes Chrome (1366x768 / 375x667) and toggles touch emulation, because HOOT
reads the real `innerWidth` and responsive components branch on it.

Tests are selected by **tag**, not by directory, so the two presets execute
different sets — overlapping, and neither a superset of the other. Measured on
the same suite lists (2026-07-30): `@web/webclient` is 870 tests under desktop
and 345 under mobile; `@web_enterprise/webclient @web_enterprise/views
@web_enterprise/mobile` is 54 and 35. Verifying a change means running the same
suite list under both. Re-measure after moving tests between addons rather than
trusting these numbers — they drift, and a stale count reads as a regression.

A suite contributing **zero** tests under the current preset is not an error:
the run only fails closed when the *whole* selection matches nothing. So

```bash
./hoot '@web_enterprise/webclient' '@web_enterprise/mobile'   # desktop preset
```

reports PASS having never executed one of the two. Gate on the per-preset test
count, not on the exit code alone.

The runner now says so rather than leaving that to the reader: a passing desktop
run whose selection contains files owning `mobile`-tagged tests prints the count
and the command to run them. It was written after a `mobile`-tagged test in
`@web/ui/dialog_service` was found failing having never been executed by anything
-- the desktop preset skips it by tag, and no workflow invokes `MobileWebSuite`.

### Bundle scoping (`&module_scope=`)

When every requested suite belongs to one addon, the runner passes
`&module_scope=<addon>`, exactly as `web/tests/test_js.py` does, and
`ir.asset._get_addons_active` narrows the bundle to that addon's manifest
closure. This is not an optimisation: unscoped, the unit-test page executes the
`src` of every *installed* addon, and those `patch()` calls are global and
unconditional. A test asserting its own addon's RPCs then sees a step issued
from outside its closure — `@web/views/fields/properties_field` failed here for
exactly that reason (`html_editor` patches `PropertyValue` to call `has_group`,
and `html_editor` depends on `web`, so the `web_js` gate never loads it) while
passing under `odoo-bin`.

Runs spanning several addons have no single closure and stay unscoped, so a
cross-addon run can still see foreign `src`. If a failure appears here but not
under `odoo-bin --test-tags '/web:WebSuite.test_<x>'`, suspect scope first.

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
specifiers (see `addons/web/machine_doc_v1/ESM_BUNDLING.md`):

* a changed `*.test.js` file → its own suite;
* anything else → every test file that imports it **directly**, plus test
  files that import a `src` file which imports the changed file (**one hop**).

The suite name is derived exactly as `tests/_framework/start.hoot.js`
(`_suiteNameFromSpecifier`) does, e.g. `web/static/tests/core/domain.test.js` →
`@web/core/domain`, so the ids match what the real test loader registers.

**Only `*.test.js` names a suite, and the second rule is why.** `static/tests/`
holds two unrelated bundles: `*.test.js` goes to `web.assets_unit_tests`, which
is HOOT, while `tests/tours/*.js` goes to `web.assets_tests`, which odoo-bin
drives as browser tours. A tour is therefore not a suite, and neither is a shared
helper. Selecting one used to mint an id the loader never registers, and the
runner answered by refusing the **whole** run — `no suite or test matches ids
"…": refusing to fall back to running every test` — so a change touching one
tour alongside ten real suites reported `0 failed / 0 passed`, which reads like
a clean pass. They now flow through the import scan instead, which is also what
makes a changed helper select the suites that actually use it.

The scan covers **every addons-path root**, not just `addons/odoo/addons`. It
used to stop there, so a changed `src` file in any of the 84 enterprise or 4
agromarin modules that ship HOOT tests produced an empty list — indistinguishable
from "nothing to run". With no arguments the changed set is
`git diff --name-only HEAD` in **each** repository backing the addons path
(they are four separate checkouts), filtered to files under a `static/` tree.

Widening the graph also means a core file legitimately reaches ~100 suites across
a dozen addons — more than a warm DB should install for an edit loop. By default
only suites owned by the addons you actually edited are selected; `--downstream`
returns the full set.

> In this workspace several sessions share one worktree, so a bare `--affected`
> picks up **everyone's** uncommitted changes (272 suites at the time of
> writing). Pass your own paths explicitly.

## `hoot-shard` — what it schedules, and why it isolates

The suite list is **read from `web/tests/test_js.py`**, not restated. It used to
be a hand-kept copy marked "KEEP IN SYNC" and had drifted: `@html_editor` (4766
tests, 494 s — over a third of the desktop pass) and `@web/libs` were missing, so
a run presenting itself as the full web suite covered 66% of the tests.
`WebSuite.test_shard_runner_covers_ci` now fails the build if the resolved plan
stops covering a test file CI runs.

Any suite too heavy to balance is **split into its child suites** — a whole-addon
id is one serial page load however long it runs, so `@html_editor` alone (494 s,
against 620 s for all 36 other web suites combined) pinned one shard while the
rest idled. It becomes 65 schedulable units. Unknown suites are weighted by test
file count rather than a flat constant, which is what let a 494 s suite look like
a 30 s one.

Each shard runs **one suite per page load** (`hoot --isolate`), because batched
suites do not give CI's answer in either direction. Batching `@web/views/fields`
with eight others failed 7 daterange/datetime/statusbar tests deterministically
on both presets — those same suites pass alone (1343 tests), exactly as
`WebSuite.test_fields` runs them — and separately *masked* 2 real
`form_save_coordinator` failures that a solo run surfaces. A further 4 desktop
and 1 mobile failures came from CPU contention between concurrent shards and did
not reproduce on an idle box. Isolation costs ~4% and removes all of it.

`--preset mobile` narrows the plan to the file suites that own a mobile test, by
calling `MobileWebSuite`'s own `_mobile_suites_under` (via `hoot_lib.mobile_suites`)
rather than restating it — the same read-from-the-runner rule the suite list
follows. That narrowing landed in `test_js.py` but not here, so a bare
`hoot-shard --preset mobile` still re-ran the desktop pass at 375x667: 9467 tests
in 258 s instead of 2229 in 108 s. Worse, it read as a *failure* — a suite owning
no mobile test resolves to an empty `&id=` filter, which `hoot` reports as
`matched no tests: failing closed`, so three of four shards printed `FAIL` while
carrying zero failed tests. Explicit suites are never narrowed, matching
`MobileWebSuite._run_hoot`.

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

### Full-suite runs (measured 2026-07-30, this box, `-j 4`)

| | before | after |
|---|---|---|
| desktop tests scheduled | 9 367 (66% — `@html_editor` and `@web/libs` were missing) | **14 209 (100%)** |
| desktop wall | 192 s | **311 s** |
| failures reported | 11, none reproducible outside the shard runner | **0** |
| mobile tests | 9 393 | **2 225** |
| mobile serial | ~875 s | **261 s** |

Desktop got slower per test because it now runs the whole suite and gives each
suite its own page; mobile got 3.4x faster because it stopped re-running the
desktop suite at 375x667. Combined serial runtime went from ~1 992 s to
~1 477 s **while covering a third more tests**.

## How it works (short version)

1. `hoot_lib.boot_server` starts one `odoo-bin` (threaded, `workers=0`) on a
   free 8085-8089 port and records it in `.hoot_state.json`. Later runs detect
   the live pid + HTTP port and reuse it.
1b. The server boots with `--dev=assets`, so it watches its own asset sources
   over inotify and drops the assets cache when one changes. The runner does
   nothing per-run. See "Why `--dev=assets`" below.
1c. On a boot (never on a reuse), `warm_bundles` fetches `/web/tests` once per
   `&module_scope=` the run will use and pulls every asset URL the page links,
   so the bundle build finishes before the first suite is timed. A port that
   answers is not a server ready to run tests: the build otherwise lands inside
   the first page load, and under `-j 4` four of them land at once. A cold
   desktop run reported 24 failures — every one in the *first* suite of its
   shard (datetime_field, list_view selection, load_state, domain_selector) —
   where the same plan on the same servers, warm, gave 0 failed / 14352 passed.
   Warming costs ~13 s per boot and made the cold run green.
2. `run_suites` authenticates over HTTP (admin/admin) to get a `session_id`,
   then instantiates `odoo.tests.common.ChromeBrowser` through a tiny shim
   (it only needs `_logger`, `browser_size`, `touch_enabled`, `fetch_proxy`),
   sets the session cookie, and navigates to
   `/web/tests?headless&loglevel=2&preset=…&timeout=…&id=<hash>…`.
3. Success/failure is detected exactly as the real suite does: the
   `[HOOT] Test suite succeeded` signal + the `unit_test_error_checker`. Console
   output is captured to report pass/fail counts and failed test names.

The runner patches nothing at runtime; `ChromeBrowser` is imported and driven
as-is. It does rely on one core capability added for it — the `--dev=assets`
watcher described next — which is a normal dev-mode feature, not a hook for
these scripts.

### Why `--dev=assets`

The warm server boots `--dev=assets,qweb`, deliberately **without** `xml`. Both
flags give the same live reload; they differ in how.

`--dev=xml` does not *invalidate* the asset caches, it *disables* them:
`base/models/ir_qweb_assets.py` guarded four ormcaches with
`@tools.conditional("xml" not in tools.config["dev_mode"], ormcache(...))`, so
every `/web/tests` navigation recomputed the asset links and the ESM payload
from scratch. Measured interleaved on two disposable databases with a same-flag
control: 0.62 s per render without `--dev`, 0.73 s with `qweb`, **3.15 s with
`xml`**. `qweb` alone is free (it only sets a render-context flag in `ir_qweb`),
so it is kept; `xml` was the entire cost.

`--dev=assets` instead gives the caches the input they were missing — *when did
the sources change*. `service/_watcher.py` already watched the addons path over
inotify for `--dev=reload`; under `assets` a changed `static/` source invalidates
the assets cache instead of restarting the process. It does so by writing an
`orm_signaling_assets` row rather than clearing in place, so it reaches every
process through the `Registry.check_signaling` that `http/_serve.py` runs at the
start of each request — including forked children under `--workers`, which the
watcher thread (living in the prefork master) shares no registry with. Because
that causal signal now exists, `_save_esm_attachment` no longer infers "the sources changed" from "a
rebuild produced a different artifact" — an inference that discarded the entries
the same request had just computed, costing a second full recompute. The render
sequence after one edit went from `slow, slow, fast` to `slow, fast, fast`.

Measured against a `--dev=xml,qweb` server on the same database, interleaved:
**3.95x** faster with no edit between runs, **1.39x** on the render right after
an edit.

Under `assets` the watcher is narrowed to `static/{src,tests}`, which costs
~5.8k inotify watches per server instead of ~20.8k for the whole addons tree.
That matters: `fs.inotify.max_user_watches` (65536 by default) is per *user* and
shared with your editor, so at the wide count a third warm server fails to
start — which `hoot-shard -j 6` would hit every run. `--dev=reload` still
watches the trees whole, since it must see every `.py`. If the watcher cannot
start at all the server now logs a warning and runs without it instead of
crashing, so check for that before concluding an edit "wasn't picked up".

A server left over from before this change carries different `--dev` flags, so
`ensure_server` detects it from `/proc/<pid>/cmdline` and recycles it once,
automatically.

### Four ways this runner returns a wrong answer

Each cost real time before it was written down. Two of the four are silent, one
announces itself, and the fourth returns no answer at all -- which is the one
most likely to be read as a hang in the code.

**A server with no watcher serves the sources as they were at boot.** The
warning above is emitted by `service/lifecycle.py` and, reaching only the server
log, was routinely missed during an otherwise green run. `hoot` now repeats it
on stdout on both the boot and the *reuse* paths — reuse is where it bites,
because `Reusing warm server` reads like everything is fine while the bundle is
frozen. If you see it, you are testing stale code: a fix you just wrote can
report FAIL, and a defect you just reverted can report PASS.

`fs.inotify.max_user_watches` is per **user**, shared with your editor and with
every other warm server; `hoot --status` lists them. Fifteen at once exhausted
the default 65536 on this box and three servers booted watcherless. Stop some
(`hoot --stop --db <name>`) or raise the limit, then `hoot --restart`.

**`--restart` while another run is in flight corrupts that run.** The bundle is
rebuilt under a browser that is mid-suite, and the result is mass failures in
whatever happened to be executing — ~200 kanban tests in the case that produced
this note, none of them real; the same suite passed 360/360 immediately
afterwards, both with and without the change under test. When a run reports
failures wildly out of proportion to the change, check whether anything
restarted the server underneath it before debugging the failures themselves.

**The server can die on its own, and every test after it fails on a fetch.**
Distinct from the `--restart` case above: nothing restarted it, it simply went
away. Measured 2026-08-19 -- `@web/ui` alone, same sources and the same warm
server, five consecutive runs:

    409 passed   409 passed   409 passed   127 failed / 282 passed   246 failed / 163 passed

The red runs are not truncated -- 127 + 282 = 409 -- so every test ran and a
quarter of them failed, twice, with the scope and the order identical each time.
Every failure carried one stack, and nothing under test appears in it:

    TypeError: Failed to fetch
      at fetchModelDefinitions (tests/_framework/module_set.hoot.js:240)
      at MockServer._loadModels (mock_server.js:1017)

The server log says why: `OSError: [Errno 28] inotify is out of capacity`. Note
which limit: this is `fs.inotify.max_user_instances` (**128**), not the
`max_user_watches` above. Exhausting *watches* boots a server without a watcher,
which is the stale-sources case; exhausting *instances* kills it. 92 of the 128
were held by the desktop session and two editors at the time, so a booting hoot
server is what tips it over.

`hoot` now asks, after every run, whether the server it ran against is still
**that** server -- the pid it started with, not merely a warm one on that
database, because a concurrent session rebooting a died server would otherwise
answer yes. When it is not, the run is reported as **VOID** rather than FAIL,
with no test names, because they are not evidence:

    VOID  @web/ui  (THE WARM SERVER DIED DURING THIS RUN — 127 failed / 282 passed, 31.4s)

`hoot-shard` parses that status rather than folding it into FAIL, so one dead
server does not read as a shard's failures. There is deliberately no automatic
retry: it would hide the cause and cost a second run of whatever the box could
not afford the first time.

**A run that prints the warning and then nothing is queued, not hung.** `hoot`
serialises on the warm server, so an invocation made while another session holds
it blocks *before* printing `Reusing warm server` -- and a narrower scope started
later, once the holder finishes, returns in seconds. That combination reads like
the wide scope hangs at HEAD, which reads like a regression somebody just landed.
Measured while diagnosing exactly that:

    ps aux | grep '[h]oot ' | grep -v odoo-bin
    1586023  ./hoot --timeout 3000 @web     <- another session, 26 min earlier
    1671382  ./hoot @web/fields             <- mine, queued
    1675411  ./hoot @web/fields             <- mine again, queued behind my own

Two of the three were the same session: each "it produced nothing, let me try
again" added another waiter. Before concluding anything from a silent run, ask
who else is running -- and if their scope *contains* yours (`@web` contains
`@web/fields`), do not queue at all; their run answers your question. Never
`--restart` while any of them is in flight, per the second case above.

### Orphans: servers nothing points at

A database has exactly one state file, and `boot_server` ends in `write_state`.
Any server booted for that db and not recorded there is *forgotten*: the pid
stays alive with nothing referencing it, invisible to `--status` and
unreachable by `--stop --all` and `--clean`. The log goes too — it is named
per-DB, so the newcomer opens the same path `"wb"`, truncating the log of the
server still writing to it.

It compounds, because every forgotten server keeps its psycopg pool and its
inotify watches. Once the cluster runs out of connection slots, `/web/login`
answers 5xx, the health check reads that as *dead*, and another server is
booted to join the pile. One workspace reached **16 servers on `hoot_web`** and
exhausted a 100-slot cluster, at which point no session could run anything.

Servers were lost two ways, and both are closed:

**Concurrent first boot.** The port locks made simultaneous boots pick
different ports; nothing made them pick different *databases*. N sessions
finding no warm server all booted one, all wrote the same state file, and the
last write won. Measured: four concurrent invocations produced four servers,
one record and three orphans — in a single burst. This is the common case
rather than an exotic one, because `hoot_web` is the default db for every plain
`./hoot` and for `hoot-shard`'s shard 0. A per-db `flock` now serialises the
boot, and whoever gets the lock second re-reads the state and reuses the server
the first one booted instead of duplicating it.

**Replacing a server that was still alive.** When the health check said "not
warm" but the process was running, `ensure_server` booted over its record. It
now stops the recorded server first, so a live pid is never left unreferenced.
That is safe only because the health check no longer mistakes load for death:
it separates **`busy`** (5xx, or no answer in time — retried) from **`down`**
(nothing listening — believed at once), so a server under load or under
connection pressure is reused rather than replaced.

**Filestores leaked the same way.** `DROP DATABASE` does not touch
`<data_dir>/filestore/<db>`, so every database hoot ever dropped left its
attachments behind — 109 such directories and 4.4 GB in one workspace, all
belonging to databases that no longer existed, and invisible because nothing
ever looks there. `drop_db` now removes the filestore too, but only after the
drop actually succeeded: a filestore whose database still exists is live data,
not litter. Existing strays predate the fix and are not swept up by it.

Orphans from before this, or from a crash between boot and `write_state`, are
found from `/proc` rather than from the bookkeeping — `--status` lists them as
`ORPHAN`, and `--stop --all` reaps them. Discovery is scoped to this checkout's
`odoo-bin`, so a sibling workspace's servers are left alone, and a server only
counts as an orphan once it is older than `ORPHAN_GRACE`: `write_state` runs
only after the server answers HTTP, so for the whole of a boot — 12-25s in
practice, up to the 120s deadline — a healthy server is recorded nowhere.
Without the grace, `--status` calls every booting server an orphan and
`--stop --all` kills a boot mid-flight. Reaping happens
only on an explicit `--all`: an untracked server has no owner by construction,
but a session that booted one microseconds ago has not written its state file
yet, and reaping on the ordinary boot path would race it.

## CI entry points (gated runs through `odoo-bin`)

The warm runner is for the local edit/run loop. CI runs the same suites through
`odoo-bin --test-tags`, driven by a `test_js.py` per addon that reuses
`web/tests/test_js.py::HOOTCommon` and selects that addon's `@…` suites:

| Addon | File | Tag | Selects |
|---|---|---|---|
| web | `web/tests/test_js.py` | `web_js` | `@web/*` (+ `@html_editor`), granular methods + coverage walk |
| bus | `bus/tests/test_js.py` | `bus_js` | `@bus` (one selector covers the whole tree) |
| mail | `mail/tests/test_js.py` | `mail_js` | `@mail/*`, fanned out + coverage walk |
| *(the other 159)* | `web/tests/test_js_addons.py` | `addon_js` | one generated method per addon that bundles suites no runner names — 660 test files that never ran |

```bash
# CI-style (boots the ERP; slow — use the warm runner above for the dev loop):
odoo-bin -c <conf> -d <db> -i bus  --test-enable --test-tags '/bus:BusSuite.test_bus_desktop'   --stop-after-init
odoo-bin -c <conf> -d <db> -i mail --test-enable --test-tags 'mail_js'                           --stop-after-init
```

Each `test_suite_filters_cover_every_test_file` walk fails the build if a new
`static/tests` directory is added without being wired into a run method, so
suites can never silently stop running (the failure mode that once lost 13 web
test files).
