# Findings — how the architecture rules were arrived at

> The evidence base behind [`ARCHITECTURE.md`](ARCHITECTURE.md),
> [`module.md`](module.md) and [`gates.md`](gates.md). For what the design
> currently *costs*, measured, see [`qualities.md`](qualities.md) — that is the
> page of numbers; this is the page of findings.

Several rules in those documents look arbitrary without the finding that
motivated them, and every entry below is a worked example of one failure mode:
*a sentence that stayed true in spirit while the code moved underneath it.* This
is a lab notebook, not a blueprint — which is exactly why it is a separate file.

**The bracketed tiers in `db/` and `http/` were documentation only** until they
were measured. Nothing verified the direction *between* the groups. Measured,
both were already layered — `db/` had 6 connectivity → resilience edges against 1
the other way (counting imported *symbols*, as `layer_check` does), `http/` 22
serving → features against 1 (counting import *statements*; by symbol it is 44
against 2) — and each back-edge was a module filed in the wrong bracket rather
than a genuine cycle. With `errors`/`dsn`/`utils` moved to `[foundation]` and
`helpers` to `[serving]`, both directions hold at zero and became contracts.

**The transitivity caveat is not hypothetical.** Two real modules spelling
`odoo/orm/fields` → `odoo.tools.something` → `odoo.orm.runtime` were added to the
tree and `--check` reported `New: 0` over the whole scanned core. (The figure
first written here — 6453 — was the *path* count of the day, before
`_collapse_nested` stopped overlapping `source` prefixes walking the same file
once per covering root; it was 6362 distinct files even then. Read the count off
a run, not off this line.)

**The mixin graph was called a DAG on the strength of the `self`-only view.**
Measuring recordset-mediated calls found `base.py` ⇄ `create` immediately;
extracting `_ConstraintsMixin` removed it, and both views are ratcheted now so
neither the prose nor the graph can move without the other. An earlier version of
the checker also silently collapsed the `read_group` subpackage into one unit,
hiding 10 edges and a whole 3-cycle — which is why its numbers are cross-checked
against the runtime `BaseModel.__mro__`.

**`orm/__init__.py`'s docstring and the gate once disagreed.** The docstring
omitted `components/` and `_recordset.py` and filed `_typing.py` under
"cross-cutting", where `layer_check.py` scopes it to Layer 0. A reader who opened
the package instead of the page got a different architecture.

**`core-does-not-depend-on-addons` first reported eight tolerated edges, not
four.** `_ImportCollector` emits both `<base>` and `<base>.<name>` for every
`from X import Y`, so each of the four statements was reported twice. The
synthesised record is now kept only when it is the one that carries the violation
(`from odoo import models` under a contract that forbids `odoo.models` but not
`odoo`), so one import statement is one violation.

**The `env` surface figures were copied, not measured.** This page and
`env_surface_check.py`'s own docstring both said `orm/fields` reaches *5*
unsanctioned private `Environment` members. Five is the size of the
distinct private set across the whole ORM — `_field_depends_context` is reached
from both packages — not `orm/fields`' share of it. Both prose copies agreed with
each other and neither agreed with the checker. Every measured figure on this
page is now derived from a live run of the checker that produces it.

**Both seam gates scoped Layer 2 to `orm/models` alone**, which left eight
top-level `odoo/orm/*.py` modules in **no** scope at all — including
`registration.py`, which was reading three private `Registry` attributes on every
model setup while `orm-helpers-and-registration-stay-below-runtime` reported it
clean at zero. Correctly so: it imports `odoo.orm.runtime` nowhere. That is
exactly the channel those gates exist to watch, and it ran through the one file
neither of them read. Hence `_orm_layer_scope.py` and its completeness test.

**The model-surface gate measured a spelling, not a coupling.** It read
`env[<literal>]` plus the accessor map and reported the framework's model
surface as closed. Four other syntaxes name a model and produced no hit:
`registry[...]`/`pool[...]` (`Registry.__getitem__` returns the model class --
the same coupling one attribute over, and `http/_serve.py` alone uses it ten
times for `ir.http`), `env.get("...")` (a `Mapping.get`, so there is no
`Subscript` node to visit), `"..." in registry` (a membership test names the
model as surely as a lookup) and a comodel argument, which is how
`orm/models/metaclass.py` names `res.users` when it builds the
`create_uid`/`write_uid` magic fields. Measured before the fix, those channels
carried 31% of all model reaches in the core, and two of the models they
reached -- `ir.demo_failure` and `res.partner` -- were absent from
`KNOWN_MODEL_SURFACE`, a set whose entire purpose is to be closed. Neither was
new coupling; both predate the gate and were simply spelled in a syntax it did
not read.

