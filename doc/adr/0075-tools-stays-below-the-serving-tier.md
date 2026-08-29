# ADR-0075: `odoo.tools` stays below the serving tier

- **Status:** Accepted
- **Date:** 2026-08-29

## Context

`doc/architecture/module.md` places `libs/` as Odoo-agnostic and `tools/` as
Odoo-coupled, both below the tier that serves requests. `layer_check` enforced
one half of that for tools — `tools-does-not-reach-the-orm-runtime` — and nothing
at all against `odoo.http`.

`odoo/tools/urls.py` imported it at module scope:

```python
from odoo.http import request
```

`odoo.http` imports `odoo.tools` in eight modules (`application.py`, `_csrf.py`,
`routing.py`, `_serve.py`, `stream.py`, `session.py`, `helpers.py`), so this is a
cycle. It resolved only because `urls.py` is not reachable from
`odoo/tools/__init__.py` — an accident of import order, not a design.

The cost was not hypothetical. **64 files across `odoo` and `enterprise` import
from `odoo.tools.urls`**: `odoo/addons/base/models/ir_qweb.py` takes
`keep_query`, and `website`, `mass_mailing`, `survey`, `link_tracker`, seven
`payment_*` providers, six `delivery_*` providers and eight `l10n_*` modules take
`urljoin`. Every one of them loaded the entire serving tier to obtain a URL
helper that does not need it.

Measured before the fix:

```
$ python -c "import odoo.tools.urls, sys; print('odoo.http' in sys.modules)"
True
```

The correct idiom was already in the tree, one file away: `cache_version.py`
imports `request` inside the function that uses it, under
`except ModuleNotFoundError`.

## Decision

`odoo.tools` may not import `odoo.http` **at module scope**. A helper that
genuinely needs the request imports it inside the function that uses it.

The contract is `tools-stays-below-the-serving-tier` in
`tooling/architecture/layer_check.py`, carrying a new `module_scope_only` flag.

That flag is the substance of the decision, not a detail of it. Every other
contract in the file bounds what a layer may *use*, and for those an import is an
import wherever it sits. This one bounds what a layer costs to *load*, and an
import below a `def` creates no load-time edge — so for this contract, and only
for contracts that opt in, a deferred import is not a violation. Without the
distinction the contract would reject the very shape that satisfies it.

## Alternatives considered

**Move `keep_query` into `odoo.http`.** It reads the request, so it arguably
belongs there. Rejected because `odoo.tools.urls` is the import path 64 files
already use, and moving the function would break every one of them to fix a
problem none of them has. The module's other three exports have nothing to do
with HTTP.

**A `TYPE_CHECKING` guard.** Does not help: `request` is used at runtime, not
merely annotated.

**Forbid the import outright, deferred or not.** Rejected: it would have no
satisfying resolution short of moving the function, and it would immediately
flag `cache_version.py` and `assets/esm_bridges.py`, both of which already do
the right thing.

**Leave it to review.** Rejected on the evidence: the inversion stood while
`layer_check` reported green across 6881 files, because no contract described
this edge. A boundary that review alone protects is a boundary that drifts.

## Consequences

`import odoo.tools.urls` no longer loads `odoo.http`, so the ~60 payment,
delivery and l10n modules that import `urljoin` stop paying for the serving tier.

`urls.py` also loses its `from odoo.libs.web import *` shim in favour of a named
re-export and an explicit `__all__`, because the star import made the surface
unreadable to a linter and hid which names the module actually publishes.

The unit test for `keep_query` no longer stubs `odoo.http` at import time to
satisfy a module-scope import; it installs the stub around the call instead,
which is both smaller and closer to what happens in production.

`module_scope_only` defaults to False, so no existing contract changes meaning.
A future contract that bounds load cost rather than use opts in the same way.

## Enforcement

`tooling/architecture/layer_check.py`, contract
`tools-stays-below-the-serving-tier`, run by `.github/workflows/architecture.yml`.

`tooling/architecture/test_layer_check.py` pins the discrimination in four
directions: a module-scope `from odoo.http import ...` and `import odoo.http`
both fail; the same imports inside a function body (and inside a nested one) do
not; the contract does not apply outside `odoo.tools`; and `module_scope_only`
does not leak — a deferred `odoo.orm.runtime` import still breaks
`tools-does-not-reach-the-orm-runtime`, which did not opt in.

`odoo/tools/tests/test_urls_keep_query.py::TestToolsStaysBelowTheServingTier`
carries the unit-level mirror: it parses `urls.py` and asserts no module-scope
`odoo.http` import, and asserts that importing the module leaves `odoo.http` out
of `sys.modules`.
