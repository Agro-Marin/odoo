# ADR-0083: The assemble verbs lose their carve-out

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

ADR-0082 retired the package carve-out and scoped the method vocabulary to every
function in the core package `odoo/`. It measured the sweep with the
abolished-verb table and left core reporting **13** survivors, all documented.
That measurement was honest about what it counted and silent about what it could
not: `naming_vocabulary.classify` treats `build`, `make`, `compose` and
`construct` as **payload-only**, so it reports one of them *only when the name
also ends in a payload suffix* — `_vals`, `_data`, `_context` and seven more.

§2.4.7 has stated the gap in prose since before that sweep: "The assemble verbs
are abolished on paper and enforced for one shape", and "object construction
takes `_prepare_` too, a factory having a consumer like anything else". Read
across the whole core package rather than across model classes, the shape the
gate cannot see held **45** definitions — more than three times the survivor
count ADR-0082 reported, in the same tree, under the same rule. The ratchet could
see **none** of them: two are declared on a model class and neither ends in a
payload suffix, so the whole sweep moves the `naming` floor by zero. A gate that
cannot move for a change of this size is not measuring the change.

Two of them were the reason this is a record rather than a sweep. `make_response`
and `make_json_response` are methods on `request`: **274** occurrences over
**134** files in three repositories, reached by almost every controller anyone
has written against this fork. `make_key` is worse in kind if not in size — a
public model method on `res.users.apikeys.description`, named by a button in
`res_users_views.xml` and called by name over RPC from JavaScript in two addons.

Seven definitions were spelled with a **bare** verb — `make()`, `build()`,
`_build()` — which no rule in §2.4 reaches at all, because
`naming_vocabulary.classify` partitions on the first token and returns `None`
when there is no remainder. A name that says only *this function runs* says less
than one that says nothing, and it is invisible to every count in the section.

## Decision

The four assemble verbs are swept out of the core package on the **consumer
test** of §2.4.7, not on the suffix list, and the bare verbs are swept with them.

Thirty-three definitions were factories, artifact builders or payload builders
and take `_prepare_*`: `make_response` → `prepare_response`, `make_json_response`
→ `prepare_json_response`, `build_routing_map` → `prepare_routing_map`,
`_build_insert_rows` → `_prepare_insert_rows`, `_make_corecords` →
`_prepare_corecords`, and so on. Object construction is the majority case and it
is the one §2.4.7 already ruled on.

The rest moved **across** the table rather than along it, which is the part
ADR-0082's Consequences asked a future sweep to copy:

- `build_param_specs` → `get_param_specs` and `_build_index_expression` →
  `_get_index_expression` answer a question about their argument. A derivation
  whose product is read is the Read row whatever arithmetic produced it.
- `make_identifier` → `normalize_identifier` and `make_xml_id` →
  `normalize_xml_id` take a representation and return the same representation,
  repaired. That is the row `validate_url` → `normalize_url` landed on in
  ADR-0082.
- `make_index_name` → `get_index_name` and `make_alias` → `get_table_alias`
  return a scalar that is the answer to a question, not a thing built to be
  handed over.
- `_build_table_objects` → `_add_table_objects` writes and returns nothing. It
  sits between `_check_rec_name` and `_check_active_name` in
  `odoo/orm/registration.py`, beside an `_add_inherited_fields` doing the same
  kind of work under the right verb.
- `_build_watcher` → `_arm_watcher` also acts rather than returns, and takes the
  word the module's own recovery log already uses for the operation
  ("re-arming watches").
- `make_key` → `action_generate_key` is a button that mints a key and returns an
  act-window action. The Button-actions row of §2.4 governs it and no assemble
  verb ever did. `check_access_make_key` moves with it, because §2.4.11 forbids
  splitting a pair across two spellings.

