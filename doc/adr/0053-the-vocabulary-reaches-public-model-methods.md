# ADR-0053: The naming vocabulary reaches public model methods, and renaming one is a surface change

- **Status:** Accepted
- **Date:** 2026-08-19

## Context

`doc/coding_guidelines.rst` §2.4 fixes a verb for each family of model method
and prints every one in its private spelling: `_get_`, `_prepare_`, `_check_`,
`_update_`, `_add_`, `_remove_`. It never says what the public form is. A reader
looking for the rule that governs a method with no leading underscore finds
nothing, and the tree has taken the silence as an exemption.

The reader on decimal.precision, spelled precision_get, is what the silence
cost. It puts the model's own noun in front of the verb, on a model whose name
already is that noun, so the prefix carries no information — and the section's
*verb leads* rule, which does govern it, was added on the assumption that a
namespace prefix is at least sometimes a protocol. Here it is not even that.

The method is not an incidental helper. `odoo/orm/fields/numeric.py` resolves a
`digits='Product Price'` declaration through it, `odoo/tools/formatting.py`
formats through it, `odoo/addons/base/models/ir_qweb_fields.py` renders through
it, and `tooling/architecture/model_member_surface_check.py` pins it as one of
the `(model, member)` pairs the framework may call on an addon-owned model. So it
is a declared contract between core and `base`, and it is public — which on a
model means reachable over RPC by any client that knows the name.

That is why this is a record and not a guideline entry. The register does not ask
for one for a naming rule; it does ask for one when a public surface changes and
the cost is paid outside this repository. Both are true at once.

## Decision

The vocabulary in §2.4 governs public model methods. The public form of a family
is the private form without the leading underscore and with the verb still
leading: a getter is `get_*`, a payload builder is `prepare_*`, a validator is
`check_*`. Nothing else about the rule changes.

The reader on decimal.precision that was spelled precision_get becomes
`get_precision`, with every call site in every repository of this workspace
rewritten in the same change and the surface pin moved with it.

Renaming a public model method is weighed as a change to a public surface. It is
not licensed by the vocabulary alone: the callers are not all greppable, and a
method reached only over RPC leaves no trace in any tree a gate can scan. **A
rename that cannot be completed inside the workspace is not begun.**

## Alternatives considered

**Leave `precision_get` alone and exempt public methods from §2.4.** The honest
version of the status quo, and what a reviewer is most likely to propose.
Rejected because the exemption has no boundary: the name is public for historical
reasons rather than by design, and a rule stopping at the underscore would leave
every RPC-reachable method permanently outside the vocabulary while the section
claims to govern the model layer. The surface argument is a reason to weigh a
rename, not a reason to make the name unreviewable.

**Keep `precision_get` as an alias forwarding to `get_precision`.** Preserves any
caller outside the workspace at the cost of two names for one operation — the
condition §2.4 exists to remove — and an alias nothing calls inside the tree is
an alias nothing tests. If a deprecation window is ever wanted, it belongs in a
mechanism that expires, not a second definition that does not.

**Rename it and leave the sibling repositories to catch up.** Rejected outright.
The pin in `model_member_surface_check.py` is exact in both directions, so the
core half would fail its own gate until the pin moved, and the addon half would
raise `AttributeError` at the first `digits=` resolution.

**Write no record and treat it as a naming rule.** What the previous two
guideline revisions did, correctly, for rules touching only private methods.
Rejected here because the first alternative above is plausible, which
`doc/adr/README.md` names as the strongest single reason to write a record.

## Consequences

Any code outside this workspace calling `precision_get` over RPC or from an
unvendored addon breaks, with an `AttributeError` naming the method — the best
failure available: loud, immediate, and naming the thing that moved. There is no
silent-wrong-answer mode.

The vocabulary now has a public half, which enlarges what a reviewer may object
to. That is the intent. It also enlarges what a rename may cost, which is why the
decision pairs the rule with the weighing.

`naming_vocabulary.py` does not gain public methods as a new population. It
already counts every method declared on a model class regardless of leading
underscore; what it cannot see is a verb in second position, a separate limit
recorded in §2.4 and not addressed here.

## Enforcement

`model_member_surface_check.py` holds the name. Its `(model, member)` set is an
exact ratchet in both directions, so the pair `("decimal.precision",
"get_precision")` cannot be renamed again, dropped, or joined by a second member
without appearing in a diff of that file. It is the only gate that knows the
method by name, and that is enough: the rename cannot be half-applied without it
failing.

The rule about the public form is `[review]`. No checker decides whether a public
method's first token is a verb, for the same reason none decides the
`_get_`/`_prepare_` split.
