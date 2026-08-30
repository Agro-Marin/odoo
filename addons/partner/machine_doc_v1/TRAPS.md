# `partner` — traps

Each entry cost a wrong conclusion at least once. They are ordered by how quickly they
mislead.

## 1. Demo data is OFF by default in this fork

`--without-demo` is the default here; upstream's is the opposite. A database created with
plain `-i partner` has `ir_module_module.demo = f` and loads **neither**
`data/res_partner_age_range_demo.xml` nor `data/mail_demo.xml`. Pass `--with-demo`.

Worse, demo installability **cascades**: `ModuleNode.demo_installable` is
`all(p.demo for p in self.depends)`, so if `base`'s demo data fails to load, every module
that depends on it silently installs without demo — and the only trace is one
`WARNING ... demo data failed to install` line, because `load_demo` catches the exception.
A module showing `demo = f` is therefore not evidence about *that* module.

This is not hypothetical: the `company_name` removal left three
`<field name="company_name">` lines in `base`'s own demo file, which raised
`ValueError: Invalid field 'company_name' in 'res.partner'` and disabled demo data for the
entire workspace. Fixed, but the shape recurs whenever a field is dropped.

## 2. A context default cannot be overridden by a user default

`default_get` (`odoo/orm/models/mixins/create.py`) reads the context **before** `ir.default`:

```python
for name in fields:
    if name in context_defaults:
        defaults[name] = context_defaults[name]
        continue
```

`action_partner`'s context sets `default_is_company`, so no saved default for `is_company`
can ever take effect from this action. Any test or feature that means to demonstrate
"Set Default Values" must pick a field the action does **not** name — which is why
`debug_menu_set_defaults` uses `website`.

## 3. The debug menu only offers fields holding a truthy value

`getDefaultFields` in `addons/web/static/src/views/debug_items.js` skips a field when `!value`, and also when it is
invisible or readonly in the current view. Consequences:

- A Boolean toggled **off** disappears from the list, so "set this false as the default" is
  not expressible through the dialog at all.
- `lang` is invisible while only one language is installed, and `type` belongs to the child
  contact rows rather than the top-level form. On a stock English database the only
  offerable field with a truthy default is `is_company`, which trap 2 rules out.

A tour that means to save a default therefore has to *type a value first*.

## 4. Two different phone searches, and they used to disagree

Finding a contact by phone number goes down two independent paths:

- The **search panel** uses `phone_mobile_search`, which `phone_validation` substitutes for
  the `phone` field in `base.view_res_partner_filter`. It strips non-digits on both sides and
  is backed by `regexp_replace` indexes built in `mixin.mail.thread.phone.init()`.
- Every **Many2one autocomplete** uses `name_search`, which reads `_rec_names_search`.

`_rec_names_search` named no phone field, so a number pasted into the Contacts search panel
found the contact while the same number typed into a Customer field found nothing.
`phone_validation` now appends `phone_mobile_search` to `_rec_names_search`, as a `@property`
so it extends whatever `base` lists rather than restating it.

When probing this by hand, use `ilike`: `('phone_mobile_search', '=', '5550199')` matches
nothing because `=` compares the whole normalised number, and it is easy to conclude from
that one probe that phone search is broken everywhere.

## 5. `<menuitem groups="...">` only ever ADDS a group

`odoo/tools/convert.py` builds the value as one `Command.link` per name — never a
`Command.set`. So narrowing a menu's audience in XML and running `-u` leaves the previous
group attached: the change reads as applied, the old audience keeps the screen, and nothing
warns. Only a `-group` entry (which emits `Command.unlink`) or a database created after the
change shows the truth.

This invalidates the obvious way to check a regating: reverting the XML, re-upgrading and
re-running the tests. The old group is re-added on top of the new one and the test passes
for a reason that has nothing to do with the code. **Verify a menu's audience on a fresh
database**, and remember that the widening in §"Menu tree" of ARCHITECTURE.md needs no
migration precisely because it is additive.

