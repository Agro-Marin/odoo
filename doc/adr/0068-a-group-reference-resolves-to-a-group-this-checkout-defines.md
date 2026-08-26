# ADR-0068: A group reference resolves to a group this checkout defines

- **Status:** Accepted
- **Date:** 2026-08-26

## Context

`res.users._has_group` resolves a group by external id through
`SetDefinitions.get_id`, which returns `None` for a reference it does not know.
`None in self._effective_group_ids()` is `False`, so an unresolvable reference
answers **"not a member"** and nothing is logged, raised or counted.

For a *positive* check that is the safe direction — `has_group("x.group_y")`
with `x` uninstalled denies, which is what the caller wanted. For a **negated**
one it inverts. `has_groups` ends with `return not positives`: a spec of only
negations, none of which resolve, falls through to `True`. Measured on the
administrator:

    has_groups('!base.group_system')  -> False   correct
    has_groups('!base.group_sytem')   -> True    typo, grants

The reach is not hypothetical. `ir_qweb.py` compiles every QWeb `groups=` and
`t-groups=` attribute into `self.env.user.has_groups(<spec>)`, and the bundled
tree carries 112 negated `groups="!…"` attributes. A single transposed letter in
one of them renders the node for every visitor, and the page still loads.

The obvious fix — raise on a reference that does not resolve — is wrong, and a
dependency analysis says why. Over all four repositories, 995 literal group
references appear inside `has_group`/`has_groups`; **ten name a module the
calling module does not depend on**:

    portal, portal_rating, web_unsplash  ->  website.group_website_restricted_editor
    account                              ->  website.group_website_designer
    utm                                  ->  sales_team.group_sale_salesman
    marin                                ->  purchase_security.group_purchase_own_orders

That is the optional-dependency idiom: ask whether the user is a website editor,
and when `website` is not installed, get `False`. Leniency is load-bearing, and
in that case the fall-through is not merely tolerable but *correct* — with
`website` absent nobody is a restricted editor, so `groups="!website.…"` should
show the node to everyone.

So the two cases are indistinguishable at runtime and have opposite right
answers. What separates them is not available to the process: whether the author
meant a module that is simply not installed here, or misspelled one that is.
It is available to a scan of the tree.

## Decision

`test_lint`'s `TestGroupReferences` collects every `res.groups` record the
checkout defines, and every group reference in Python (`has_group`,
`has_groups`, `_has_group` on a string literal) and in XML (`groups`,
`t-groups`). A reference is a finding when its module **is** a module of this
checkout and the group is not one that module defines. The floor is zero, held
by `assert_ratchet` with no baseline file.

An unqualified reference is read as its own module's, matching
`test_menu_parents` and the loader. A reference into a module the checkout does
not contain is never a finding — that is the idiom above, and the gate has
nothing to say about it.

At runtime, `res.users._group_id` stays lenient and logs once, at WARNING, when
a reference fails to resolve **and** its module is in
`registry._init_modules`. That is the same judgement as the gate, made from the
one fact the process does have, and it covers a module the gate cannot see:
`enterprise`, `agromarin`, and anything installed from outside the tree.

## Alternatives considered

- **Raise on an unresolvable reference.** Rejected: it breaks the ten call sites
  above, each of which is correct as written. The fork would have to give every
  optional dependency a hard `depends`, which is the wrong direction.
- **Make an unresolvable negation deny instead of grant.** Rejected: it inverts
  the correct answer for the uninstalled-module case, which is the common one.
  It also splits `has_groups` into two policies for one spec.
- **Warn at runtime and stop there.** Rejected as the whole answer. The warning
  only fires on a path that executes, and a `groups="!…"` typo in a template
  nobody has rendered this boot is exactly the case that stays silent. It is
  kept as the half that reaches modules outside the tree.
- **Check it in `ir.ui.view` validation at install time.** Rejected: it moves the
  failure to whoever installs the module rather than whoever writes it, and it
  cannot see a Python call site at all.
- **Ratchet the count instead of holding zero.** Rejected on measurement: the
  tree has 3520 references and zero findings, so there is no debt to ratchet, and
  a baseline file would list a floor of nothing.

## Consequences

- A typo in a group reference fails CI in the PR that writes it, in both
  polarities and in both languages.
- The optional-dependency idiom keeps working, unchanged and ungated.
- The gate is blind to `enterprise` and `agromarin`, which it does not check out.
  The runtime warning is what covers them; extending the gate follows the
  cross-repo pattern already used by `js_face_boundary` and
  `named_export_coherence` (§9.4 of the workspace map), not a second baseline.
- A group defined anywhere other than a `<record model="res.groups">` element —
  created in Python, or loaded from a CSV — is invisible to the collector and
  would read as a finding. None exists today; the vacuity tests fail loudly if
  the collected set stops covering `base`'s own four.

## Enforcement

`odoo/addons/test_lint/tests/test_group_refs.py`, run by `test_lint.yml` over the
whole module on every PR with no `paths:` filter. Floor zero via
`assert_ratchet("lint_group_reference", …)`: the gate has no baseline file under
tooling/ratchet/baselines, and that absence **is** the zero — named in prose
because the file deliberately does not exist.

Four tests guard the judgement itself rather than the tree: that the scan reaches
both Python and XML, that it found the groups it judges against, that a planted
typo is caught in both polarities, and that a reference into an absent module is
not flagged.
