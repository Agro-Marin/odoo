# Fork architecture audit — 2026-09-04

Baseline: `00a71dd4120` on `19.0-marin`. Findings describe that checkout;
implementation notes describe the accompanying working-tree changes. Baseline
measurements below are frozen to that revision, not standing counts.

## Assessment and scope

Keep the modular monolith. Per-database model assembly, transactional business
operations and addon inheritance are fundamental requirements. Splitting these
across services would introduce distributed consistency and extension problems
without a demonstrated operational benefit.

The strongest existing decisions are the ORM layers, pure cache/compute
components, a persistence port, frozen settings injected into infrastructure,
transport-independent transaction orchestration, and public addon facades.
The next architectural gains come from strengthening behavioral contracts.

Reviewed the core subsystem and runtime maps, risk register, persistence and
retry implementation, migration discovery/execution, module boot dependencies,
test tier configuration, and gate execution instructions. Ran Python and JS
layer/cycle checks and Environment/Registry surface checks. JS public boundary
checks inspected consumers from the assembled workspace. This is not an audit
of every business addon, production configuration, or deployed CI service.

## Findings and proposals

| Priority | Evidence at baseline | Improvement and acceptance condition | Status |
|---|---|---|---|
| P0 | `service/transaction.py` commits outside the retry loop. An existing test explicitly pins failure without retry at commit. | Include commit in the bounded attempt. A real commit-time rejection must replay with a fresh snapshot and commit the intended write once. | Implemented; PostgreSQL contract test covers write skew. |
| P0 | The retry loop suppresses rollback and state-reset errors before executing the handler again. An existing test explicitly pins replay after failed rollback. | Require successful recovery before replay; preserve the triggering error when rollback fails, with the recovery error chained. | Implemented; tests cover rollback, closed cursor and both state resets. |
| P0 | A naive move of commit into the loop would replay successful work when a post-commit hook raises a concurrency exception. `db/cursor.py` advances `commit_count` before callbacks. | Use that existing durability boundary to forbid replay and local registry reset after commit; continue signaling peers. Unknown connection-loss outcomes must propagate. | Implemented; unit and real-cursor tests cover durable callback failure. |
| P1 | `modules/db.py` reaches `Manifest` through the package that imports `db`; the cycle checker pins that cycle. | Import from the owning module and delete the obsolete exception; retain the public facade. | Implemented; the cycle gate now rejects its return. |
| P1 | `InMemoryBackend.search` calls `flush_all()`; R9 explains how this erases pending-compute state needed to reproduce recursive stored-field defects. | Define selective flush semantics for the backend port, then run identical recursive-compute scenarios against memory and PostgreSQL. Verify the known regression fails against the pre-fix implementation in both. | Implemented in the continuation; metadata-based selective flush, and ordinary-write recursion scenarios on both backends. R9 closed. |
| P1 | Migration stage selection is syntactic; R3 documents that a post-stage script cannot recover data already removed by schema setup. | Require populated-database upgrade fixtures for representation changes, asserting preserved business values as well as schema visibility. | Follow-up for schema-changing addons; this patch changes no schema. |
| P1 | R8 records browser suites skipped by headless runs. The reproduction loops in `gates.md` print failures with `echo` without aggregating a failing exit status. This checkout has no GitHub workflow directory. | Provide a reproducible validation entry point that aggregates failures, separates pytest tiers into processes and requires actual browser execution for selected tours. Connect it to the chosen CI system. | Follow-up; deployed enforcement was not inspected, so local absence does not prove absent CI. |
| P2 | Public-surface validation reports undeclared imports without failing; R6 records independently versioned sibling consumers. | Classify supported exports, migrate deep imports by consumer scope, and validate the assembled release before publication. | Follow-up; migrate consumers before tightening facades. |
| P2 | Import checks do not model runtime dependencies through `env` and `pool` (R2). Existing seam gates constrain those channels. | Extend narrow protocols when removing concrete private dependencies; retain runtime seam budgets alongside import rules. | Follow-up; no generic service-locator replacement proposed. |

The baseline Python cycle gate reported the module-loader and CLI cycles. The
JS cycle gate reported the POS store/receipt cycle. Python and JS layer checks
reported no new violations; tolerated exceptions remain debt. These are
structural measurements, not a claim that production behavior is correct.

## Implemented transaction contract