## 6. `sudo()` carries privileges, not `active_test`

`_add_partners_to_compute` sweeps `res.partner` to re-derive `age_range_id`. `res.partner`
has an `active` field, so a plain `search` silently drops archived contacts
(`odoo/orm/models/mixins/_query.py`), and an archived contact keeps a stored cohort no bound
supports. `sudo()` looks like it should cover this and does not: it answers *who* is asking,
not *what* is visible. The sweep spells `with_context(active_test=False)` for that reason.

`agromarin/marin` carries a migration written to repair exactly this drift, which is what a
missing `active_test` looks like from downstream.

## 7. The bounds cannot be fractional, so do not guard them

`min_value` and `max_value` are Floats, which invites a constraint that they be whole years.
There is no way to violate it: both declare `digits=(16, 0)`, and the ORM rounds every write
to the declared precision -- `1980.5` is stored as `1981.0`. A `@api.constrains` for whole
years is unreachable code. (Direct SQL bypasses the rounding, and nothing in this module
writes the table directly.)

## 8. The cohort name is unique case-insensitively, and the rule can be absent

`_name_uniq` is a `models.UniqueIndex` over `lower(name)`, not a
`models.Constraint("UNIQUE(name)")`. Two consequences, in order of how often they mislead.

**A unique index that cannot be built does not fail the upgrade.** If a database already
holds two cohorts whose names differ only by case, `CREATE UNIQUE INDEX` fails, Odoo logs
`could not create unique index "res_partner_age_range_name_uniq"` and the module loads
anyway. The upgrade exits 0, the data is untouched and the rule is simply not enforced --
the same state as before this index existed, so nothing regresses, but the rule you are
reading in the source is not necessarily the rule the database holds. Verified: the index
is absent, both rows survive, and removing one and re-running `-u partner` builds it. Check
`pg_indexes` before concluding the rule is in force.

**The conversion this rests on used to be impossible.** Replacing a `Constraint` with a
`UniqueIndex` of the same name silently did nothing -- `Index.apply_to_database` read a
constraint's backing index as an index already in place -- and then made the *next* upgrade
fatal, because the reflection recorded type `i` for an object PostgreSQL holds as type `u`
and `DROP INDEX` cannot release a constraint's index. That was fixed in `odoo` `2c60f5f3d33`,
which is what made this declaration possible; the upgrade path is exercised end to end
(a database built on the constraint, upgraded onto the index) and the framework's own
coverage is `odoo/addons/base/tests/test_table_object_conversion.py`.

## 9. `res.partner.age.range` bounds are years, and half-open

`min_value` and `max_value` are birth **years** stored as Floats, not ages, and the interval
is `[min, max)`. A cohort "1965-1980" is therefore written `min_value = 1965`,
`max_value = 1981`. Writing `1980` produces a cohort that silently excludes everyone born in
1980. `max_value = 0` is the open-ended marker, valid only on the newest cohort.

## 10. `agromarin` also seeds cohorts, through a key the loader ignores

`agromarin/marin_data` lists its cohort file under an `oca_data_manual` manifest key, which
is not a key the module loader knows, so installing that module loads nothing. Those records
arrive only when something imports them by hand — at which point they can collide with the
demo cohorts here, both on the unique name constraint and on `mixin.band`'s overlap check.

## 11. On an Integer field the ORM cannot tell `0` from "not set"

`('age', '=', 0)` and `('age', '=', False)` are **the same domain**. Measured by spying on
what actually arrives: `('age', '=', 0)` reaches the field as `('in', OrderedSet([False]))`
and is then decomposed to `('=', False)`, so `_search_age` receives `False` for both and no
implementation can separate "aged zero" from "has no age".

**The fold is confined to `=` and `!=`, and it is worth knowing exactly that.** The ordering
operators are untouched -- `('age', '>', 0)` arrives as the integer `0`, as do `>=`, `<` and
`<=`. So the "not set" branch below must be reached only for `=`/`!=`; widening it to every
operator would turn "older than nobody" into a `UserError` on a domain that works today.

