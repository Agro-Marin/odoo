# ADR-0082: The method vocabulary reaches core

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

§2.4.13 scoped the method-naming vocabulary to model methods and exempted "the
framework packages below the ORM (`odoo/db`, `odoo/http`, `odoo/tools`,
`odoo/orm` internals)" on the ground that they "legitimately speak SQL and Python
data-structure vocabulary". `naming_vocabulary.py` implements a narrower rule
still — a class-membership test over `models.Model` and its siblings — so the
whole of the core package `odoo/` measured **0** while carrying **80** definitions the
abolished-verb table would have flagged anywhere else.

The exemption was written from the package names, not from the bodies. Read
against the bodies, the carve-out described a handful of the 80 and misdescribed
the rest:

- `_validate_borrowed_conn`, `_validate_copy_args`, `_validate_rec_name`,
  `validate_db_name`, `validate_esm_config` raise on failure. That is the
  Validation row exactly, in a package the ORM vocabulary was said not to reach.
- `_ensure_error_response` returns the response it built, `_ensure_xml_ids`
  returns an iterator and creates `ir.model.data` rows, `_ensure_field_triggers`
  returns a dict. Three producers spelled as assertions.
- `validate_csrf`, `verify_admin_password` and
  `verify_limited_field_access_token` answer a question and never raise —
  predicates, which the Validation row explicitly sends elsewhere.
- `validate_url` prepends `http://` and returns a URL. It validates nothing.
- `Field.ensure_computed` recomputes pending stored computes. It is a mutation.

None of that is SQL vocabulary or Python data-structure vocabulary. It is
ordinary misnaming, and the package boundary was hiding it — a file can be
sixteen names wrong and green, which §2.4.13 already said about the addon trees
and had not applied to itself.

`ensure_one` is the case that made this a decision rather than a sweep. It is a
public model method, so it is RPC-reachable, and it is the single most-written
name in the workspace: **6,574** occurrences across **2,115** files in four
repositories. A vocabulary that stops at the most-used name in the tree teaches
that the vocabulary is for other people's code.

## Decision

The vocabulary governs **every function in the core package `odoo/`** — module level, plain
classes and model classes alike. The package carve-out is retired; what survives
the vocabulary in core is a list of five names, not a directory.

`EnvironmentMixin.ensure_one` becomes **`check_singleton`**. It raises on
failure, so it is the Validation row, and the tail takes its word from the error
the method already raises (`Expected singleton:`) rather than from the arity.
No shim is left behind: §3 of the workspace `CLAUDE.md` carries no upstream
backward-compatibility constraint, and a shim would keep the abolished spelling
reachable — and therefore writable — forever.

`fetch` joins the reserved table as the ORM read operation. `BaseModel.fetch()`
loads stored values into the cache; `_fetch_field`, `_fetch_query` and
`_fetch_query_sql` are its internals. `_get_query` would promise a `Query`
return, and renaming the private half alone is the split §2.4.11 forbids.

Four further names keep an abolished token because the token is a noun:
`fill_temporal` (a `read_group` parameter and a context key), `ensure_db` (the
route flag declared in `addons/web`), `on_delete` (a field on
`ir.model.fields`), and control characters. `append_paths` keeps its verb
because both halves of the `_append_` reservation hold — an ordered list, and an
addition at its end, beside an `insert_paths` that takes the index.

## Alternatives considered

**Leave core alone, as §2.4.13 said.** Rejected on the evidence above: the
sentence describes five names and the tree held eighty. Keeping it would have
meant defending `_validate_borrowed_conn` as SQL vocabulary.

**Sweep only the ungated addon population** (`odoo/odoo/addons/*/models/`, ten
definitions). This is the reading §2.4.13 supports as written, and it is the
smallest defensible change. Rejected because it leaves the ORM's own
`_validate_fields` and `Field.ensure_access` — the names every addon author reads
first — spelled the way the guideline abolishes.

**Sweep the private names only, leaving `ensure_one`, `validate_csrf` and
`make_response` public.** Rejected: `validate_csrf` is declared in
`http/_protocols.py` and implemented in `_csrf.py`, and `_validate_fields` has a
stub in `_model_stubs.py` and a definition in `_constraints.py`. Splitting on
visibility would have split four of those pairs, which is the failure §2.4.11
names — a pair split across two spellings is worse than a pair uniformly wrong.