Two things generalise. A gate built on one spelling of a coupling is invisible
from inside its own report -- it says "clean" in exactly the voice it would use
if it were complete. And the fix is cheap when the mechanism is already trusted:
extending `_EnvModelCollector` by four visitors and re-baselining by two models
beat writing a second checker, which is what the first draft of this
investigation proposed.

**`env_model_surface_check.py`'s subtree pins exist because the flat set is not
enough.** Appending `env["ir.model"]` to `orm/components/model_graph.py` — a
package whose entire contract is that it is pure Python — passed `layer_check`,
`env_surface_check`, `pool_surface_check` and the model-set gate at once.

**`py_cycle_check.py` reported on 323 modules and called that the core.** It is
338: `odoo/tests/` is the shipped test *framework*, and a "drop any path with a
`tests` component" filter removed all 17 of its modules. `layer_check` had the
identical bug and fixed it at `_CORE_TEST_FRAMEWORK_PACKAGE`; nothing had
propagated the rule.

**`libs_facade_check.py`'s scope has widened twice on measurement.**
`odoo/tools` held 19 leaf imports and `orm`/`http`/`modules`/`service` nine more,
all while the gate reported green, because a tree outside the scope cannot fail.
It scans every core package now (`odoo/libs` itself excepted: an area importing
its own leaves is how a package is built), and `test_every_core_package_is_scanned`
fails if a new one is added without being scanned or explicitly excused. It is a
separate tool rather than a `layer_check` contract because `Contract.allow` is
prefix-matched and `_ImportCollector` emits a synthetic `<base>.<name>` per
imported symbol, so `odoo.libs.numbers.float_round` (a symbol) is
indistinguishable *by name* from `odoo.libs.numbers.float_utils` (a module); the
discriminator is on disk.

**The subsystem map depicted four directories that do not exist.** It drew
"connectivity"/"resilience" under `db/` and "core"/"features" under `http/` as
subdirectories when both packages are flat, and the invented "core" node masked
the real, undocumented `http/core.py`. That is what `subsystem_map_check.py` was
written for.

**The HTTP call graph was cited after it had been deleted.** It lived in
`odoo/http/__init__.py`'s module docstring; `4ffeacacd8c` stripped docstrings
from `odoo/` and, because nothing read that one, took the only detailed copy with
it while this page went on calling itself the abridged version. Recovered from
`4ffeacacd8c~1`, re-verified symbol by symbol, and moved to a README so the strip
policy and the call graph no longer compete for the same lines.

**`env._core` handed out the object it claimed to curate.** `OrmCore`'s slots
were named `cache`/`engine`, so `env._core.cache` *was* `transaction._cache_store`
while this page said the raw objects stay private to `Transaction`. Renaming them
to `_cache`/`_engine` is also the change that broke two DB-backed addon tests
with every structural gate green — the worked example under *The limits of
"enforced"*.

**`test_http` was in no workflow at all** and had accumulated three defects, one
of them a test committed red two months earlier. It is in the integration lane
now, with its own database.

**An earlier version of the `package_index_check.py` paragraph claimed the
removed patch names were "quoted rather than backticked on purpose".** They never
were, and no convention asks authors to punctuate around a checker. Section
scoping is the fix.

**The risk register was in `DOC_PATHS` and asserted by nothing.** Membership
of the concatenated document is what makes a page *readable* by the gate, not
what makes it *checked* — and the two look identical from outside. `risks.md`
shipped with five figures (the two runtime-channel comparisons, the checker
count in digits, the public-surface pin size); every one was correct, and
mutating R2's to `Layer 2's 99` and `777 Registry sites` left the whole suite
green. The word form of the checker count was pinned in `gates.md` while the
three bare `24`s here were not, so adding a gate would have failed one page and
quietly falsified the other. Each figure now derives from a live run of the
checker that produces it, and one assertion guards the *conclusion* rather than
the digits, because both sides of a comparison can be re-measured correctly
while the sentence around them is left claiming the opposite.

See also: `doc/adr/` (architecture decisions, 0001–0016 — 0012/0013 cover
attachment storage and content placement, which sit above this page's scope) and
the `orm/__init__.py` module docstring.