The bare verbs take a noun. Four were nested closures and are named for what
they return or do — `get_node_info`, `value_to_operand`, `get_column_type`,
`add_term`. Two were the memo bodies behind `_constraint_methods` and
`_onchange_methods` and take the spelling of what they fill, per §2.4.10's memo
rule. `Speedscope.make` → `prepare_document` and `Collector.make` →
`prepare_collector` are factories.

One `make_*` in core is **not** renamed: `WSGIRequestHandler.make_environ` in
`odoo/service/wsgi.py` overrides werkzeug's method of that name. A rename there
is not a rename, it is a silent unhooking.

## Alternatives considered

**Leave it, since the gate reports zero and §2.4.7 already documents the gap.**
Rejected because the documentation was the whole of the enforcement, and it had
already failed once: ADR-0082 swept core with the ratchet's own definition of the
population and reported the sweep complete, three days before this count found
45 more under a sentence in the same guideline. A gap named in prose beside a
number that excludes it reads as the number.

**Widen `classify` so the four verbs are flagged unconditionally, then sweep
whatever it reports.** This is the mechanical version and it was rejected on what
it would do to the *addon* floor, not to core. The verbs are payload-only in
`ABOLISHED` precisely because `naming_vocabulary` reads a name and not a
receiver; unconditional flagging moves the `naming` floor by the 21 model methods
that spell one today and by nothing else useful, while the population this record
sweeps — module-level functions, plain-class methods, closures — stays invisible
to it either way. The scope error is class membership, not the suffix list.

**Sweep the private names and leave the four public ones** — `make_response`,
`make_json_response`, `make_alias`, `make_key`. Rejected on ADR-0082's own
ground: `make_json_response` is declared in `odoo/http/_protocols.py` and
implemented in `odoo/http/_response.py`, so visibility would have split that pair
across two spellings, which §2.4.11 names as worse than a pair uniformly wrong.
The cost is real and it is a cost, not a veto: 134 files across three
repositories move in the same change.

**Leave `make_response` as a delegating shim**, which §2.4.14 invites for a
public-surface change. Rejected for the reason ADR-0082 rejected the `ensure_one`
shim, and more strongly here: `make_response` is the first method an addon author
meets when writing a controller, so a shim would leave the abolished spelling as
the one every tutorial and every existing controller shows.

**Rename `make_environ` with the rest**, for a core package with no `make_*` left
in it. Rejected: it is an override, and §2.4 governs names an author chooses.

## Consequences

`git grep -w make_response` returns two things in the four repositories: this
record, and ADR-0082, which cites the old spelling in the alternative it
rejected. Both are immutable and both are prose about a name that is gone, which
is ADR-0082's own amendment on the same point. `_make_corecords` survives the
same way, in ADR-0052 and in the `note` of `py_x2many_count`'s baseline.

Every controller in `enterprise` and `agromarin` moved in this change — 33 and 18
files. A controller written against this fork before 2026-08-30 calls a method
that no longer exists, and the substitution is mechanical and total.

A live database can hold `make_key` where no grep reaches it, exactly as
ADR-0082 found for `ensure_one`. The pre-migration is written rather than owed:
`base/migrations/1.24/pre-migrate_assemble_vocabulary.py`, with
`base/__manifest__.py` bumped to `1.24` in the same change so the directory
cannot be one an upgrade has already consumed. It carries the **17** renames that
are methods and excludes the module-level functions on ADR-0082's safe_eval
argument. It also excludes the seven bare verbs for a new reason and the opposite
one: `.make` is an attribute access on anybody's object, so anchoring on the dot
buys nothing there, while a nested closure is reachable by no attribute access at
all.

It was proved to run rather than assumed to, on the standard ADR-0082's second
amendment set: a database aged back to `1.23` with one planted block holding the
real calls beside every near-miss. The three attribute accesses moved
(`wizard.make_key()`, `request.make_response(body)`, `Query.make_alias(...)`);
the bare local `make_key = 1`, a longer name sharing the prefix and the two
excluded module-level functions survived untouched, `obj.make_index_name(...)`
included even though attribute access reached it; and the two routes the anchor
cannot take -- `record . make_alias` and `getattr(request, "make_response")` --
were logged with their row ids rather than rewritten.

