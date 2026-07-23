# odoo.tests — Conventions & Gotchas

## Where the framework's own tests live

| Suite | Runs via | Covers |
|-------|----------|--------|
| `odoo/addons/base/tests/test_test_suite.py` | odoo-bin `--test-tags` | runner logging, cleanups, skip, retry, `TestCursor` stack, `compute_stats` |
| `odoo/addons/base/tests/test_tests_tags.py` | odoo-bin | `tagged`, `TagsSelector` parser + selection |
| `odoo/addons/base/tests/test_form_create.py` | odoo-bin (post_install) | `Form` on real views, modifier merge, o2m `mode="form"` |
| `odoo/addons/base/tests/test_http_case.py` | odoo-bin (spawns Chrome) | `browser_js`, console error handling, screencasts |
| Tier-1/Tier-2 pytest (`cd addons/odoo && pytest` / `pytest odoo/orm/tests`) | pytest | do NOT cover odoo/tests directly; keep green anyway |

Quick battery after touching this package (disposable DB):

```
--test-tags /base:TestTestSuite,/base:TestSelector,/base:TestSetTags,\
/base:TestCursorStack,/base:TestBenchmarkStats,/base:TestFormCreate,\
/base:TestHttpCase,/base:TestChromeBrowser,/base:TestRequestRemaining
```

## Tagging rules

- Every test class must end up **either** `at_install` **or** `post_install`
  (`tagged()` warns otherwise). `HttpCase` should be `post_install`
  (registry must be fully loaded for assets/routes).
- `test_tags` is a plain set inherited through subclassing; `@tagged("-x")`
  removes. Position (`at_install`/`post_install`) is itself just a tag.
- `test_sequence` (int attr) orders tests inside a suite.

## Public API surface

- `odoo.tests` re-exports exactly `common.__all__` + `Form`/`O2MProxy`/
  `M2MProxy`. **Adding a public helper to `common.py` requires adding it to
  `__all__`** or `from odoo.tests import X` won't resolve.
- `Command`, `patch`, `mute_logger` are *sanctioned* convenience re-exports;
  don't remove.
- `odoo.tests.common.ChromeBrowser` must remain a valid attribute (mock
  target used by bus/base tests and web tooling), even though the class
  lives in `browser.py`.
- `test_cursor.py` / `test_module_operations.py` are import shims for old
  upstream paths — external tooling (runbot) may call
  `python -m odoo.tests.test_module_operations`. Keep until proven dead.

## Gotchas (hard-won)

- **Do not commit/rollback/close `cls.cr`** in a TransactionCase — it is
  patched to raise. Open another cursor (`self.registry.cursor()`) or use
  savepoints.
- `TestCursor._cursors_stack`: close order matters; `close()` removes the
  cursor itself and warns on out-of-order close. Never `pop()` blindly.
- HTTP requests during tests need `allow_requests` (lock release + cookie);
  requests without the current `test_request_key` cookie get HTTP 400 by
  design (`assertCanOpenTestCursor`).
- `assertQueriesContain` is **not** a subset check: exact query count,
  substring match per query.
- `warmup`/`assertQueryCount`: the warm-up run executes the whole test body
  once with `self.warm = False`; assertions must be conditional on nothing —
  the framework skips the count checks itself.
- Retry mode (`ODOO_TEST_FAILURE_RETRIES`) treats **any ERROR-level log**
  during a soft run as failure (`lower_logging`), not just assertions.
- `benchmark.compute_stats`: mean/median/percentiles are outlier-trimmed
  (indices trimmed jointly across time/db/query lists); `min_us`/`max_us`
  are raw extremes.
- Ruff config marks `F401` unfixable — remove unused imports by hand.
- Py 3.14 / PEP 758: `except A, B:` (no parens, no `as`) is valid and is
  the enforced style — don't "fix" it back to parenthesized form.
- Chrome flakiness: `Thread.start()` can transiently refuse
  (`pthread_create`) under load — `ChromeBrowser.__init__` retries with
  fresh Thread objects; keep that pattern if touching the receiver setup.

## What NOT to do

- Don't import business-addon code here; `common.py` logs an error if the
  framework is imported by a non-test server process.
- Don't add state to `BaseCase` instances that survives across tests —
  environments/caches are reset per test by cleanups in
  `TransactionCase.setUp`.
- Don't make `browser.py` import `common.py` at runtime (only under
  `TYPE_CHECKING`) — the split exists so the CDP client stays importable
  without the framework; shared helpers go in `utils.py`.