The fold therefore decides which of the two readings the pair must carry, and it is the one
every generic tool asks: `= False` is the framework's spelling of *not set*, and it is what
the client's "is not set" filter emits. `_search_age` answers it as `birthdate = False`.
`isinstance(False, int)` is `True`, so this has to be settled **before** any numeric guard --
the unguarded path reads the value as `0` and answers "is not set" with every contact born in
the last twelve months.

Two consequences worth knowing before reopening this:

- Exactly-zero is not expressible through `=`. It is `age >= 0` intersected with `age < 1`.
- The invariant in ARCHITECTURE.md -- "a contact with no birthdate matches no comparison,
  negation included" -- is about the **ordering** operators, which is also exactly the set the
  fold leaves alone. `=` and `!=` against `False` are
  the is-set question, not comparisons, and they answer it. `TestSearchAge` splits the two
  for that reason.

## 12. `group_expand` does not fire in `formatted_read_group`

It is gated on the `read_group_expand` context key
(`addons/web/models/web_read_group_helpers.py`), which `web/static/src/model/relational_model`
sets on every grouped view. So `age_range_id`'s expansion is real in the client and invisible
to a bare `formatted_read_group([...], ["age_range_id"])` -- which reads exactly like the
feature not working. Assert it through `web_read_group` with the context key, as
`TestPartnerAgeRangeScale` does.

## 13. Private Information is gated by the view, not by the fields

The page carries `groups="base.group_partner_manager"`, which hides the widgets. It does not
restrict the fields: a user holding only `base.group_user` reads `birthdate`, `gender`, `age`
and `age_range_id` on any contact through export, RPC, an optional list column or a saved
filter. **This is known and unfixed**, not an oversight, and gating the fields is a decision
rather than a patch:

- `age` and `age_range_id` are this module's, so `groups=` on them costs one line each -- and
  buys nothing while `birthdate` is open, since the age is a trivial reading of it.
- `birthdate` and `gender` are `base`'s. `agromarin/partner_relationship` computes on
  `partner_id.gender` and `agromarin/remote_dav_sync` reads `partner.birthdate` when it builds
  a vCard; a compute or a controller running as a non-member raises rather than degrading, so
  gating either one needs those call sites decided first.

The honest summary is that the page is a *placement*, not a permission.

## 14. The cohort sweep is synchronous and has no ceiling

`_add_partners_to_compute` searches **every** matching contact and recomputes them inside the
caller's transaction, on every bound edit, archive and unlink. Measured at ~15k contacts per
second (2085 in 0.14 s), so a sixteen-year cohort over a 500k-contact database at 60%
birthdate coverage is ~60k rows and several seconds of row locks on `res_partner`, the most
contended table there is.

**This is unchanged and deliberate.** Deferring the tail to a cron would make the
classification eventually consistent, and `test_06`, `test_11` and `test_13` all assert it is
immediate after a flush. Narrowing the sweep to the symmetric difference of the before/after
spans is the change that preserves those assertions -- a one-year nudge on a sixteen-year
cohort currently sweeps all sixteen -- and it is intricate enough around `active` flips to
deserve its own design rather than a drive-by.


## 15. `gap_before` and `partner_count` read state no `@api.depends` can name

One reads every other band on the scale, the other reads the address book. Neither is a
function of the record's own fields, so the ORM has nothing to invalidate them on: moving the
band *below* used to leave a cohort reporting a gap that edit had just closed, and only within
the same transaction, which is why it survives a casual click-through in the interface.

`_add_partners_to_compute` is the one chokepoint every create, write and unlink passes
through, so it drops both caches model-wide. That covers every edit made *to the scale*.
It does not cover the other direction: change a contact's `birthdate` and a cohort's
`partner_count` is stale for the rest of that transaction. Nothing in the interface reads a
cohort in the same request that edits a contact, so this is left alone rather than paid for
with a stored counter.