Four figures in §2.4.7 moved with the sweep and are pinned, so the guideline
cannot drift back into describing the old tree: the `_prepare_*` population
(727 → 728), the assemble-verb reach (23 → 21) and the two figures that restate
each.

## Enforcement

`tooling/architecture/naming_core_vocabulary.py` is the checker ADR-0082's
Enforcement sketched, built here because that record's condition — "if the sweep
regresses often enough to want one" — was met by this sweep existing. Two sweeps
three days apart, both sized by a hand-written scan over a population the gate
could not report, is the evidence it asked for.

It is a **separate module from `naming_vocabulary.py`**, not a `--roots` flag on
it, and the three differences are why:

- It reads **every function** — module level, plain classes, nested closures —
  rather than the methods of model classes.
- It flags the four assemble verbs **unconditionally**. They are payload-only in
  the shared `ABOLISHED` table because that table is read by a checker that sees
  a name and not a receiver; widening it there would move the addon floor by
  names nobody has read.
- It flags a **bare** assemble verb, which `classify` cannot see at all.

Its scope is the core package including `odoo/tests` — the test *framework*,
production code that `_sources.is_test_path` excludes by the name of its
directory, and the one tree `test_excluded_trees_stay_empty.py` already records
as wrongly classified. `TestCursor` lives in a file called `test_cursor.py` and
is a cursor.

**Its floor is zero and it carries no debt**, which is what the sweep bought.
The survivors are an argued allowlist — `naming_core_allowlist.json`, thirteen
names, each with the reason it is not a violation — rather than a count. A floor
would admit the fourteenth silently; an allowlist entry has to be written down.
`test_naming_core_vocabulary.py` holds the allowlist to both directions: no
entry may name something core does not define, and none may name something
neither the gate nor its candidate report would have raised.

**One shape is reported and deliberately not gated.** A bare verb from the rest
of the abolished table — `delete`, `verify`, `validate`, `lookup` — is often the
contract being implemented rather than a naming choice. There are fourteen,
`--candidates` prints them, and they stay in §2.4.6's `[review]` tier where
reading the body is the only way to tell. Gating them would have meant fourteen
renames argued from a rule the guideline does not state mechanically.

All fourteen were read once, here, so the next person does not start from the
list. **Six are the contract and are not renames:**

- `AttachmentStorage.delete` and `DbStorage.delete` sit in a `read` / `write` /
  `delete` / `to_stream` interface over a file store. §2.4.3 reserves `read`
  and `write` for exactly that and says the pair "must not split across `_get_`
  and `_write_`"; `delete` is the third member of the same contract.
- `Command.delete` names x2many command code 2. It is public, written across
  four repositories and mirrored in the JavaScript client, and `Command.unlink`
  is a *different* command — the two names carry the distinction between
  deleting the record and merely unlinking it. Collapsing one to `remove` puts
  it beside `unlink` with nothing to tell them apart.
- `password.py`'s `verify` sits beside `hash` and `identify`: the passlib
  contract this class exists to answer to. §2.4.8 would send a never-raising
  bool to the Predicate row, and the external contract wins.
- `view_validation.py`'s `validate` is a binding decorator — `@validate("form")`
  registers a validator, the shape `@api.constrains` has. It is named for what
  it declares, not for what it does.

- `test_http`'s `MemorySessionStore.delete` reads as a half-finished sweep — it
  sits beside a `_remove_sid` and a `remove_from_identifiers` that ADR-0082
  renamed — and is not one. The class derives from werkzeug's
  `FilesystemSessionStore`, so `new` / `get` / `save` / `delete` are werkzeug's
  API and the two renamed neighbours are ours. **It is visible to the candidate
  finder only because the override test is a call test**: `_overrides_same_name`
  looks for `super().<name>()` in the body, and this override does not call up.
  A gate cannot resolve a base class it never imports, so an override that
  replaces rather than extends will always reach this list.

