# Double-patch allowlist staleness

Answers the one question `addons/mail/static/tests/core/patch_order_audit.test.js`
cannot ask itself: **is an allowlist entry still double-patched anywhere?**

```bash
tooling/patchorder/patchorder.py            # sweep the whole workspace
tooling/patchorder/patchorder.py --check    # exit 1 if anything is stale
tooling/patchorder/patchorder.py addons ../enterprise   # explicit roots
```

```
roots scanned      : 5
allowlist entries  : 106
pairs indexed      : 2549
unresolved sites   : 70  (patch(X, factory()) and similar — not object literals)

no stale entries — every allowlist pair still has >= 2 patch sites
```

## Why the audit cannot ask it

`KNOWN_DOUBLE_PATCHES` records the `(target, method)` pairs two or more addons
patch, where bundle order — not source order — decides the `super` chain. The
audit asserts one direction, that every *live* double-patch is allowlisted, and
that is sound in any bundle: a scoped page can only produce a subset of the live
pairs, so it cannot false-fail.

The mirror direction is not a property of a bundle at all.
`getDoublePatchedPairs()` reads the runtime patch registry, and CI runs that
suite with `&module_scope=mail`. Every pair whose second patcher lives in
`im_livechat`, `whatsapp`, `voip`, `knowledge`, `sms`, `snailmail`, … is absent
for that reason alone, indistinguishable from one whose patch was really
removed.

An advisory used to print both kinds together and ask the reader to separate
them. Measured on `@mail/core` at `17179890aea`: of the 82 entries it named, 81
were still double-patched elsewhere in the tree and exactly one —
`MailGuest.prototype :: setup` — was genuinely stale. A 99% false-positive rate
on a question whose real answer is one line. The advisory is gone; this is what
replaced it.

## Three things this refuses to do

**It does not give a verdict from a partial scope.** Run over `addons` alone it
reports `Thread.prototype :: open` as having one site — its second patcher is
enterprise's `knowledge`, never scanned. Any root the workspace has and the run
did not is named as `SCOPE INCOMPLETE`, findings are relabelled *candidates*,
the "prune these" instruction is withheld, and `--check` exits **2** rather than
passing or failing. One root short is the same false confidence as one bundle
short, which is the fault this tool was written to remove.


**It does not restate the allowlist.** The entries are parsed out of the test
file at run time. A copy here would be the very thing the tool exists to catch
drifting, and it refuses outright if the Set literal has moved or parses empty
rather than sweeping a fraction of it while reporting on all of it.

**It does not report stale entries from a scan that found nothing.** With no
`patch()` call anywhere in the given roots, every entry looks stale and
`--check` would condemn the whole allowlist. That is the "compared nothing,
reported clean" fault inverted, and it exits non-zero naming the roots instead.

## The trap that produced 17 false stales

The first scan matched `patch(TARGET, { … })` at the call site and reported 17
entries as patched by nothing. All 17 were wrong. Most of `addons/mail` writes:

```js
const messagePatch = { canForward(thread) { … } };
patch(Message.prototype, messagePatch);
```

which a call-site regex never sees — the same blind spot `CLAUDE.md` records for
the SQL `IN` gate, where a query assembled into a variable is invisible to the
check. `build_index` resolves top-level `const NAME = { … }` in the same file and
follows the identifier. `test_indexes_the_named_const_spelling` pins it.

**Validate recall against a live run before trusting a zero.** The scoped mail
bundle reports 25 live pairs; the corrected index finds 25 of 25, each with two
or more sites. That is what licenses believing its zeroes. `patch(X, factory())`
still cannot be read statically — those are *counted* as unresolved and printed,
never silently dropped, because a dropped site is exactly a false stale.

## Why this gates nothing

Same choice `tooling/testbaseline/` made, for a stronger reason: **it could not
be sound in this repo's own CI.** `architecture.yml` checks `odoo` out alone, and
alone the question has no answer — `MailGuest.prototype :: setup` (one site, in
`mail`) is indistinguishable from `Thread.prototype :: open` (one site in `mail`,
one in enterprise's `knowledge`). It is the shape `js_private_access.py` hits and
that `CLAUDE.md` §9.2.1 records as open.

A blocking version is possible and the pattern already exists: pin each entry
**per consumer scope**, the way `js_public_surface.py` does — a repo-alone run
judges the entries whose sites are all in `odoo`, the sibling repos' cross-repo
lane judges the rest, and `--update` refuses anything less than the full
workspace. That was not built here because the pin is a second copy of a
cross-repo measurement that must be regenerated whenever any addon adds or
removes a patch, and the fault it would catch is mild: a stale entry permits a
pair that never occurs. It widens what the audit accepts without review; it
breaks nothing. Sweep before touching the allowlist, and when the maintenance
case changes, the upgrade path is the paragraph above.