**Keep `ensure_one` as a delegating shim**, which §2.4.14 invites for a
public-surface change. Rejected for this fork specifically. The shim's value is
for callers outside the workspace, and the measured external surface is one
JavaScript string in `enterprise/voip`'s mock server; against that, a shim leaves
the abolished spelling as the shorter and better-known of two working names.

**Rename `BaseModel.fetch()` too**, so the family drops the abolished verb
outright. Rejected: `fetch` is a single token, so no abolished-verb rule reaches
it, and the canonical `_get_` is wrong for a method that returns `None` and warms
a cache. Reserving it states what is true.

## Consequences

`git grep ensure_one` finds nothing, in any of the four repositories. Anyone
reading a stack trace, an override list or a tutorial written before
2026-08-30 will see a name the tree no longer has; the rename is mechanical and
total, so the answer is always the same substitution.

The vocabulary now costs more to violate in core and less to explain: the scope
is "this repository", not "this repository except six packages whose names you
must remember".

`_check_fields`, `check_db_name` and `_get_row` each now share a spelling with an
unrelated method elsewhere in the workspace (`addons/rpc`'s test helper,
`tooling/hoot`'s validator, `DictBackend.get_row`). All three are in packages
that are never imported together with their namesake; the collision is in a
grep, not in a namespace.

**A live database can hold `ensure_one` where no grep reaches it.**
`ir.actions.server` stores Python in a column, and a call to the old
`ensure_one` is a plausible line in a server action written through the UI. Every *shipped* data
file in the four repositories is clean — the sweep rewrote them, and a scan of
every `name="code"` block finds no renamed name left — so nothing in this
workspace needs a migration. A database whose users have written their own
server actions does, and it is the ADR-0056 shape: a pre-migration rewriting the
name in every column that holds Python. None is written here, because this
workspace carries no such database (`CLAUDE.md` §5); one is owed before this
lands anywhere that does.

Three renames changed row rather than spelling, and that is the part a future
sweep should copy: `validate_csrf` → `is_valid_csrf` (Predicate),
`verify_hash_signed` → `resolve_hash_signed` (partial producer, §2.4.11),
`validate_url` → `normalize_url` (converter). Read the return before reading the
verb.

## Enforcement

`naming_vocabulary.py` does **not** gate this, and extending it to would be the
wrong shape: its class-membership test is what makes the addon count meaningful,
and a directory rule bolted onto it would fuse two populations under one floor.
The core sweep is held by the guideline text (§2.4.13, rewritten) and by review.

The shape a checker would take, if the sweep regresses often enough to want one:
a `--roots odoo/odoo --all-functions` flag on `naming_vocabulary.py` feeding its
own baseline in `tooling/ratchet/baselines/`, held at zero in `exact` mode, the
way `ruff` is. The census already walks every function — `census()` counts module
level helpers and plain-class methods separately — so the measurement exists and
only the flag and the floor are missing.

Two gates do hold pieces of it today. `test_doc_restated_counts` pins the
`infix_abolished` and `bool_return_is_not_a_predicate` figures this sweep moved,
so the guideline cannot drift back into describing the old tree.
`web/machine_doc_v1/factcheck.sh` greps for `def check_esm_config` by name and
blocks, which is what caught the rename's reach into a machine doc.

## Amendments

### 2026-08-30 — the Consequences overstate what the grep returns

Consequences opens "`git grep ensure_one` finds nothing, in any of the four
repositories." That is true of every line of **code**, and false as written: the
grep returns this record and the §2.4.13 prose that documents the rename, which
are the two places the old spelling is supposed to survive. Read the sentence as
a claim about the tree, not about the documentation of the tree.

The distinction is the one this record is about. A name kept in prose *because
the prose explains why it is gone* is not the abolished spelling staying
reachable — nothing dispatches to it, and no author copies it from here by
accident. A checker for the sweep would scan definitions, not documents.

### 2026-08-30 — the pre-migration owed by the Consequences is written

Consequences said no pre-migration was written and that one was owed before this
lands on a database whose users have written their own server actions. It is
written: `base/migrations/1.23/pre-migrate_method_vocabulary.py`, rewriting the
43 renamed **methods** across the three columns ADR-0056 established —
`ir_act_server.code`, `ir_actions_server_history.code`, `ir_model_fields.compute`.

Two things it does that ADR-0056's did not have to, both consequences of this
being 59 renames rather than one:

- **It is anchored on attribute access, not on a word boundary.** Stored Python
  runs under `safe_eval` with no import, so the 16 renamed module-level
  functions are unreachable from it and are excluded outright; a method is
  reachable exactly one way. `.delete_rows` is ours and `delete_rows` on its own
  is a local of the author's — a distinction ADR-0056 never had to draw, because
  `_for_xml_id` is nobody's variable name and `delete_rows` is everybody's.
- **It reports what it could not reach.** Whitespace around the dot and a
  `getattr` with a string literal are the two routes the anchor misses; both are
  logged with row ids rather than rewritten blind.

It also answers that record's amendment, which is the reason this one exists.
`3c531a8ce43f`'s script never ran, because it was added under a version an
upgrade had already consumed and Odoo skips such a directory in silence. This
one ships under `1.23` with `base/__manifest__.py` bumped to `1.23` **in the same
change**, so the number cannot have been consumed; and it was proved to run
rather than assumed to, on a database aged back to `1.22` with planted stored
Python in all three columns. The probe kept the near-misses in the same row as
the real calls — a bare local, a longer name sharing the prefix, an excluded
module-level function — and all three survived untouched while the three real
calls moved.

### 2026-08-31 — the sweep reached `addons/`, and the stored-Python exposure was measured

This record's Decision governs the core package. The vocabulary was afterwards
applied to `addons/` in eight rings, and the `naming` ratchet went **95 → 0**:
project, POS, mail, website, l10n, payment/account, and a final ring of eleven
modules. Each ring was verified by installing it into one database with every
module's tag selected and diffing the failing set against an rsync copy of the
working tree with only that ring's rename inverted.

**A per-ring baseline is blind to the ring before it.** It clears a ring of
failures in its own modules and cannot see one an *earlier* ring caused —
`account_peppol` sends mail, the mail ring had renamed mail methods two commits
earlier, and both its failures were `assertSentEmail` assertions, which is what
a hook that stopped firing looks like. Inverting all seven maps at once (7,387
occurrences over 2,332 files) reproduced the same two failures, which is the
measurement that clears the sweep rather than the ring.

**Three names could not be renamed by word boundary**, and each is the same
distinction the pre-migration draws between `.name` and a bare name:

* `_validate_amount` and `_validate_leave_request` are planted in
  `tooling/architecture/test_naming_vocabulary.py` as the FIXTURES asserting
  that `_validate_` is detected. Rewriting them would have edited the gate's own
  evidence that the rule it enforces is real.
* `assign_partner` is a local variable in the very module that defines a method
  of that name on `crm.lead`. A word-boundary rewrite renames the local too,
  consistently, so nothing raises and the tree keeps a local named after a
  method.

**The Consequences' owed pre-migration is answered, and mostly answered by
measurement rather than by scripts.** Every shipped `<field name="code">` and
`<field name="compute">` in the four repositories was scanned for all ~110
renamed names. **One record matched**: `mail`'s Fetchmail cron, inside
`<data noupdate="1">`, which the upgrade would never have rewritten —
`mail/migrations/1.26` carries it and was proved to fire on a database aged back
to 1.25. No other module ships stored Python naming a renamed method.

Eight further modules renamed a **public** method (`point_of_sale`,
`pos_loyalty`, `website_crm_partner_assign`, `l10n_ar`, `l10n_it_edi`,
`stock_picking_batch`, `html_editor`, `iap`). None ships a record that calls
one, so a pre-migration in each would do nothing here — and ADR-0056's own
amendment removed such a script for exactly that reason, noting that a migration
which never runs "was dead code that read as a live guard". They are not
written.

**What remains is a database this workspace cannot see**: a server action a user
wrote through the UI, calling one of those public names. The query that answers
it, on a real database, before upgrading:

```sql
SELECT 'ir_act_server' AS src, id, code FROM ir_act_server
 WHERE code ~ '\.(remove_cash_in_out|remove_opening_control_session|check_lock_dates
                 |check_coupon_programs|update_assigned_partner
                 |update_salesman_of_assigned_partner|update_geo_location
                 |get_l10n_ar_vat|check_codice_fiscale|update_batch_user
                 |remove_snippet|check_warning_alerts)\M';
```

If it returns rows, the recipe is `base/migrations/1.23` scoped to the module
that owns the name, under a version above the module's own — anchored on the
leading dot, because these names are ordinary enough to be somebody's variable.
