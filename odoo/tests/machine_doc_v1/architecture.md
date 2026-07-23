# odoo.tests — Architecture

## Test-case hierarchy

```
unittest.TestCase
  └─ case.TestCase           (vendored: trimmed run loop, subtests, tb surgery)
       └─ BaseCase           (tags, retry, HTTP blocking, patch helpers)
            ├─ TransactionCase        (one class-level tx; savepoint per test)
            │    └─ HttpCase          (registry test mode + url_open/browser_js)
            └─ SingleTransactionCase  (one tx across all test methods; no savepoints)
```

- `BaseCase.__init_subclass__` assigns default `test_tags = {standard,
  at_install}` and `test_module` (used by tag selection) to any subclass in
  `odoo.addons.*`.
- `TransactionCase.setUpClass` opens **one cursor** for the whole class,
  patches its `commit/rollback/close` to raise, and each `setUp` wraps the
  test in a `Savepoint`. Registry/cache invalidation is captured and restored
  by class cleanups; `signal_changes` is patched to simulate multi-worker
  signaling without RPC.

## Transaction & lock model (the core trick)

- A **module-level `_registry_test_lock`** (a `RegistryRLock`) is acquired at
  import time by the test runner thread. HTTP worker threads that want a
  cursor during a test must go through `TestCursor`, which blocks on that
  lock.
- `HttpCase.allow_requests` (used by `Opener.request`, `Transport.request`,
  `browser_js`) releases the lock for the request's duration
  (`release_test_lock`) and correlates request↔test via the
  `test_request_key` cookie (checked in `BaseCase.assertCanOpenTestCursor`;
  stale/foreign requests get HTTP 400 instead of touching the wrong tx).
- `TestCursor` wraps the class cursor: `commit` = release savepoint,
  `rollback`/`close` = rollback to savepoint. Readonly test cursors run
  `SET TRANSACTION READ ONLY` inside the savepoint. A class-level
  `_cursors_stack` tracks open test cursors; `close()` removes *itself*
  (warning on out-of-order close — do not pop blindly, see git history).

## Execution flow (`--test-enable` / `--test-tags`)

```
modules/loading.py
  └─ loader.make_suite(modules, position)     position ∈ {at_install, post_install}
       ├─ get_test_modules(module)            imports odoo.addons.<m>.tests.test_*
       ├─ TagsSelector(config[test_tags])     + TagsSelector(position)
       └─ OdooSuite(sorted by test_sequence)
  └─ loader.run_suite(suite)                  sets modules.module.current_test (finally-reset)
       └─ suite.run → case.run → result       failures are LOGGED immediately
```

`OdooTestResult` keeps **counts only** (no failure list) and logs each
error at the exact file:line of the failing frame (`getErrorCallerInfo`).
`ODOO_TEST_MAX_FAILED_TESTS` halts the run past N failures.

### Retry machinery

`BaseCase.run` re-runs a failed test up to `ODOO_TEST_FAILURE_RETRIES`
times: non-final attempts run under `result.soft_fail()` +
`lower_logging` (failures don't count, error logs are buffered); the final
attempt counts for real. One real failure disables retries for the rest of
the session (`BaseCase._tests_run_count = 1`). `@no_retry` opts a
class/method out.

## Tag selection grammar (`tag_selector.py`)

```
[-][tag][/file_path.py|/module][:Class][.method][[params]]   (comma-separated)
```

- No tag + include → implicit `standard`. `*` → all tags. `-…` → exclude.
- Exclusions beat inclusions; with only exclusions, `standard` is the
  implicit include base.
- The module name is also matched as a tag (retro-compat).
- Malformed specs **log an error and are ignored** — the spec grammar is
  anchored, so verify with `TagsSelector("...")` when in doubt (a bad file
  path used to be silently accepted and match zero tests).

## Browser stack (`browser.py`)

`HttpCase.browser_js` (and `start_tour`) drive one `ChromeBrowser`:

```
browser_js
  └─ ChromeBrowser(test_case)        spawns chrome --headless, connects CDP ws
       ├─ _receive thread            dispatches CDP events → _handlers
       ├─ Fetch.requestPaused        non-local URLs → test_case.fetch_proxy (404/mock)
       ├─ Runtime.consoleAPICalled   console.error → screenshot + fail future
       │                             success_signal ("test successful"/"tour
       │                             succeeded") → dirty-form check → success
       └─ Runtime.exceptionThrown    → screenshot + fail future
```

- The test thread awaits `browser._result` (a `concurrent.futures.Future`).
- `browser.stop()` is **idempotent**; `browser_js` registers it twice on its
  ExitStack: early safety-net (covers setup failures — Chrome + profile dir
  would otherwise leak) and late happy-path (stop browser *before* waiting
  on remaining request threads).
- `patch("odoo.tests.common.ChromeBrowser")` is a supported mock target:
  `browser_js` resolves the name through `common`'s module globals, which
  re-import it from `browser.py`.

## Form emulation (`form.py`)

`Form` fetches the form view via `get_views`, parses modifiers
(required/readonly/invisible/column_invisible) into python-evaluable
expressions (`_combine_bool_exprs` merges duplicate-field occurrences with
AND, ancestor invisibility with OR), and drives `onchange`/`web_read`/
`web_save` exactly like the web client. x2many fields are edited through
`O2MProxy`/`M2MProxy`; sub-records via `O2MForm` carry a `parent` eval
context. Values live in `UpdateDict`s that track the `_changed` key set —
only changed, non-readonly fields are saved.