**Five are a real backlog, and each is a separate weighing:** `Registry.delete`
(whose own test file is called `test_registry_forget.py` — §2.4.12 says prefer
the test's word), `EnvironmentSet.lookup`, `Domain.validate` (it raises, so the
Validation row), the `ormcache` wrapper's `lookup` closure, and
`_seed_fixtures`'s `_inject`.

The remaining three are `Backend.delete` at its Protocol declaration and two
implementations, which is one decision about whether a backend's ORM-facing
member takes the reserved `unlink`.

`test_doc_restated_counts` pins the four §2.4.7 figures this sweep moved.
`tooling/architecture/doc_gate/module_view.py` and
`tooling/architecture/doc_gate/runtime_view.py` each name a renamed
symbol and block, which is what caught the reach of `make_index_name` and
`_build_server` into `doc/architecture/`.

## Amendments

### 2026-08-30 — the floor is six, not zero, and every one is in `odoo/tests`

Enforcement says the gate's floor is zero and that its survivors are an argued
allowlist rather than a count. The second half stands. The first was measured on
a working tree that carried another session's uncommitted sweep of `odoo/tests`,
and this record's own commit does not contain it: at that parent the gate reports
**six**, all in the framework tree — `delete_cookie`, `build_rpc_payload`,
`fetch_proxy`, `make_fetch_proxy_response`, `make_jsonrpc_request` and
`make_suite`.

The floor is therefore six, and the distinction Enforcement draws is the one that
matters: those six are **debt**, not survivors, so they are a floor and not
allowlist entries. Four already have chosen names in the sweep running in that
tree; the floor goes to zero in the commit that lands it.

`test_naming_core_vocabulary` asserts the boundary rather than the number — a
finding anywhere outside `odoo/tests` fails whatever the floor says. Pinning the
six by name was tried first and is wrong for the same reason the zero was: it
breaks on the framework sweep's commit and again on the re-bank, so it would have
had to be edited twice to stay true and once more to stop being a lie.

**Measuring a floor against a shared checkout is what went wrong**, and it is
`CLAUDE.md` §12 in a form that record did not anticipate: the trap it warns about
is committing another session's work, and this is the mirror — reading their
uncommitted work as your own tree's state and banking a number from it. Measure a
floor at the commit that will carry it.

### 2026-08-30 — the floor reached zero, and the two sweeps only work together

The amendment above says the floor "goes to zero in the commit that lands it".
This is that commit. The six are renamed and `naming_core` is re-banked to **0**
in exact mode, so the boundary `test_naming_core_vocabulary` asserts and the
count the baseline carries now agree without either being a list of names.

`fetch_proxy` is `prepare_proxy_response`, `make_fetch_proxy_response` is
`prepare_proxy_response_from_content`, `build_rpc_payload` is
`prepare_rpc_payload`, `make_suite` is `prepare_suite`, `delete_cookie` is
`remove_cookie`, and `make_jsonrpc_request` is `call_jsonrpc` — the one of the
six that is not the Payload row, because it performs the request rather than
assembling one.

**Neither sweep was green on its own**, and that is the part worth keeping. This
record's own commit left the gate reporting six; the framework sweep alone would
have left it reporting forty-five. The two were measured against a shared
working tree that carried both, which is how the floor came to be banked at zero
before either had landed — the mirror trap the amendment above names. What the
pair also shows is the ordinary form of it: a commit here swept up call sites
from the framework sweep's uncommitted tree while leaving its definitions
behind, so `modules/loading.py` called `loader.prepare_suite` against a
`loader.py` that still defined `make_suite`, and every addon reaching
`self.call_jsonrpc` faced an `HttpCase` that still spelled it
`make_jsonrpc_request`. **A pathspec commit takes the working tree, and a rename
is the one change whose halves fail silently apart.**
