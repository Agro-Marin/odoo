# `partner` — test map

Every test class in `tests/` and what it pins. All are `post_install`, so
`--test-enable` without `-i partner` or `-u partner` skips them silently.

```bash
odoo-bin -c <conf> -d <db> -i partner --with-demo --test-enable \
    --test-tags '/partner' --stop-after-init
```

`--with-demo` matters for anything reading cohorts: see TRAPS.md trap 1. A regating is the
one thing this command cannot check: menu groups accumulate across upgrades, so verify one
on a **fresh** database (TRAPS.md trap 5).

| Class | File | Pins |
|---|---|---|
| `TestResPartner` | `tests/test_res_partner.py` | `_get_backend_root_menu_ids` includes this app's root menu, so a contact opened from a notification lands in Contacts |
| `TestSearchAge` | `tests/test_res_partner.py` | `_search_age`: that a non-stored age is still answerable in SQL, that every operator inverts against `birthdate`, that the strict forms shift a year, that a contact with no birthdate matches neither a comparison nor its negation, that `= False` asks whether an age is *set* rather than whether it is zero, that a fractional age is a `UserError` and not a 500, and that the field declares no aggregator |
| `TestActivityIcon` | `tests/test_activity_icon.py` | the systray activity entry for `res.partner` uses this module's icon rather than `base`'s |
| `TestPartnerAgeRange` | `tests/test_res_partner_age_range.py` | the cohort model: bound validation, overlap rejection, the open-ended newest cohort, reclassification when a cohort's bounds move, that an **archived** contact is swept like any other, and that a new cohort chains onto the highest closed bound |
| `TestPartnerAgeRangeUi` | `tests/test_age_range_ui.py` | the cohort model is *reachable* — the menu tree a partner manager is actually **drawn**, declared views, the birthdate input the classifier needs, filtering as well as grouping, and that `base.group_partner_manager`'s write right can be exercised |
| `TestBirthdayFilters` | `tests/test_res_partner.py` | the birthday filters, run as the **domains the search view really carries** rather than as copies of them: *Birthday Today*, *Birthday This Month*, *Without Birthdate*, the month group-by, and that an index covers `date_part(birthdate)` |
| `TestPartnerAgeRangeScale` | `tests/test_res_partner_age_range.py` | what the configuration screen has to answer: the bounds named in `display_name` (and that an unnamed draft does not print "False"), `partner_count`, the uncovered years in `gap_before` (and that the oldest cohort's open edge is not one, and that archiving a *middle* band opens one while archiving the *lowest* does not), that both survive an edit to a neighbouring band, that an empty cohort survives the group-by, and that a cohort opens its contacts |
| `TestPartnerAgeRangeClassificationRights` | `tests/test_res_partner_age_range.py` | that classifying a contact does not need the writer to be able to read the cohorts -- the fixture grants a portal group write on `res.partner` and asserts it still cannot read `res.partner.age.range` |
| `TestUi` | `tests/test_ui.py` | the `debug_menu_set_defaults` tour, and that a company's Tax ID label follows the company country |

## `TestPartnerAgeRangeUi` exists because the model was unreachable

`partner` shipped the cohort model, its tests and an ACL granting
`base.group_partner_manager` create/write/unlink, while declaring no view, no action and no
menu for it anywhere in the workspace. The right could not be exercised and cohorts could
only arrive from a data file. These tests fail if that regresses.

**Reachability has three layers, and the first version of these tests only checked one.**
Declaring the view, action and menu left the branch gated on `base.group_system`, so the
group the ACL empowers was still drawn nothing; and the birthdate the whole classifier reads
was on no form at all. The tests missed both because they asserted around the user's path
rather than along it — `with_user(manager).create(...)` exercises the ORM, which no menu
gates, and `menu.parent_id == config_menu` is true whether or not anyone can see either.

So the assertions now go through the rendered artefacts: `load_menus` for the menu tree
(not `_visible_menu_ids`, which reports the cohort entry visible while its parent is pruned,
see TRAPS.md), and `get_view` / `get_combined_arch` for the form and the search view. An
assertion that cannot fail when the behaviour regresses is not coverage.

## The configuration sweep replaced two hardcoded pairs

`test_every_configuration_screen_drawn_to_a_manager_is_one_they_can_save` was
`test_administrator_only_screens_stay_administrator_only`, which named Industries and
Identifier Types and checked those two. The rule is universal -- a leaf a manager may only
read must carry the narrower group itself -- and stating it as a list covered only the
instances somebody had thought of. **Countries was the third, and the enumerated version
passed while a manager was drawn a screen `res.country`'s ACL refuses to let them save.**

The sweep now derives the leaves from the menu tree, resolves each action's `res_model`, and
asserts `drawn => writable`. Verified to fail, not merely to pass: run against a database
installed before the regating it reports exactly
`Contacts/Configuration/Localization/Countries -> res.country` out of 7 screens swept. It
also asserts that it swept something, so a tree that stops resolving cannot pass by
asserting nothing.

## `TestUi.test_set_defaults` is fragile by nature

The tour drives the debug menu's "Set Default Values" dialog, which is why the test asserts
its own preconditions in Python before starting: `website` editable, absent from the action
context, and `is_company` still defaulted by that context. Traps 2 and 3 explain why those
three assertions are load-bearing — get the target field wrong and the tour fails at the last
step with a selector timeout that says nothing about the real cause.
