# ADR-0056: Stored Python is a binding no checkout holds, and `_for_xml_id` is renamed across it

- **Status:** Accepted; stored half amended 2026-08-22 (see *Update*)
- **Date:** 2026-08-20

## Context

`doc/coding_guidelines.rst` §2.4 sorts the bindings a rename must carry into
three kinds: greppable inside the workspace, computed at runtime through
`getattr`, and reachable from outside the workspace. It describes the third as *a
public method an integration may call over RPC*, and a reader takes from that a
test they can apply — a leading underscore means the third kind does not arise.

The test is wrong, and `ir.actions.server` is why. Its `code` field stores
**Python source in a database column**. That source runs with `env` in scope and
calls whatever it likes, private or not, and the field is edited in the web
client, so most of what it holds was never in any checkout. Measured over the
shipped data files of this repository, which is only the half a grep can see:
101 distinct private method names, in 110 code blocks, across 68 files. One of
them, `_fetch_mails`, already carries a verb §2.4 abolishes and the `naming`
ratchet counts — a rename the section asks for, with a binding nothing checks.

`ir.actions.actions._for_xml_id` made this concrete and breaks the section on its
own terms. Its first token is the preposition `for`, so
`naming_vocabulary.classify` reads a token carrying no rule and reports nothing;
§2.4's *the verb leads* governs it and no gate does. Its name also hides its
return type, which is the same dict `_get_action_dict` returns four lines below
it and says so — and `base`'s own machine doc had recorded it as "Get action
record by XML ID", which is what the name led a reader to believe and is not what
the method does.

Two facts bound the cost. The name came with the 19.0 baseline, which §2.4's *a
rename carries its bindings* settles: that is a note about effort, not an answer,
and this fork carries no upstream compatibility constraint. And the `addons_path`
of this workspace resolves to the four checkouts and an empty downloaded-addons
directory, so there is no unvendored addon source. The source surface is exactly
what we can rewrite; the database is not.

## Decision

`ir.actions.actions._for_xml_id` becomes `_get_action_dict_by_xml_id`, in every
repository of this workspace in one change — 535 occurrences over 351 files in
`odoo`, `enterprise` and `agromarin`, including the six `<field name="code">`
blocks that ship a server action calling it.

The database half was carried by a migration (removed 2026-08-22, see *Update*),
`base/migrations/1.8/pre-migration.py`, which rewrote the name inside every
column of a database that stores Python: `ir_act_server.code`,
`ir_actions_server_history.code` and `ir_model_fields.compute`. It matches on
Postgres word boundaries so a name that merely contains the old one —
`_get_tax_ids_for_xml_id` in `l10n_nl` — is left alone.

No shim is left. The workspace is the whole of the source surface and the
migration the whole of the stored surface, so a delegating alias would protect
nothing while costing the second name §2.4 exists to remove — ADR-0053's
reasoning for `precision_get`.

Generally: **a method name written into stored Python is a binding of the third
kind, whatever its leading underscore says.** The question a rename must answer
is not whether a method is public but whether its name is written down anywhere
this workspace cannot rewrite.

## Alternatives considered

**Leave `_for_xml_id` alone.** The recorded position until this record. Its three
available arguments each fail: that the name came from upstream, which the fork's
posture voids; that the method is private, which is the belief this record exists
to correct; and that 535 call sites is too many, which §2.4 answers directly —
greppable bindings are cost, not a veto. What remains is the stored half, and
that argues for writing a migration rather than for keeping a name that
misdescribes its own return value.

**Rename the source and skip the migration.** The dangerous option rather than
merely the incomplete one. Every shipped block would be correct, every test would
pass, and a server action a user wrote would raise `AttributeError` the next time
it ran — at whatever hour its cron fires, in a traceback pointing at a database
row rather than at this commit.

**Rewrite `ir_act_server.code` and leave the history table.** The cost falls the
other way from how it first reads. `ir.actions.server.history` keeps up to 100
previous bodies per action so a user can roll back to one. An entry left
unrewritten is a body that fails on restore, defeating the feature; an entry
rewritten is a trail attributing text to an author who did not type it. The trail
is an undo buffer for a code editor, not a legal record, so restorability wins.
The migration logged the two row counts separately.

**Rewrite `ir_ui_view.arch_db` as well.** A QWeb expression can name a model
method, so the column is reachable in principle. Rejected: no occurrence is
attested here, the column is translated `jsonb` rather than text, and rewriting
view source to cover an unobserved case buys less than it risks.

**Add a gate instead of renaming.** Not an alternative — the follow-up, recorded
in §2.4 rather than here. A checker that reads `<field name="code">` the way
`naming_vocabulary` reads `.py` would move the shipped half of this population
from unenumerable to merely wide, and would have caught `_fetch_mails`. It is a
new blocking gate and owes its own record.

## Consequences

As recorded, a database upgraded to `base` 1.8 had its stored Python rewritten
once, and one skipping 1.8 still ran the script, because Odoo runs every
migration directory between the installed and the target version. The *Update*
below retires that mechanism.

Code outside this workspace that calls `_for_xml_id` — an unvendored addon, an
RPC client reaching a private method by ignoring the convention — breaks with an
`AttributeError` naming the method. The loud failure, and the one available:
there is no silent-wrong-answer mode, because no method answers to the old name.

The `naming` ratchet does not move. `for` is not an abolished verb, so this
rename is invisible to the gate that counts the campaign — the same observation
§2.4 now records about the whole of `ir_actions.py`, and the reason the rule it
enforces is `[review]`.

## Enforcement

None by gate, stated rather than hidden. `naming_vocabulary.py` gained
`stored_code_references()`, which counts the population this record is about and
feeds the three figures §2.4 states through `doc_restated_counts`; it measures
the problem and forbids nothing. The rename is held by the absence of the old
name — `git grep _for_xml_id` over the workspace returns this
record, the §2.4 paragraph, and `l10n_nl`'s unrelated `_get_tax_ids_for_xml_id`.
No call site survives.

## Update — 2026-08-22: the migration is removed, not superseded

`base/migrations/1.8/pre-migration.py` never ran on any database it was written
for. `52f7aceeadc9` bumped the manifest to 1.8 and an upgrade consumed that
number; `3c531a8ce43f` added the script afterwards, against a version already
installed. Odoo runs `migrations/<v>/` only when `<v>` exceeds the stored
`db_version`, so on every database at `19.0.1.8` it was skipped in silence — no
warning, exit 0. It was dead code that read as a live guard.

It is removed rather than renumbered, because on the database it exists for it
has nothing left to do: `ir_act_server.code`, `ir_actions_server_history.code`
and `ir_model_fields.compute` all match zero rows on `_for_xml_id`, and no view
carries `history_wizard_action`. The six shipped server actions live in XML and
were rewritten from source by the ordinary upgrade. That the columns are clean
*without* the script having run is also the evidence that no hand-written stored
Python here ever called the old name.

This re-opens **Rename the source and skip the migration** above, which this
record rejected as the dangerous option, for any database whose stored Python is
*not* already clean — a developer's local copy, or a restore predating the
rename. The argument against it is unchanged and still correct; what changed is
that the population it protects is empty here. A database that needs it should
restore the script from `3c531a8ce43f` under a version number above its own.