An attempt owns handler execution, flush, and commit. Concurrency failures may
replay only before any commit since entry, after successful rollback and local
state reset. The transport participant restores session state and rewinds
request input. Attempts retain the existing retry limit and backoff policy.
Integrity errors remain translated, with the original error preserved if
translation itself fails.

After a durable commit, callback and signaling failures propagate without
replaying business work or resetting committed registry state. Connection loss
with an unknown outcome is not a concurrency rejection. This does not provide
exactly-once execution for external side effects; handlers still need
transactional jobs or idempotent outbound operations.

Retrying the entire transaction follows PostgreSQL's
[serialization failure guidance](https://www.postgresql.org/docs/18/mvcc-serialization-failure-handling.html).
The durability distinction comes from this fork's cursor contract, not error
message text.

No public signature, model field, schema, dependency, or deployment changes.
The deliberate behavior changes are additional attempts on commit-time
concurrency rejection and failure instead of replay after unsuccessful
recovery. Tests pinning the former behavior were updated explicitly.

## Validation and limits

- `tests/service/test_transaction_recovery.py` covers recovery order, fresh
  return value, prior cursor commits, post-commit failure, failed state reset,
  closed recovery cursor, unknown commit outcome and self-committing handlers.
  Running it against the baseline transaction implementation in a separate
  process fails the new recovery invariants, confirming regression sensitivity.
- `tests/contract/test_transaction_recovery.py` exercises real PostgreSQL write
  skew rejected at commit, a fresh snapshot on replay, aborted writes absent,
  and a durable write preserved once after callback failure.
- `tests/contract/test_commit_count_ordering.py` verifies the durable marker
  advances before callbacks. All selected PostgreSQL tests ran without skips.
- `tests/loading/test_migration_schema_visibility.py` passed against a fresh
  installation and a populated schema upgrade after the loader import change.
- The complete real-import framework invocation passed with local socket
  access. Python/JS layer and cycle checks, runtime seam checks, and JS public
  boundary checks across the assembled workspace passed.
- Local mypy over the service and modules packages reports the same diagnostics
  against baseline sources supplied through `--shadow-file` and the changed
  sources. This is a no-regression comparison, not a clean type-check result.

Final run record for this audit: the framework suite passed 4,121 tests with
one skip; the selected PostgreSQL contracts passed five tests and the loader
upgrade suite passed three. The standalone run passed 5,282 tests with three
skips and two documentation failures: it had collected the old cycle-prose
checker before that checker was updated. A fresh run of the complete affected
documentation suites passed all 156 tests. Core Ruff and changed-file Ruff
format checks passed. These are dated execution results, not suite-size floors.

Run the pytest tiers in separate processes as documented in `pytest.ini`.
PostgreSQL dependency skips are not passing evidence. Production latency, full
addon integration, replica failover and browser tours remain release checks;
this audit does not certify a completed “best in class” architecture.

## Continuation: selective backend flushing

In-memory search now discovers flush dependencies from field metadata and
preserves deferred work and dirty values. PostgreSQL retains its SQL query
planner. The initial continuation used shared SQL compilation; the correctness
review below records why that implementation was wrong and how it was replaced.

Search tests cover identifier-only queries, computed-field filters/order,
related-model dependencies and cache preservation. Recursive tests exercise
ordinary parent writes and root renames followed by middle-first reads. The
same model definitions and recursive scenarios run on the PostgreSQL adapter
with real temporary tables. These test schemas intentionally do not claim
coverage of record rules, schema migration or database constraints.

Mutation checks restored the old eager search, removed the recursion guard,
and narrowed the guard to the current field. Each failed the corresponding
new invariants in a separate process without changing repository files.
This closes R9's testability gap while leaving the other adapter limitations
explicit.

Continuation validation: the complete real-import framework suite passed
4,130 tests with one skip; the PostgreSQL adapter contracts passed six tests;
the selected architecture and document suites passed 257 tests. Core Ruff and
changed-file formatting checks passed. Non-incremental mypy over the ORM
reported the same seven existing diagnostics with both the original and
changed backend source supplied through `--shadow-file`.

## Adversarial correctness review

Two regressions in the continuation were reproduced before correction:

- A timezone-aware datetime property domain queried `pg_timezone_names` during
  SQL compilation and failed in the in-memory adapter.
- A custom domain with a Python predicate invoked its PostgreSQL callback.

SQL compilation is not a pure dependency-discovery API. In-memory searches now
walk domain, relation and ordering metadata directly. Regression tests also
cover non-stored related ordering, dirty one-to-many inverses and an explicit
error for SQL-only custom domains. Opaque Python predicates conservatively
retain the historical full flush because their dependencies cannot be inferred.
This is a bounded backend contract, not proof of universal SQL/Python equivalence.

The previous PostgreSQL transaction contracts used a real cursor but mocked
transaction and registry state. A separate loading-tier test now uses an
installed base database, real registry, field cache and stored compute queue.
It requires a serialization rejection at commit, verifies the replay reads the
original partner name rather than the aborted cached write, and checks only the
second attempt survives. Loading and lightweight contract tests must run in
separate processes because installed addon classes contaminate the latter's
synthetic registry.

Review validation: 27 focused regressions passed; eight PostgreSQL contracts
and the real-ORM loading test passed in separate processes, without skips.
Restoring the earlier shared-planner backend in an isolated process fails both
new regressions. Restoring the pre-fix retry implementation fails the real-ORM
test at PostgreSQL COMMIT. The architecture/documentation selection passed 287
tests and 38 subtests. Core Ruff, changed-file formatting, layer/cycle checks,
subsystem-map coherence and the unchanged function/class size floors passed.

The final full framework run passed 4,121 tests and 975 subtests, with eight
skips and seven failures. All seven failures are in inotify watch setup with
ENOSPC (host watch capacity exhausted), including tests of the installed
inotify package directly. This is not a fully green framework run. Earlier
restricted runs also hit socket restrictions and missing worktree Sass assets;
the final run had socket access and the existing workspace dependencies linked.

## Follow-through: preexisting failures, 2026-09-05

The inotify failures were actionable. Read-only process inspection found VS Code
holding 65,057 watches against a host budget of 65,536. Workspace editor settings
now exclude generated trees, dependencies, caches and secondary worktrees; the
reusable template is `tooling/vscode-settings.json`. Host limits were not raised
and other processes were not terminated.

The fork also had resource-ownership defects: watcher shutdown depended on
reference collection, and a failed tree constructor could retain descriptors
through its exception traceback. The inotify adapter now owns explicit,
idempotent closure of both the inotify descriptor and epoll object. Construction
failure closes partially acquired resources. The event thread releases its
resources on exit; a timed-out join leaves closure to that thread instead of
closing descriptors beneath a live reader. Tests retain references and exception
tracebacks, and prove the prior implementation leaks in both cases. Watcher
fixtures now close their trees and no longer skip host-capacity failures.

The previous Python type-check reports used a development mypy version that
was older than the repository pin. The shared environment now uses the pinned
version and has pinned dateutil stubs. Newly introduced search typing errors
and existing load-path, HTML-value and WSGI interface mismatches were corrected.
The HTML annotation preserves the existing empty-string result; request timeout
configuration now targets the connection directly and is tested on real sockets.
Recovery exception classification is named and typed, with absent PostgreSQL
table metadata handled explicitly.

The final order-dependent framework skip was replaced with a subprocess import
boundary check. A deprecated-config test now captures its own warning instead
of leaving it buffered for an unrelated test. These changes strengthen the
checks rather than treating untested behavior as a passing result.

The freshly built pinned toolchain also exposed dateutil boundaries previously
hidden by missing stubs. Date helpers now use the public weekday constants and
explicitly select calendar-component construction. Variadic forwarding retains
the constructor's full argument surface; safe evaluation distinguishes the raw
module import from its published restricted wrapper.

Integrated on `19.0-marin`. Final framework verification passed 4,140 tests and
975 subtests with no failures, skips or warnings. The date helper tier passed
82 tests and four subtests. The combined isolated type check passed across all
13 scoped packages (809 source files); the dependency-rich ORM/service/module
check also passed. PostgreSQL search/retry contracts passed eight tests and the
separate real-ORM loading test passed. Layering, import cycles, core Ruff and the
unchanged size floors passed. Architecture documentation and launcher checks
passed; the launcher integration check was rerun after building its local
pinned environment instead of accepting its missing-environment skip.

## Continuation: gate environment freshness, 2026-09-05

The main checkout's cached gate environment lacked the newly required dateutil
stubs, yet `tooling/gate` accepted it because Ruff and mypy's versions matched.
The launcher now validates the complete requirements file with pip's
non-installing resolver plan before executing the requested command. It rejects
missing or mismatched packages, incomplete dependencies, plans that would
install anything, and absent or malformed reports. Platform markers and version
ranges remain owned by pip rather than a second requirement parser.

Validation isolates pip from local configuration and environment flags. Tests
reproduced how `PIP_NO_DEPS=1` and a config-file equivalent otherwise bypassed
transitive checks. Package-index access and cache writes are disabled during
validation. A stale environment gets an explicit synchronization command; the
check itself does not install packages. The main checkout's cached environment
was synchronized with its declared requirements.

All 17 launcher/environment tests passed, including real pip runs against
isolated environments and a local wheel that pip could plan successfully but
had not installed. Restoring the old launcher in temporary test checkouts
makes the missing-package, wrong-version and uninstalled-wheel regressions fail.
The validated main-checkout gate passed the combined 809-file type check and
Ruff over tooling and tests. This closes a concrete reproducibility gap; it does
not establish deployed CI enforcement or close the browser-coverage risk R8.

## Continuation: selected infrastructure is required, 2026-09-05

The infrastructure exception was already distinct from a deliberate skip, but
its error policy was opt-in. Both a small mixed suite and a real Odoo process
reproduced a successful result when database tests ran and selected HTTP tests
could not start. A guard against phases that started nothing did not cover
this mixed case.

`ODOO_REQUIRE_INFRA` now defaults to 1. Missing HTTP, browser or other declared
infrastructure is an error for selected tests. Ordinary deliberate skips are
unchanged. Explicitly setting the variable to 0 permits a partial local run,
with a warning naming that incomplete coverage; the all-unstarted-phase guard
still applies. Infrastructure failures during class setup and test methods are
both covered by the framework contract.

The loading contract exercises real process exit codes for strict mixed
selections, explicit partial selections, the existing empty-phase guard and
normal database-only execution. Its positive served selection sends an actual
XML-RPC request to a server on an ephemeral port. This strengthens R8's result
contract; it does not certify that every business tour has been run or fixed.

The broader review caught an obsolete third-party patch exception left by the
earlier `safe_eval` import-alias correction. Its timezone assignment configures
a sandbox wrapper, not the real `dateutil` module. Removed that exception and
added a fresh-process regression proving the original library function retains
its identity while sandbox evaluation uses the fork's timezone resolver.
The architecture gate also detected the newly committed add-ons changing the
bundled-module count from 647 to 650; the documented count now matches the tree.

All six real-process loading contracts passed, including the base add-on's
infrastructure accounting tests. Machine-document checks passed for `odoo.tests`
(98) and `base` (967); architecture documentation and its mutation checks passed
(156 tests, 32 subtests). The `odoo.tests` type check passed across 18 files.
Core Ruff is clean; function-length excess remains zero and class-length excess
remains 22,366. The two permission-dependent lint scanner tests skipped by an
elevated run passed separately as the normal user.

The full real-import framework run passed 4,188 tests and 975 subtests. The
separate leaf/tooling run exposed another architecture defect: consumer scanners
descended into the nested `.worktrees/architecture-review` checkout. Obsolete
code then appeared as current consumers, doubling widget figures and expanding
several JavaScript surfaces. Ten failures traced to this scope contamination;
one further test found four stale prose figures after recent core changes.

The shared source traversal now prunes nested Git checkouts before descent,
recognizing both `.git` files and directories, and excludes `.worktrees` and
cache trees. An explicitly selected worktree root remains a valid scope. Five
affected JavaScript scanners and the documentation scanner use this traversal;
the existing public, extension, field-record and environment surface pins are
unchanged. Documentation coverage compares directories from the same source
scope rather than unrelated checkouts. The four prose figures were refreshed
from their owning measurements.

New fixtures exercise named worktree directories, arbitrarily named nested
clones and worktrees, and explicit worktree roots. Restoring unbounded traversal
in a test process makes all three nested-checkout fixtures fail. A separate
regression ensures recursive documentation globs do not read another checkout.

The broad leaf/tooling run recorded 5,291 passes, 881 subtests, 11 failures and
three skips before these corrections. Its two permission skips passed as the
normal user; the remaining skip is the deliberate absence of oversized literal
service `start()` methods. Rerunning the affected suites passed 239 tests and
five subtests, leaving only two further prose counts that changed during
concurrent add-on work; those counts were refreshed separately. Core framework
and loading contracts are distinct runs and were not shadowed by leaf stubs.
The final prose-count suite passed all 29 tests and five subtests. Every failing
suite from the broad run was rechecked after its correction; the entire
leaf/tooling suite was not repeated. Ruff, formatting and the typed traversal
helper also passed their final checks.
