"""The method vocabulary over every function in the core package.

`naming_vocabulary.py` implements §2.4.13's scope as a class-membership test, so
it reports on methods declared on `models.Model` and its siblings and on nothing
else. That is the right population for the addon floor it feeds -- an addon is
model classes and little else -- and it is the wrong one for `odoo/`, which is
overwhelmingly module-level functions and plain classes. Core was swept by hand
for exactly that reason when the vocabulary was extended to every function in
it, and swept again three days later -- the assemble verbs losing their
carve-out -- over a population the first sweep's measurement could not see.

This gate is the checker the first sweep sketched and the second argued had
become owed. It differs from its sibling in three ways, each of which is why a
`--roots` flag on the sibling would not have done:

* **It reads every function**, not the methods of model classes.
* **It flags the assemble verbs unconditionally.** They are payload-only in
  `ABOLISHED` because the sibling reads a name and not a receiver, and widening
  that shared table would move the addon floor by names nobody has looked at.
  Here the population is small enough to have been read.
* **It reads the abolished table as families rather than as a word list.**
  §2.4.20's argument is that a row's printed entry can drain to zero while the
  operation goes on being performed under a word nobody listed, and that the
  drained entry then reads as a finished family. `SYNONYMS` is that reading made
  blocking, and the comment above it argues the exclusions as well as the
  entries.
* **It flags a bare assemble verb.** `classify` partitions on the first token
  and returns `None` when there is no remainder, so `make()` and `_build()` are
  invisible to every rule in §2.4. Seven of the second sweep's forty-five were
  spelled that way.

Bare verbs from the rest of the abolished table are **not** flagged, and the
line is drawn there on purpose. There is no reading under which a bare `make()`
is right -- the Payload row has no exception for it. A bare `delete` often is:
`orm/runtime/backend.py` declares one on a Protocol, `libs/password.py` has a
`verify` beside a `hash` and an `identify`, and in both the bare name IS the
contract being implemented. Those are §2.4.6's `[review]` tier and stay there.
`--candidates` prints them, so the population is visible without being blocking.

What survives the vocabulary in core is a list and not a package boundary, so the
survivors are an allowlist naming each one and why, never a floor. A floor would
let the next one in silently; an entry has to be argued.

The floor was six when this was written, all of them in `odoo/tests`: the second
sweep took every other part of core to zero and left the framework tree to a
sweep already running inside it, because colliding with a live rename is worse
than a floor. That sweep landed and the six are gone, so the gate is a hard zero
held by `test_naming_core_vocabulary` and by no baseline file -- which is why
every assertion in that module is aimed at a scan that has stopped looking
rather than at a count.

**The name says core and the gate no longer only reads core.** Four of its rules
read a BODY rather than a spelling -- whether a `collect_` owns what it returns,
whether a `check_` raises, whether a `_get_` returns anything at all, whether it
creates what it claims only to describe -- and none of those is a question about
a package. They were core-only because core is where they were written. The
sibling gate cannot ask them at any scope: it matches a literal abolished token
in a leading position, so it reports zero over every one of them however the
tree is pointed.

`--addon` names a scope out of `GOVERNED_ADDONS`, and `addons/stock` is the
first bundled tree to earn one: fourteen definitions there, all invisible to
the sibling's floor of zero. Two things make that a scope rather than a flag.
The allowlist is keyed by NAME, so it is split per scope -- a core entry
exempting an addon method would be §2.4.20's `_check_path` collision with the
argument attached to the wrong definition. And `CORE_ONLY_KINDS` holds back
§2.4.4's two infix rules, which need a noun test nothing mechanical has;
`stock`'s four infix hits are all `assign`, that module's own operation.

An addon is added to `GOVERNED_ADDONS` after it has been swept and not before,
and it is a hard zero from that moment, on the same terms as core: no baseline
file, and a survivor argued into the allowlist rather than banked.
"""

from __future__ import annotations

import argparse
import ast
import itertools
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ast_cache
import _sources
import naming_vocabulary as nv
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve())
CORE = ROOT / "odoo"

# The scopes this gate may be pointed at, `--addon` naming one of them. `core`
# is the population the module docstring argues for; the rest are bundled
# addons, onboarded one at a time.
#
# The four rules that read a BODY were written for core and are not a core
# reading: whether a `collect_` owns what it returns, whether a `check_` raises,
# whether a `_get_` returns anything and whether it creates what it claims to
# describe are questions about a function, not about a package. They were
# core-only because that is where they were written, and `addons/stock` is the
# first scope to be swept against them -- fourteen definitions the sibling gate
# reports as zero, because the sibling matches a literal token in a leading
# position and none of the fourteen wears one.
#
# An addon earns a row here after that sweep and not before, which is the shape
# `GOVERNED_ADDONS` has in every other `--addon` gate: a scope nobody has read
# measures cleanly and is pinned by nothing.
#
# `web` is the second, and it is here for a reason `stock` did not have: when
# it landed the sibling gate read model classes, plus module-level and nested
# definitions under an addon's `models/` and `wizard/` only. `addons/web` is
# twenty-four CONTROLLER files, and no list named `controllers`, so more than
# half of this addon was in no gate's population at any scope. Its floor of
# zero was not a swept tree, it was an unread one -- §2.4.13's "the wrong gate
# reading 0" with the population missing rather than merely thin. The sibling
# now governs every file under a manifest, so that hole is closed on the
# spelling rules; what still needs this row is the body-reading half.
#
# `sale` is the third, and its seven findings are the cleanest statement of what
# the sibling gate cannot ask. `naming_vocabulary.py --roots addons/sale --count`
# reads ZERO, and has read zero throughout: not one of the seven wears an
# abolished token in a leading position, which is the only thing that gate
# matches. Five were the body-reading rules -- a `_get_` that creates the product
# it promises only to describe, a `_prepare_` that returns nothing, a `_check_`
# that returns instead of raising, a total `_resolve_`, a `determine` synonym --
# and two were §2.4.4's held-back kinds. A floor of zero over a population no
# rule in that gate can reach is not a swept tree either; it is `web`'s finding
# arriving through the rules rather than through the file list.
# `point_of_sale` is the fourth, and it is `sale`'s finding a second time with
# one addition of its own. `naming_vocabulary.py --roots addons/point_of_sale
# --count` reads ZERO, and the body-reading rules found five: a `_validate_`
# that returns two lists instead of raising, a `_check_modules_to_install` that
# installs the modules and reports whether it did, and three producers that
# create records under a `_get_`/`_prepare_` promising only to describe them.
# The addition is that its ten held-back hits are the strongest case yet for
# holding them back -- `opening control`, `closing control` and `cash control`
# are the POS domain's own nouns for the session's open and close steps, and
# `scan_via_proxy` is a barcode scanner. Ten candidates, zero defects, which is
# what §2.4.4 means by a candidate list.
#
# `purchase` is the fifth and is the cheapest row here, because the sweep that
# earned it was done for another reason: nine renames across `purchase_order.py`,
# `purchase_order_line.py` and `account_move.py`, plus the `_merge_*` family
# arriving from `base_order` with `sale`'s. It reads 0 with the allowlist OFF and
# 0 against the deferred kinds as well, so it needs no allowlist entry at all.
#
# It was nearly kept OUT over a bug, and that is the part worth recording. The
# `model-noun` rule read `_inherit` as the model's own words, so `mixin.order.merge`
# made `merge` a model noun on every order model mixing it in -- 21 findings
# across `base_order`, `sale` and `purchase`, every one a member of one deliberate
# namespace the mixin declares. From inside any single scope that reads as a
# convention question rather than a defect: 19 under one prefix in `base_order`,
# 2 in `sale`, 2 in `purchase`. Three sessions comparing the same finding caught
# it; none of them measuring harder would have.
#
# **A SCOPE IS NOT A HARD ZERO UNTIL THE RENAMES THAT MADE IT ZERO ARE ON THE
# BRANCH, AND THE ROW IS NOT LANDABLE UNTIL THEN EITHER.** This tuple is the
# assertion, so it travels in the same commit as its evidence. It is not the
# familiar "commit before you bank a floor" -- this gate has no floor, and that
# is exactly what makes the failure silent: a row that is true of your working
# tree and false of the branch prints nothing, where a stale doc figure at least
# gives `doc_restated_counts.py --check` something to diff. Measured in one day:
# `web` was true of the checkout and false of the branch until its renames
# landed, and `point_of_sale` read 0 in the checkout and SIX in a detached
# worktree at the tip with only these gate files copied in. Both were found by
# somebody re-measuring in that worktree, and by nothing else -- every session
# had correctly read every scope as 0 in the shared checkout, where everyone's
# uncommitted renames are present and the gate will never run.
#
# `purchase_stock` is the seventh and it tests the clause above rather than
# following it: its renames are already landed (`9773cf7de066`), so the row does
# NOT travel in their commit. The session that made them flagged the mismatch
# themselves rather than adding the row quietly, which is the right instinct and
# is why this note exists. The clause is satisfied in substance and that is what
# it is for -- the rule protects against a row asserting a zero that is true of
# somebody's working tree and false of the branch, and here the zero is on the
# branch: measured in a detached worktree at `9773cf7de066`, allowlist off, 0.
# Read the clause as "the row may not precede its renames", not as "the row must
# share their commit".
#
# THE MEASUREMENT THAT SETTLED IT WAS WRONG THE FIRST TIME, in the direction that
# would have blocked this row. An ad-hoc probe calling `classify_definition`
# directly reported `purchase` at 1 on the branch -- `_collect_qty_changes`,
# [accumulate] -- while the gate read 0 from the same tree. The gate was right:
# `measure()` skips a node when `nv._overrides_same_name` holds, and that method
# calls `super()._collect_qty_changes(...)`. A probe that reaches past the entry
# point asks a NEIGHBOURING question and answers it correctly, which is worse
# than failing. Measure a scope with `measure()`.
#
# `mrp` is the eighth, on `purchase_stock`'s terms: its sweep is already landed
# (`1ad4b4cbb623`), and `measure()` in a detached worktree at that commit reads
# 0 with no allowlist entry. The two it reported before the sweep were the
# body-reading rules exactly -- `_get_mo_count`, a five-field `compute=` hook
# returning nothing, and `_check_planned_start`, which set a key on a caller's
# dict and returned -- and both were invisible to the sibling gate at every
# scope. The five `--candidates` rows are all `assign`, stock's own operation
# (`_action_assign` and kin), which is the reading `stock`'s row already argues.
GOVERNED_ADDONS = (
    "core",
    "stock",
    "web",
    "sale",
    "purchase",
    "point_of_sale",
    "purchase_stock",
    "mrp",
)

# `addons/mail` was swept against every rule that travels and is NOT here yet,
# and one kind is the whole reason. Everything else the rules reach was renamed
# in the sweep -- the `detect` predicates the entry below was written for, a
# `locate`/`find` pair spelling one operation twice, and both `shaping`
# findings -- and `Store.resolve_data_request` is argued into the scoped
# allowlist against the day this row lands. What is left is `model-noun`, and
# a count is deliberately not printed here: the rule was under active edit the
# afternoon this was written and the reading moved three times in an hour, so
# take it from `--addon mail` rather than from this paragraph.
#
# The residue is not a defect list, and two groups say why.
#
# MOST of it is the public `channel_*` RPC surface of `discuss.channel`
# (`channel_join`, `channel_pin`, `channel_fetched`, `channel_rename`, ...),
# reached by name from the discuss client. Each is a §2.4.14 binding before it
# is a name, so it is not a rename anyone takes on a rule's say-so.
#
# The rest is the shape this rule's own comment already holds back from CORE
# and does not hold back from an addon: a WIZARD whose model name IS the
# operation. `mail.template.reset.reset_template` and
# `mail.followers.edit.edit_followers` repeat their model's word because the
# model was named for the verb, which is the argument that leaves core's
# thirteen unswept -- and it does not become a different argument in `addons/`.
#
# So mail joins this tuple when a scope can hold back the kinds ITS population
# has not been read against, and not before: banking it now would either take
# renames nobody has argued or exempt them by name, which is the word list the
# allowlist exists not to become. Swept 2026-09-09.

# §2.4.4 owns the infix population and calls it a CANDIDATE list rather than a
# defect list -- nothing mechanical can tell a verb parked behind a noun from a
# noun spelled like a verb, and the census counts 137 of them under `addons/`.
# Core can gate the rule because core was swept by hand, name by name. An addon
# scope cannot, and `stock` is where the difference is legible: all four of its
# infix hits are `assign`, which is that module's own operation -- `_action_assign`,
# and the `assigned` state on `stock.move` -- rather than a hidden verb. So the
# body-reading rules travel to an addon scope and the two spelling rules that
# would need a noun test stay behind.
# `trailing` joins them, and its own core population is the argument. Of the five
# it found there, ONE was a defect and four were nouns sitting in the last
# position: the seed a colour is hashed from, the comodel-id-lookup SHAPE a
# domain optimiser rewrites, the `<delete>` element `_tag_<xml tag>` dispatches
# on, and `batch_cache_fill`, which is a real defect held for a reason of its own
# (see the allowlist). One in five is a candidate population by any reading, and
# core could be gated on it only because those five were read one at a time.
CORE_ONLY_KINDS = frozenset({"infix", "infix-synonym", "trailing"})

# `resolve-total` was held back here while core's nineteen went unread, with a
# note saying to move it out once somebody had read them. They have been read,
# and they were THREE populations rather than the two that note predicted.
#
# FIVE were partial producers already, and no body test could see it.
# `_resolve_attempt(job) -> CompletionStatus | None` has a single `return
# status`; whether that is None is a runtime question. The ANNOTATION answers it,
# and `annotates_optional` now reads it -- the same evidence
# `is_declaration_only` takes from `-> str | None` on an extension point, and the
# stronger of the two, because an annotation is the contract where a body is only
# today's implementation of it. That removed five findings with a rule instead of
# five allowlist entries.
#
# SIX were ordinary producers wearing a reserved word and are renamed:
# `_get_scope`, `_get_cache_and_key`, `_get_enqueue_state`, `_get_error_frame`,
# `_get_sequence_date`, `_get_param_spec_fields`. None of them looks anything up;
# each computes a value from its arguments.
#
# EIGHT are the second SENSE of the word, and this is what the original note was
# reaching for without quite naming. §2.4.3 reserves `_resolve_` for §2.4.11's
# partial producer -- the object, or nothing meaning not applicable. The tree also
# uses `resolve` for NAME RESOLUTION: turn a symbolic reference into the thing it
# names, total, raising when it names nothing. That sense is a term of art from a
# layer below on exactly the terms `reap` and `probe` are -- DNS
# (`_resolve_webhook_candidates`), Python's MRO (`resolve_mro`), XML-DSig's
# `<Reference URI>` (`resolve_reference`), the asset subsystem's own `Resolution`
# (`_resolve_path_def`) -- and it reaches our own code too, where a state string
# becomes a method (`_resolve_runner`) or a dotted @depends path becomes a Field
# tuple (`resolve_depends`).
#
# NO PREDICATE SEPARATES THE TWO SENSES, which is why the eight are argued into
# the allowlist one at a time rather than carved out by a rule. What the rule CAN
# do is stop reporting the five the annotation already settles. With those three
# groups discharged the population is zero, so the kind gates in core like every
# other, and this set is empty rather than deleted -- the next rule written
# against an unswept core population belongs in it.
#
# `model-noun` is the first rule written into it, and it is `CORE_ONLY_KINDS`
# with the sign reversed: that set holds a rule back from an ADDON scope because
# core was swept by hand and the addon was not, and this one holds a rule back
# from CORE because the addon was swept and core was not. §2.4.4 says a first
# token repeating the model is what hides the verb; the rule reads 0 in
# `addons/stock` after the renames that landed with it, and 3 in `odoo/`:
# `ir.actions.report.report_action`, `ir.job._job_ping` and
# `ir.module.module.module_uninstall`. Nobody has read those three, and two of
# them are public names whose callers a Python grep cannot see (§2.4.19), so
# each is a §2.4.4 public-surface weighing rather than a rename. `--candidates`
# prints them, which is the whole content of holding a rule back: one that is
# neither blocking nor printed has been dropped rather than deferred.
UNSWEPT_IN_CORE_KINDS: frozenset[str] = frozenset({"model-noun"})

# `_sources.is_test_path` calls any path with a `tests` component a test path.
# That is right for odoo/orm/tests and its siblings and wrong for exactly one
# tree: odoo/tests is the test FRAMEWORK -- TransactionCase, HttpCase, the CDP
# driver, the suite runner -- production code every addon test runs on, excluded
# by the name of its directory rather than by anything about it. The same
# reasoning `test_excluded_trees_stay_empty.py` records, applied to a gate that
# can act on it: TestCursor lives in a file called test_cursor.py and is a
# cursor, not a suite.
FRAMEWORK = CORE / "tests"

ALLOWLIST = Path(__file__).with_name("naming_core_allowlist.json")

# §2.4.3's Payload row prints four verbs; the operation has more spellings than
# the row has entries. `assemble`, `craft` and `forge` were read here first and
# now sit in the shared table beside the four, on the same terms -- flagged
# whatever the tail, `_prepare_` under a payload suffix and `_get_` otherwise.
# The bare form is still this gate's alone (`classify_name` below).
ASSEMBLE = nv.ASSEMBLE_VERBS

# §2.4.20: read the table as families, not as a word list. `naming_vocabulary.py`
# matches the literal token by construction, so a row's entry can drain to zero
# while the operation goes on being performed under a synonym -- and the drained
# entry then reads as a finished family. Each key below is a word the table does
# not print whose body satisfies one of its rows; the value is that row's
# canonical and the reason, which is what the renamer needs and the count is not.
#
# This table held ten words as a core-only reading until the addon floors had
# been read against them -- the argument was that the shared table would move
# by names nobody had looked at. They have been looked at, one repository at a
# time, and `populate`, `prune`, `sweep`, `seed`, `scan`, `detect`, `determine`,
# `tweak` and both spellings of `synchronize` are `nv.ABOLISHED` rows now,
# reported by `classify_name` as `leading` like any other. What stays here is
# the one the shared table refuses, and what is NOT in either is as argued as
# what is:
#
# * `refresh` is §2.4.17's cache verb in core and only there. In `addons/` the
#   same word is an OAuth *refresh token* (`google_account`, `microsoft_account`,
#   both calendars) and `REFRESH MATERIALIZED VIEW` (`mixin_report_sql`), two
#   reserved senses a name cannot separate from the cache one, so the shared
#   table would print a wrong canonical for half its population.
# * `collect` and `emit` need a discriminator this table does not have. Most of
#   core's `collect_*` accumulate into a caller's container and return nothing,
#   which is not the Read row -- `accumulate` below reads the body for it;
#   `emit` is `logging.Handler.emit`, and an override whose name is the
#   contract is a rename that silently unhooks it.
# * `reap` and `probe` are terms of art from a layer below, on §2.4.3's
#   "reserved, not abolished" terms: `reap` is the POSIX wait-for-a-child, and
#   `probe` is a named subsystem in `odoo/db/`.
# * `complete` is two operations under one word, and the measurement is what
#   says so rather than the intuition. It reads as the Mutation row's `_fill_`
#   -- `pos.order._complete_values_from_session` and `portal`'s
#   `_complete_address_values` both setdefault into a caller's dict, and the
#   first is renamed `_update_values_from_session` by hand for exactly that.
#   But `gamification.quest.complete_step` and `_complete_quest` mean MARK AS
#   DONE, which is a domain operation and not a row of the table at all, and
#   `odoo/tests/case.py`'s `_complete_traceback` is a third reading. Two in
#   core and six across `addons/` would be flagged by a `complete` row, and the
#   canonical it printed would be wrong for at least three of them -- a synonym
#   entry whose canonical is a coin flip is a word list again, which is what the
#   paragraph above this list exists to refuse.
#
# `categorize` and `categorise` are here on the opposite terms from `complete`:
# ONE canonical, and a population that was read to zero before the entry landed.
# `db/metrics.py` spelled the operation `categorize` beside `ddl.classify_statement`
# in the same package -- two verbs, one operation, §2.4.3's own duplicate report --
# and was renamed; the entry keeps the second spelling from coming back.
SYNONYMS: dict[str, tuple[str, str]] = {
    "refresh": (
        "_reset_ / _invalidate_ / _rebuild_",
        "names neither the drop nor the rebuild, which is what §2.4.17 exists to say",
    ),
    "categorize": (
        "_classify_",
        "one operation, and the tree already spells it classify",
    ),
    "categorise": (
        "_classify_",
        "one operation, and the tree already spells it classify",
    ),
    # `forget` was §2.4.17's fourth cache verb in core -- `forget_unaccent_table`,
    # `_forget_ref_cache`, `Registry.forget`, the reachability probe's `forget` --
    # and every one named a drop or an invalidation the section already has a
    # word for. Read to zero across core before the entry landed (odoo-95's
    # `clear_database_state`, odoo-07's probe half), so it is a contract.
    "forget": (
        "_clear_ / _invalidate_",
        "§2.4.17 names the drop and the invalidation; forget says neither",
    ),
}

# Vendored code is not ours to rename. `nv.SKIP_DIRS` carries "vendored"; this
# tree spells it with the underscore.
SKIP_DIRS = nv.SKIP_DIRS | {"_vendor"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    kind: str
    why: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.name}  [{self.kind}] {self.why}"


def addon_src(addon: str) -> Path:
    return CORE if addon == "core" else ROOT / "addons" / addon


def load_allowlist(addon: str = "core") -> dict[str, str]:
    """The survivors of one scope, never of another.

    A flat name list shared across scopes would exempt an addon method because
    a core function of the same name was argued years earlier, which is the
    §2.4.20 trap one directory up: a name is not unique, and an allowlist keyed
    on the name alone is a claim that it is.
    """
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    if addon == "core":
        return data["names"]
    return data["scopes"].get(addon, {})


def is_suite(path: Path) -> bool:
    if path.is_relative_to(FRAMEWORK):
        return False
    return "tests" in path.parts or path.name.startswith("test_")


def scan_files(root: Path | None = None) -> list[Path]:
    scan = root or CORE
    return [
        path
        for path in sorted(scan.rglob("*.py"))
        if not (set(path.parts) & SKIP_DIRS) and not is_suite(path)
    ]


def definitions(
    tree: ast.Module,
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef | None]]:
    """Every function in a module, with the model class it is declared on.

    `ast.walk` was enough while every rule read a name or a body. `model-noun`
    reads the RECEIVER's name, which lives on the enclosing class, so the walk
    has to carry it -- and it has to lose it again inside a function, because a
    closure nested in a method is not declared on the model. `_get_tasks`'s
    inner helper is a local, and asking whether its first token repeats the
    model would attribute the class's name to a function the class does not
    declare.

    A non-model class yields `None` for the same reason `model_class_nouns`
    returns an empty set for one: `_name` / `_inherit` is what makes a leading
    noun the model's own, and a plain class has neither.
    """

    def walk(node: ast.AST, cls: ast.ClassDef | None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, child if nv.is_model_class(child) else None)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield child, cls
                yield from walk(child, None)
            else:
                yield from walk(child, cls)

    yield from walk(tree, None)


# §2.4.3's Read row canonical is `_get_`, and its discriminator is the RETURN --
# "the return value feeds anything else". A `collect_*` is that row exactly when
# the value it returns is the value it produced. Where it fills a container it
# did not create -- a parameter, an attribute of its receiver, a closure variable
# of the function around it -- the product is that container and the return is
# bookkeeping: a loop variable, a recursion handle, a token-stream state. That is
# the Addition row acting on somebody else's object, and no rename this gate can
# name would improve it.
#
# The distinction is why `collect` was held out of `SYNONYMS` when the synonym
# table landed. It is not cosmetic: of core's twenty-six `collect_*`, eleven
# return a value and only seven of those own it. A rule that stopped at "returns
# something" would have demanded `_get_` from all eleven, and four of the answers
# would have been lies.
# `accumulate` is the same word as this rule's own kind name and was not in the
# set, so the rule could not see the family it is named for. Measured before
# adding it: SEVEN `accumulate_*` definitions in all of `addons/`, ONE flagged,
# and none at all in core or `stock` -- so no floor moves anywhere. The six it
# leaves alone are the argument for the body test rather than an exemption from
# it: `pos.session._accumulate_amounts`, `_accumulate_order_payments` and
# `_accumulate_stock_amounts` and `account.move`'s two all fill a bucket dict
# handed in by the caller, which is the Addition row acting on somebody else's
# object. The one it takes owns what it returns.
ACCUMULATE_VERBS = frozenset({"collect", "gather", "accumulate"})

_MUTATING_METHODS = frozenset(
    {
        "append",
        "appendleft",
        "add",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _names_bound_in(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every name the function itself creates, parameters included.

    A container is the function's own product when the function made it. The
    parameters count as bound but NOT as created -- `_owns_its_return` subtracts
    them, because a container handed in belongs to the caller.
    """
    bound: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            bound.add(child.id)
    return bound


def _mutated_roots(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    roots: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in _MUTATING_METHODS
            and (root := _root_name(child.func.value)) is not None
        ):
            roots.add(root)
        targets: list[ast.expr] = []
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
        elif isinstance(child, ast.AugAssign | ast.AnnAssign):
            targets = [child.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute | ast.Subscript)
                and (root := _root_name(target)) is not None
            ):
                roots.add(root)
    return roots


def returns_a_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            if not (
                isinstance(child.value, ast.Constant) and child.value.value is None
            ):
                return True
        if isinstance(child, ast.Yield | ast.YieldFrom):
            return True
    return False


def raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(child, ast.Raise) for child in ast.walk(node))


def owns_its_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The value it returns is a value it made, not one it was handed."""
    if not returns_a_value(node):
        return False
    args = node.args
    parameters = {
        a.arg
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
        if a is not None
    }
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            parameters.add(extra.arg)
    created = _names_bound_in(node) - parameters
    return not (_mutated_roots(node) - created)


# §2.4.21: a prefix is a claim, and where the claim is about the RETURN the test
# is the body. `_get_` is §2.4.3's Read row -- "the return value feeds anything
# else" -- and `_prepare_` is the Payload row, whose entire content is a promise
# about what comes back. Neither survives a body that returns nothing.
RETURN_CLAIM_VERBS = frozenset({"get", "prepare"})

# §2.4.3 reserves `_resolve_` for a PARTIAL producer: "returns the object, or
# `None` meaning *not applicable*". The reservation is the whole content of the
# verb -- a producer that always has an answer is the Read row and `_get_` says
# so, and one that never returns at all is not a producer. So a `_resolve_` with
# no not-applicable path is using a reserved word to mean the ordinary thing,
# which is §2.4.3's "collapsing it destroys information" read backwards.
#
# `None` is not the only spelling of not-applicable and treating it as the only
# one is how this rule over-reports. In an ORM an EMPTY RECORDSET is the idiom,
# and `stock.location._resolve_inventory_location` returns `Location.browse()`
# for exactly that: scope not set, nothing to resolve. A rule that read only
# `return None` would have demanded a rename of the one member of stock's six
# that is using the reservation correctly. `_returns_empty_recordset` is why the
# population is four rather than five.
# §2.4.3's Predicate row is `_is_` / `_has_` / `_can_`, and its discriminator is
# that "the returned `bool` is the answer to a question about the subject". The
# same row warns, in its own words, that **the return type is not the test** --
# so a rule keyed on "returns a bool" is the mistake the row names, and this one
# is keyed on something narrower: a `_get_` whose every return is a boolean AND
# at least one of which the function WORKED OUT.
#
# The difference is not pedantry, it is the whole population. A hook's default
# implementation returns the literal `False` and its overrides return a value:
# `ir.ui.view.get_formview_id` returns a view id or False, and
# `_get_placeholder_filename` a filename or False. Both are bool-returning by a
# naive reading and neither is a predicate -- the base is a stub, and the
# contract lives in the overrides the gate cannot see from here. Requiring one
# computed boolean -- a comparison, a `not`, a `bool()`/`any()`/`all()` -- takes
# core from 2 to 0, stock from 2 to 0 and the bundled tree from 18 to 4, and
# every one of the 18 that dropped out was a stub of that shape.
_COMPUTED_BOOL_CALLS = frozenset({"bool", "any", "all"})

# A call to a method whose own name is a predicate is a computed boolean, on the
# authority of §2.4.3's Predicate row: "the returned `bool` is the answer to a
# question about the subject". That row is a CONTRACT, so the gate is entitled to
# read a `self._is_x()` the way it reads a `bool(...)`, and the vocabulary gets
# stronger the more of the tree obeys it.
#
# It is not decoration. `sale`'s `_show_discount` returns `False` on an empty
# recordset and `self._is_discount_feature_enabled() and self.compute_price ==
# "percentage"` otherwise -- every return boolean, one of them computed. Without
# this the `and` fails `all(_is_boolean(...))` on its first operand and the whole
# definition reads as a non-predicate, which is how the clearest member of the
# `_show_` family escaped the rule written for it.
#
# Measured before landing, because this widens two rules at once (`bool-under-get`
# takes it too): core 0 -> 0, stock 0 -> 0. The only definition it adds anywhere
# is the one it was written for.
_PREDICATE_CALL_PREFIXES = ("is_", "has_", "can_", "should_")


def _is_predicate_call(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name.lstrip("_").startswith(_PREDICATE_CALL_PREFIXES)


def _is_computed_bool(node: ast.expr) -> bool:
    """A boolean the function worked out, not a literal it was born with."""
    if isinstance(node, ast.Compare):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return True
    if _is_predicate_call(node):
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _COMPUTED_BOOL_CALLS
    ):
        return True
    # `a or b` yields an OPERAND, so it is only boolean when every operand is --
    # and only *computed* when at least one of them is. Reading `or` as boolean
    # by itself reported `_get_lang` and five like it, whose operands are strings.
    if isinstance(node, ast.BoolOp):
        return all(_is_boolean(v) for v in node.values) and any(
            _is_computed_bool(v) for v in node.values
        )
    if isinstance(node, ast.IfExp):
        return all(_is_boolean(v) for v in (node.body, node.orelse)) and any(
            _is_computed_bool(v) for v in (node.body, node.orelse)
        )
    return False


def _is_boolean(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return True
    return _is_computed_bool(node)


def answers_a_question(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    returns = [
        n for n in ast.walk(node) if isinstance(n, ast.Return) and n.value is not None
    ]
    if not returns or not all(_is_boolean(n.value) for n in returns):
        return False
    return any(_is_computed_bool(n.value) for n in returns)


RESOLVE_VERB = "resolve"

# §2.4.20 calls `_show_` a fourth predicate prefix and then declines to abolish
# it, for a reason that is about the SHARED TABLE and not about the verb: "an
# entry prints one canonical target and this family has three". `ABOLISHED` maps
# a verb to exactly one canonical, so `_show_` cannot be expressed there at all.
# This gate's finding carries a free-form `why`, so it can print all three and
# say the modality moves to the tail -- which is the whole of §2.4.20's argument,
# and the structural reason the rule belongs on this side rather than that one.
#
# It is a BODY rule for the same reason `bool-under-get` is: the row's own words
# are "the return type is not the test". A `show_*` that returns a recordset, an
# action or a truthy operand is not answering a question, and `sale`'s nested
# `show_line` -- which returns `line.display_type and down_payment_lines` -- is
# exactly that. It stays unflagged, correctly, and the rule reaches only the
# member of the family that really is a predicate.
SHOW_VERB = "show"


def annotates_optional(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The return ANNOTATION admits None -- `X | None`, `Optional[X]`, `None`.

    The partial-producer rule reads the body, and a body cannot always show what
    the declaration already says: `_resolve_attempt(job) -> CompletionStatus |
    None` has one `return status`, and whether `status` is None is a runtime
    question no AST answers. The annotation answers it, and it is the stronger
    evidence of the two -- it is the contract, where a body is only today's
    implementation of it.

    This is the same reading `is_declaration_only` takes of an extension point
    annotated `-> str | None` whose body is a bare `return`, and it is applied
    here for the same reason: where the declaration states the partiality, the
    reserved word is earned.
    """
    return _admits_none(node.returns)


def _admits_none(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant):
        return annotation.value is None
    if isinstance(annotation, ast.Name):
        return annotation.id == "None"
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _admits_none(annotation.left) or _admits_none(annotation.right)
    if isinstance(annotation, ast.Subscript):
        head = annotation.value
        name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
        if name == "Optional":
            return True
        if name == "Union":
            elts = annotation.slice
            values = elts.elts if isinstance(elts, ast.Tuple) else [elts]
            return any(_admits_none(v) for v in values)
    return False


_EMPTY_RECORDSET_CALLS = frozenset({"browse"})


def _returns_empty_recordset(node: ast.Return) -> bool:
    """`return SomeModel.browse()` -- the ORM's spelling of "not applicable"."""
    call = node.value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr in _EMPTY_RECORDSET_CALLS
        and not call.args
        and not call.keywords
    )


def _can_yield_none(expr: ast.expr | None) -> bool:
    """Whether the returned EXPRESSION can evaluate to None.

    Not just `return None`. A partial producer usually says it in one line --
    `return None if self.sort_key is None else (...)` is stock's, and reading
    only the statement misses it, because the None is a branch of a ternary and
    not the returned node. `x or None` is the same shape with a different
    operator. This was the third false positive the rule produced against a real
    tree, and all three were the same mistake: assuming one spelling of "no".
    """
    if expr is None:
        return True
    if isinstance(expr, ast.Constant) and expr.value is None:
        return True
    if isinstance(expr, ast.IfExp):
        return _can_yield_none(expr.body) or _can_yield_none(expr.orelse)
    if isinstance(expr, ast.BoolOp):
        return any(_can_yield_none(value) for value in expr.values)
    return False


def has_not_applicable_path(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A path on which the function declines to produce anything.

    A bare `return`, an expression that can be None, an empty recordset, or
    falling off the end of the body -- which returns `None` without saying so,
    and is the commonest spelling of the four.
    """
    for child in ast.walk(node):
        if not isinstance(child, ast.Return):
            continue
        if _can_yield_none(child.value):
            return True
        if _returns_empty_recordset(child):
            return True
    body = [
        n
        for n in node.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    return bool(body) and not isinstance(body[-1], ast.Return | ast.Raise)


# §2.4.10: an error is BUILT here and RAISED there. A method whose every return
# is a freshly constructed exception is that builder, and the section prints its
# canonical -- `_prepare_*_error`, or `_resolve_*_error` where a `None` return
# says the failure is not applicable. Both halves of the section's own argument
# are mechanical: "the larger half says no verb at all" is a body whose returns
# are all exception constructions under a noun phrase (`_budget_exhausted`,
# `not_found`), and "`_get_` is not always where it lands" (§2.4.11) is the same
# body under the Read verb (`get_config_warning`). Neither name says an exception
# comes back, and a caller who reads `raise request.not_found()` as a call that
# raises has the control flow backwards.
#
# What counts as an exception class is decided three ways, none of them a word
# list of our own: a name imported from a module called `exceptions`
# (`werkzeug.exceptions`, `odoo.exceptions`), a class in the same module that
# derives from one of those, or the spelling every exception in the stdlib
# already uses -- `*Error`, `*Exception`, `*Warning`, plus `*Denied` and `*Exit`
# for `AccessDenied` and `SystemExit`. `NotFound` and `Forbidden` are the reason
# the import test exists: werkzeug spells its HTTP exceptions as nouns.
#
# Two shapes are exempt, and both are named in §2.4.10 already. The `X_to_Y`
# converter (§2.4.5) -- `_integrity_error_to_validation_error` builds an
# exception FROM an exception, and the converter idiom is the honest name for
# that. And a nested definition filling a same-named parameter slot -- the
# `error_func` closure inside `ir.attachment._check_access` takes the name of
# the `error_func` parameter it stands in for, because "a slot and the method
# that fills it are one contract under two names"; the slot is the name to
# argue, and it is `_check_access`'s, which the allowlist already carries.
_EXCEPTION_SUFFIXES = ("Error", "Exception", "Warning", "Denied", "Exit")
_ERROR_BUILDER_VERBS = frozenset({"prepare", "resolve"})
_ERROR_BUILDER_TAILS = frozenset({"error", "exception", "warning"})


def exception_class_names(tree: ast.Module) -> frozenset[str]:
    """The names a module binds to exception classes, by import or by subclass."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.rpartition(".")[2] == "exceptions"
        ):
            names.update(alias.asname or alias.name for alias in node.names)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = _callee_name(base)
                if base_name is not None and (
                    base_name in names or base_name.endswith(_EXCEPTION_SUFFIXES)
                ):
                    names.add(node.name)
    return frozenset(names)


def _callee_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _own_returns(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    """Every `return <value>` of this body, not of a closure nested in it."""
    found: list[ast.expr] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if isinstance(child, ast.Return):
            if child.value is not None and not (
                isinstance(child.value, ast.Constant) and child.value.value is None
            ):
                found.append(child.value)
            continue
        stack.extend(ast.iter_child_nodes(child))
    return found


def _constructs_exception(expr: ast.expr, exception_names: frozenset[str]) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    name = _callee_name(expr)
    return name is not None and (
        name in exception_names or name.endswith(_EXCEPTION_SUFFIXES)
    )


def builds_an_error(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    exception_names: frozenset[str] = frozenset(),
) -> bool:
    """Every value this returns is an exception it constructed, and it raises none."""
    returns = _own_returns(node)
    return (
        bool(returns)
        and all(_constructs_exception(value, exception_names) for value in returns)
        and not raises(node)
    )


def slot_fillers(tree: ast.Module) -> frozenset[int]:
    """`id()` of every nested definition named for a slot it fills.

    §2.4.10: "a slot and the method that fills it are one contract under two
    names", so the filler takes the slot's spelling and the slot is where the
    name is argued. A slot is a parameter of the enclosing function, or a local
    the enclosing function also binds some other way -- `error_func = None` and
    `forbidden, error_func = res` beside `def error_func()` are three fillers of
    one local. Keyed by identity because a name is not unique in a tree.
    """
    found: set[int] = set()

    def slots_of(func: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
        args = func.args
        names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        for extra in (args.vararg, args.kwarg):
            if extra is not None:
                names.add(extra.arg)
        stack: list[ast.AST] = list(ast.iter_child_nodes(func))
        while stack:
            child = stack.pop()
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            stack.extend(ast.iter_child_nodes(child))
        return frozenset(names)

    def walk(node: ast.AST, slots: frozenset[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                if child.name in slots:
                    found.add(id(child))
                walk(child, slots_of(child))
            else:
                walk(child, slots)

    walk(tree, frozenset())
    return frozenset(found)


# §2.4.8's fourth family after the modal one: a predicate spelled as a
# PREPOSITIONAL PHRASE. `_in_scope`, `_on_login_cooldown`, `_within_code_ranges`
# have no part of speech a verb grep can reach, and they answer a question all
# the same. `from` is deliberately absent: `Y_from_X` is §2.4.5's converter idiom
# and a classmethod constructor, and neither is a question.
PREPOSITION_TOKENS = frozenset({"in", "within", "on", "at", "under"})


# The ORM write calls that are evidence a producer performs what it claims only
# to describe (§2.4.7 for the payload row, §2.4.11 for the read one). `write` is
# NOT among them and its absence is the rule: §2.4.3 reserves read/write for a
# method whose object is a FILE, so a call spelled `write` is as likely to be a
# filestore as a recordset -- `ir.attachment._prepare_content_vals` ends in
# `backend.write(data, checksum)` and is a correct payload builder. `create` and
# `unlink` have no such twin.
ORM_WRITE_CALLS = frozenset({"create", "unlink"})

# `Command.create([...])` builds a one2many payload; it is what a `_prepare_*`
# is FOR, and matching on the attribute name alone would flag the canonical use
# of the canonical prefix.
_COMMAND_RECEIVERS = frozenset({"Command", "fields"})


def is_declaration_only(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A definition that declares a shape and supplies no behaviour.

    Three spellings of one thing. `...` and `pass` are the Protocol member and
    the ABC stub. A body that is a single bare `return` or `return None` is the
    same declaration in the ORM's dialect: a BASE EXTENSION POINT, whose whole
    content is the name and the signature a dependent module will override.
    `ir.attachment._get_zip_detached_reader` is one, and `cloud_storage`
    supplies the reader; `res.users._get_mfa_type` and `_get_mfa_url` are two
    more, and `auth_totp`, `auth_totp_mail` and `l10n_au_hr_payroll_api` supply
    the values. Each is annotated `-> X | None`, which says the None is the
    contract rather than a producer failing to produce.

    Its name comes from the contract it declares, so the body cannot be evidence
    about it -- there is no body. That is why this belongs in the RULE and not
    in the allowlist: an allowlist entry is an argument about one name, and this
    is a class of name. The entry that used to carry `_get_stack_trace` was the
    same shape and came out when this landed, which is the direction an
    allowlist should move.

    KNOWN RESIDUAL: a `_get_*` whose body is only `return` is now permanently
    invisible to `empty-return`, and a producer somebody stubbed out and never
    finished looks identical from here to a base extension point. The body
    cannot separate them. What can is whether anything in the workspace
    overrides the name -- an extension point has overrides and an abandoned stub
    does not -- which is the check that was done by hand on the three above and
    is the discriminator to reach for if this ever hides a real one.
    """
    body = [
        n
        for n in node.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if not body:
        return True
    if len(body) != 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    if (
        isinstance(only, ast.Expr)
        and isinstance(only.value, ast.Constant)
        and only.value.value is Ellipsis
    ):
        return True
    return isinstance(only, ast.Return) and (
        only.value is None
        or (isinstance(only.value, ast.Constant) and only.value.value is None)
    )


def performs_orm_write(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in ORM_WRITE_CALLS
        ):
            continue
        receiver = child.func.value
        root = receiver
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id in _COMMAND_RECEIVERS:
            continue
        return True
    return False


# §2.4.8's three predicate prefixes, plus the modal §2.4.20 reads onto them.
# A predicate does not perform the operation its tail names -- it answers a
# question ABOUT it -- so the verb behind one of these is the subject and not a
# §2.4.4 hiding place. `can_scan_identity` asks whether a field's cache admits an
# identity scan; renaming its middle token would be renaming the question.
PREDICATE_PREFIXES = nv.PREDICATE_PREFIXES


def _is_abstract_raise(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """The whole body is one `raise` -- an abstract member, not a validator.

    `nv._always_raises` asks a DIFFERENT question and must not be reused here: it
    tests whether the LAST statement is a raise, which is true of every validator
    that guards with an early `return` and ends by raising. Substituting it
    exempted `_check_confirm_state` and `_check_confirm_lines_have_product` --
    two of the eight this rule was written for -- and the count still looked
    plausible, because it went from 8 to 6 rather than to 0. A helper whose name
    fits is not a helper whose question fits.
    """
    body = [
        n
        for n in node.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    return len(body) == 1 and isinstance(body[0], ast.Raise)


# §2.4.22: a method whose whole body is one ORM shaping call hands back the
# receiver reshaped, and §2.4.3's vocabulary has no row for it -- every verb
# there names a method that PRODUCES something, and `self.filtered(...)`,
# `self.sorted(...)`, `self.grouped(...)` and the `with_*` family produce
# nothing. The canonical is the ORM's own past participle, which that section
# argues is the framework's spelling rather than a missing verb.
#
# Three narrowings, and every one of them is what keeps the rule off a read:
#
# * The receiver must be `self`. §2.4.22 excludes a body that returns rows the
#   caller never held, and a navigation is exactly that:
#   `stock.move.line._get_pending_dest_moves` is
#   `self.move_id.move_dest_ids.filtered(...)` and is correctly a `_get_`,
#   because what comes back is not a subset of the receiver.
# * The envelope calls are NAMED rather than matched on a `with_` prefix. A
#   prefix test reported `assetsbundle`'s `minify`, whose body is `return
#   self.with_header()` and whose return is a string -- a plain class wrapping a
#   plain method, and nothing to do with an ORM environment.
# * The body must be exactly one return. A method that searches and then filters
#   returns rows the caller never held, which is the first bullet again.
#
# The name test is on the first TOKEN and not on a string prefix, which is a
# one-word difference that hid a finding: `_without_putaway_scan` returns
# `self.with_context(...)` and `"without_putaway_scan".startswith("with")` is
# True, so a `startswith` test exempted the one name §2.4.22 singles out. That
# section gives `_without_*` its own bullet precisely because it is NOT the
# `_with_` row -- it "names what is absent from the return, which is the one
# thing a recordset cannot show you" -- so exempting it by spelling was the
# rule agreeing with the defect. Measured when the token test replaced the
# prefix test: stock 0 -> 1 (that name, renamed with it) and every other scope
# unchanged.
_NARROWING_CALLS = frozenset({"filtered", "filtered_domain"})
_ORDERING_CALLS = frozenset({"sorted"})
_GROUPING_CALLS = frozenset({"grouped"})
_ENVELOPE_CALLS = frozenset(
    {"with_context", "with_company", "with_user", "with_env", "with_prefetch", "sudo"}
)
_SHAPING_PREFIX: dict[str, str] = {
    **dict.fromkeys(_NARROWING_CALLS, "filtered"),
    **dict.fromkeys(_ORDERING_CALLS, "sorted"),
    **dict.fromkeys(_GROUPING_CALLS, "grouped"),
    **dict.fromkeys(_ENVELOPE_CALLS, "with"),
}


def shaping_prefix(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The prefix §2.4.22 owes a body that is one ORM shaping call on `self`."""
    body = [
        n
        for n in node.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    call = body[0].value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
        return None
    receiver = call.func.value
    if not (isinstance(receiver, ast.Name) and receiver.id == "self"):
        return None
    return _SHAPING_PREFIX.get(call.func.attr)


# §2.4.4: "a first token repeating the model is what hides the verb". The model
# qualifies every method it declares, so a leading noun naming that same model
# buys nothing and costs `classify` its foothold -- it partitions on the first
# token and scores `bom` for `mrp.bom._bom_find`, which carries no rule. That
# section calls grepping a model's file for such a first token the cheapest
# search for this defect; this is that search made blocking.
#
# It needs none of the namespace weighing that keeps §2.4.4's infix rule in
# `CORE_ONLY_KINDS`. A namespace is legitimate only where it names a protocol
# several models implement, and **a namespace that names one model is not a
# namespace**, because it could not survive being moved to another -- so the
# model's own tokens are the one leading noun that needs no judgement about
# whether it is a noun.
#
# Two exclusions, both measured against the tree rather than argued:
#
# * A first token that is itself a verb is not a hiding place, whatever the
#   model is called. `base.partner.merge.automatic.wizard._merge_bank_accounts`
#   scores `merge` against the model's own tokens and is an ordinary
#   verb-object name; so is `change.password.wizard.change_password`. Without
#   this the rule is a report about wizard MODEL names, which is a different
#   question and not this one.
# A FINDING ON A PUBLIC METHOD IS A WIRE RENAME, NOT A LOCAL ONE, and the rule
# cannot say so from here. `web`'s `base.document.layout.document_layout_save`
# was this rule's first confirmation outside stock, and repairing it cost eleven
# binding sites across two repositories -- a `<button type="object" name=...>`,
# an `account` override, a machine-doc line, and SIX JS tour selectors spelled
# `button[name='document_layout_save']`, which no Python gate resolves. §2.4.4's
# own weighing applies before the rename ("a rename that cannot be completed
# inside the workspace is not begun"), and §2.4.19's applies after it, because a
# public name may be reached from a database column no grep can see. Two of
# core's three findings are public for exactly this reason.
#
# * §2.4.5's converter idiom names its source first by construction -- "`X_to_Y`
#   is the converter idiom, and `to` is the verb" -- so a converter on
#   `res.partner` spelled `partner_to_vcard` opens with the model's own noun
#   because the ordering rule for converters says to, and there is no verb
#   hidden behind it. The test is spelled here rather than taken from
#   `nv._CONVERTER_IDIOM`, which requires a SINGLE token on each side
#   (`[a-z0-9]+_to_[a-z0-9]+`) and so cannot see a converter whose operand is a
#   noun phrase. That narrowness is invisible in the census it feeds and would
#   be a false positive here.
_CONVERTER_IDIOM = re.compile(r"_?[a-z0-9_]+_to_[a-z0-9_]+")
_MODEL_NOUN_VERBS = (
    set(nv.ABOLISHED)
    | nv.CANONICAL_VERBS
    | nv.EXEC_VERBS
    | set(SYNONYMS)
    | ASSEMBLE
    | ACCUMULATE_VERBS
    | PREDICATE_PREFIXES
    | set(nv.HOOK_ATTRS)
    | {
        "action",
        "button",
        "copy",
        "create",
        "fields",
        "filtered",
        "grouped",
        "init",
        "load",
        "name",
        "read",
        "set",
        "sorted",
        "unlink",
        "view",
        "with",
        "without",
        "write",
    }
    # Verbs that appear INSIDE Odoo model names, because a wizard is named for
    # the operation it performs: `base.language.import`, `base.module.upgrade`,
    # `change.password.wizard`, `account.resequence.wizard`,
    # `mail.template.reset`, `product.merge`. Without them the rule reports
    # `import_lang` as "the model's own noun" when `import` is the verb, which
    # is not merely a false positive -- it is a false STATEMENT, and a finding a
    # reader cannot act on is worse than one nobody printed.
    #
    # `protocol_namespaces` already exempts any of these that a model NOT named
    # for it leads a method with, so these are only the ones no such witness
    # exists for in a scope. They are here rather than there because the witness
    # test is scope-local and this claim is not: `import` is a verb in every
    # tree, whether or not this one happens to contain the proof.
    | {
        "change",
        "edit",
        "export",
        "import",
        "install",
        "join",
        "merge",
        "reconcile",
        "rename",
        "resequence",
        "reset",
        "save",
        "send",
        "uninstall",
        "upgrade",
    }
    # The ORM's registry namespaces name no subject at all: every model is
    # `ir.*`, `res.*`, a `mixin.*` or an addon's own word, so `ir` and `res` in
    # leading position repeat a namespace rather than the model, and the rule
    # has nothing to say about them.
    | {"base", "ir", "mixin", "res"}
)


def leading_token(name: str) -> str:
    return name.lstrip("_").split("_")[0]


def model_class_nouns(cls: ast.ClassDef | None) -> frozenset[str]:
    """The words of the model a class IS, which is not the words it inherits.

    `_name` wins outright, and the distinction is the whole rule rather than a
    detail of it. A class carrying `_name` alongside `_inherit` is a model
    MIXING IN protocols, and §2.4.4 licenses a noun-first prefix exactly where it
    names "a protocol several models implement" -- so a mixin's own noun in
    leading position is the licensed case, not the defect. `sale.order` inherits
    `mixin.order.merge`, which declares `_merge_get_eligible_orders`,
    `_merge_group_orders`, `_merge_lines`, `_merge_finalize` and thirteen more:
    reading `_inherit` as the model's own name made `merge` a model noun and
    turned one deliberate 21-name convention into 21 findings, across three
    addons, in a mixin none of them declares.

    `_inherit` alone is the other case and is read: a class with no `_name` is an
    EXTENSION of that model -- this fork splits a model across such classes by
    seam (§2.4.13) -- so the inherited name is the name of the model it is
    declaring methods on. `StockPickingTypeDashboard` is `_inherit =
    "stock.picking.type"` and nothing else, and `_picking_count_buckets` was
    found on exactly that evidence.
    """
    if cls is None:
        return frozenset()
    names: dict[str, list[str]] = {"_name": [], "_inherit": []}
    for statement in cls.body:
        if not isinstance(statement, ast.Assign):
            continue
        for target in statement.targets:
            if not isinstance(target, ast.Name) or target.id not in names:
                continue
            value = statement.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names[target.id].append(value.value)
            elif isinstance(value, ast.List | ast.Tuple):
                names[target.id] += [
                    e.value
                    for e in value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
    own = names["_name"] or names["_inherit"]
    return frozenset(
        token for name in own for token in name.replace(".", "_").split("_") if token
    )


def protocol_namespaces(files: list[Path]) -> frozenset[str | tuple[str, str]]:
    """The leading nouns a scope licenses -- single tokens, and token PAIRS.

    Two witnesses, in one set because `model_noun_first` asks one question of it.
    The single tokens are the original test and are described below. The pairs
    are §2.4.4's other sentence: "a leading noun that names a thing is a
    namespace; a stack of adjectives is a qualifier", which it puts as a test for
    "a leading run of two or more tokens -- ask whether those tokens name
    something that exists in the system".

    A pair earns its place by appearing BEHIND A VERB HEAD somewhere else in the
    scope, and both halves of that are load-bearing. Appearing elsewhere at all
    is not enough: `_channel_type_policies` and `_channel_type_policy` are the
    same wrong prefix twice and would exempt each other, and `channel_join`
    would be exempted by `discuss_channel_join`, which is a concatenation rather
    than a concept. Behind a verb, the run is being USED as a noun by a method
    that already has its verb -- `_get_project_sharing_company`,
    `_is_project_sharing_accessible`, `_check_exists_collaborators_for_project_sharing`
    are three methods naming the *project sharing* feature, which is what makes
    `project_sharing_toggle_is_follower` a namespace at the head rather than
    `project.task`'s own noun leaking into first position.

    Measured when it landed: it exempts exactly two populations and moves no
    governed scope -- `project` 1 -> 0 and `account`'s two `_currency_table_*`
    (`_create_currency_table` and `_check_currency_table_monocurrency` are the
    witnesses), while core stays at 3 and `mail`'s ten stay findings. Session
    odoo-f2 found the case by hand in `addons/project` and argued it as an
    allowlist entry; a class of name belongs in the rule instead.

    THE SINGLE-TOKEN HALF: leading tokens a model that is NOT named for them
    also declares.

    §2.4.4 licenses a noun-first prefix "only where it names a protocol several
    models implement (`_message_*`, `_notify_*`, `_track_*`, `_portal_*`), never
    as a per-model tidy-up", and gives the test: **would the prefix survive
    being moved to another model**. This is that test run over the scope, and
    the answer is yes exactly when some model whose own name does not contain
    the token has already moved it there.

    Written that way it discharges a second question with the same evidence, and
    that is why it is one function rather than two. A token used in leading
    position by a model that is not named for it is either a protocol
    (`_mail_get_partners` on `res.partner`) or an ordinary verb that happens to
    appear in another model's name (`_merge_bank_accounts` on
    `base.partner.merge.automatic.wizard`, where `merge` leads methods on models
    with no `merge` in them). Both are exempt and neither needs telling apart --
    which is worth saying, because the alternative was a hand-written list of
    English verbs, and §2.4.20 spends a section on what a word list costs.

    Three properties, every one of them the conservative direction:

    * It is scope-local. A protocol declared in `mail` and implemented only in
      `stock` looks like a per-model tidy-up from inside `addons/stock`, so the
      rule can still report a name a wider index would exempt. That is why the
      finding says "unless it is a namespace" and why an addon is swept by hand
      before it is gated -- the standard `CORE_ONLY_KINDS` already sets for the
      infix rule.
    * A model split across extension classes (§2.4.13) is still one model here,
      because the test reads the model NAME rather than the class: `stock.quant`
      is thirteen classes and exempts nothing by being thirteen.
    * It exempts on one witness. Requiring two would catch a token a single
      other model borrowed, and would also lose every protocol with one
      implementor in the scope; the first is a name a reader can still find and
      the second is a false positive in a gate, so the trade goes this way.
    """
    licensed: set[str | tuple[str, str]] = set()
    for path in files:
        tree = _ast_cache.parse_file(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not nv.is_model_class(node):
                continue
            own = model_class_nouns(node)
            for member in node.body:
                if not isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if member.name.startswith("__"):
                    continue
                tokens = member.name.lstrip("_").split("_")
                if tokens[0] not in own:
                    licensed.add(tokens[0])
                if tokens[0] not in _MODEL_NOUN_VERBS:
                    continue
                licensed.update(itertools.pairwise(tokens[1:]))
    return frozenset(licensed)


def model_noun_first(
    name: str,
    cls: ast.ClassDef | None,
    namespaces: frozenset[str | tuple[str, str]] = frozenset(),
) -> str | None:
    """The model's own noun standing where the verb belongs."""
    if _CONVERTER_IDIOM.fullmatch(name):
        return None
    tokens = name.lstrip("_").split("_")
    first = tokens[0]
    if first in _MODEL_NOUN_VERBS or first in namespaces:
        return None
    if len(tokens) > 1 and (first, tokens[1]) in namespaces:
        return None
    return first if first in model_class_nouns(cls) else None


# §2.4.4 says a noun in FRONT of a verb hides it from `classify`, which
# partitions on the first token. The mirror was open the whole time:
# `nv.infix_abolished_verb` scans `tokens[1:-1]`, so the LAST token is read by
# nothing -- `classify` never reaches it and the infix rule stops one short of it
# on purpose. `_relation_delete`, `_term_lookup` and `_compile_and_validate` all
# sat in core wearing an abolished verb in that position.
#
# Two exclusions, both measured rather than argued from the armchair.
#
# `fetch` is §2.4.3's reserved ORM read operation and lands in trailing position
# constantly and correctly -- `_get_fields_to_fetch` names the operand set of
# `fetch()`, `search_fetch` is the operation.
#
# `domain` lands there constantly too and is right on both sides of §2.4.1: it is
# the field-hook spelling (`_domain_<field>`) and it is the ordinary Read
# (`_get_x_domain`). Session odoo-3a read 48 of them in `addons/stock` by hand
# and not one was an abolished verb in that position.
#
# Both are the same shape as the infix rule's own carve-out: a token that is a
# NOUN where it sits. Without them this rule is noisier than the one it mirrors.
TRAILING_EXEMPT = frozenset({"fetch", "domain"})


def trailing_abolished_verb(name: str) -> tuple[str, str] | None:
    """An abolished verb or synonym in the LAST token -- §2.4.4's other blind spot."""
    tokens = name.lstrip("_").split("_")
    if len(tokens) < 2:
        return None
    token = tokens[-1]
    if token in TRAILING_EXEMPT:
        return None
    # The assemble verbs are payload-ONLY in the shared table, and that carve-out
    # cannot survive here: a verb in the last position is what the name ends
    # with, so it can never also end in `_vals`. Reading `payload_only` in this
    # position would make the branch unreachable and quietly exempt every
    # `_report_build` in the tree. This gate already flags them whatever the tail
    # in the leading position; the same holds at the other end.
    if token in ASSEMBLE:
        return token, "_prepare_* or _get_*"
    if (entry := nv.ABOLISHED.get(token)) is not None:
        canonical, payload_choice = entry
        if payload_choice:
            return token, f"{canonical}* or {nv.PAYLOAD_CANONICAL}*"
        return token, f"{canonical}*"
    if (synonym := SYNONYMS.get(token)) is not None:
        return token, synonym[0]
    return None


def infix_synonym(name: str) -> str | None:
    """A synonym parked behind a noun -- §2.4.4's hiding place, one table over.

    `nv.infix_abolished_verb` asks the same question of the shared table. A
    synonym hides in the same position for the same reason: `classify` partitions
    on the first token, so a noun in front of the verb is invisible to it.
    """
    tokens = name.lstrip("_").split("_")
    if tokens[0] in PREDICATE_PREFIXES:
        return None
    for token in tokens[1:-1]:
        if token in SYNONYMS:
            return token
    return None


# §2.4.20: a public `check_*` that returns instead of raising is the Validation
# row's blind spot, and the row's discriminator is what the method does ON
# FAILURE. `_check_*` promises a raise; where the answer is *returns something*,
# the prefix is wrong whatever the underscore, and no gate aimed at internals
# sees it because no @api.constrains binds it.
#
# The proxy is mechanical -- the body returns a value and raises nothing -- and
# it IS a proxy: a check whose failure path is a helper's raise reads from here
# exactly like a read. Those are argued into the allowlist rather than renamed,
# which is the honest shape for a rule whose test is one frame deep.
#
# `predicate-raises` IS THAT RULE'S MIRROR and nobody had written it. §2.4.3's
# Predicate row says in its own words "never raises, no side effect"; the
# Validation row is the one that "raises on failure". So a `_is_`/`_has_`/
# `_can_`/`_should_` on a body that raises and returns nothing is asserting the
# opposite of what it does, and it reads a body, so it travels to an addon scope
# on the same terms as the other four.
#
# Measured before landing, allowlist off: core 0, stock 0, web 0, point_of_sale
# 0, account 0, mail 0 -- and sale 1, purchase 2, base_order 5. All eight were
# one family, the confirm/cancel guard registry on `mixin.order`, and all eight
# are renamed in the same commit as this rule, because `sale` and `purchase` are
# governed and a rule that lands ahead of its renames turns their hard zeros red.
#
# TWO THINGS THIS RULE CANNOT SEE, and the family is the argument for saying so
# rather than trusting the count:
#
# * `_can_confirm` and `_can_cancel` were the same defect and this test reads
#   them as CLEAN. They raise only indirectly -- through `_run_check_registry`,
#   which `getattr`s a list of method names -- so `raises(node)` is false on
#   their own bodies. Anything mechanical finds eight here and the real family
#   was ten. A body test cannot follow a dispatch.
# * The registry's members are STRINGS, so renaming one without its list leaves
#   `getattr` raising AttributeError at confirm time, and no import, lint or
#   gate sees it. Worse in one place: `agromarin/credit_management_approval`
#   REMOVES a name from the list under `contextlib.suppress(ValueError)`, so a
#   missed rename there does not even raise -- it silently stops removing, and a
#   credit check fires on confirm in the configuration built to skip it. The
#   check that catches this is not a gate, it is resolving every string literal
#   in a `*_validation_methods` list against the set of names actually defined
#   in the workspace; it read 0 unresolvable after this sweep.
#
# `_always_raises` is the carve-out and it is a CLASS of name rather than an
# exception, on the same terms `is_declaration_only` is one for the return-claim
# rules. A body whose whole content is `raise NotImplementedError` is an abstract
# member declaring a contract for its overrides, and the docstring above it
# usually says "Returns True if ..." -- the name describes what the OVERRIDE
# returns, so the base has no body to be judged on. Measured over the whole
# bundled tree after this sweep: the rule finds exactly two,
# `mixin.google.calendar.sync._is_google_insertion_blocked` and its Microsoft
# twin, and both are that shape. Without the carve-out they are the rule's only
# survivors anywhere in `addons/`, and both are correctly named.
def classify_definition(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    cls: ast.ClassDef | None = None,
    namespaces: frozenset[str | tuple[str, str]] = frozenset(),
    exception_names: frozenset[str] = frozenset(),
) -> tuple[str, str] | None:
    """Return (kind, why) for a definition the vocabulary refuses, else None.

    The name alone settles most of it; the rest need the body, because their
    discriminator is a claim about behaviour rather than about spelling, and
    `model-noun` needs the class, because its discriminator is a claim about
    what the receiver is called.
    """
    # §2.4.4's two infix rules and the trailing rule are the CANDIDATE-list
    # tier: that section says nothing mechanical can tell a verb parked behind a
    # noun from a noun spelled like a verb, which is why `CORE_ONLY_KINDS` holds
    # all three back from an addon scope. Returning one of them here lets a rule
    # that is NOT gated at this scope shadow one that is, and the definition is
    # then reported by nothing.
    #
    # `_without_putaway_scan` is that shape and is why this is not theoretical:
    # its last token is `scan`, a `SYNONYMS` entry, so `trailing` fired and
    # `measure` dropped it because stock holds that kind back -- while the body
    # is `return self.with_context(...)`, which `shaping` gates at every scope.
    # A candidate-tier name rule was hiding a gated body rule. So a weak hit is
    # remembered and returned only if nothing that reads the body fires.
    hit = classify_name(node.name)
    if hit is not None and hit[0] not in CORE_ONLY_KINDS:
        return hit
    weak_name_hit = hit
    stem = node.name.lstrip("_")
    verb = stem.partition("_")[0]
    if (prefix := shaping_prefix(node)) is not None and leading_token(stem) != prefix:
        why = (
            f"the body is one ORM shaping call and produces nothing -- §2.4.22; "
            f"a caller told `{verb}` has to open the body to learn the return is "
            f"the receiver reshaped. Take `_{prefix}_*`"
        )
        return ("shaping", why)
    if (noun := model_noun_first(node.name, cls, namespaces)) is not None:
        why = (
            f"`{noun}` is the declaring model's own noun, so it qualifies "
            f"nothing and hides the verb from `classify` -- §2.4.4; take the "
            f"row the body satisfies, with the model's word dropped"
        )
        return ("model-noun", why)
    # A bare name used to return here, before any rule that reads a body. That
    # was a hole and not a tier: `def _resolve(settings)` in `db/endpoints.py`
    # always answered and was never asked, because `resolve-total` sat below
    # this line. The body rules ask about behaviour, and a body has behaviour
    # whether or not a noun follows the verb; only the spelling rules need the
    # remainder, and `classify_name` has already declined it.
    if verb in ACCUMULATE_VERBS and owns_its_return(node):
        why = (
            f"{verb} -> _get_ -- it returns the value it made, which is the "
            f"Read row; a collector that fills a caller's container is not"
        )
        return ("accumulate", why)
    if verb in RETURN_CLAIM_VERBS and not is_declaration_only(node):
        if not returns_a_value(node) and not nv._always_raises(node):
            why = (
                f"`{verb}_` is a promise about the return and this returns "
                f"nothing -- §2.4.21; take the row the body satisfies"
            )
            return ("empty-return", why)
        if "or_create" not in stem and performs_orm_write(node):
            why = (
                "it creates or unlinks records under a name that promises only "
                "to describe them -- §2.4.11's _get_or_create_*, or §2.4.7"
            )
            return ("producer-writes", why)
    if verb == "get" and answers_a_question(node):
        why = (
            "every return is a boolean and one is computed -- §2.4.3's Predicate "
            "row: `_is_` / `_has_` / `_can_`, with the question in the tail"
        )
        return ("bool-under-get", why)
    if (
        builds_an_error(node, exception_names)
        and not _CONVERTER_IDIOM.fullmatch(node.name)
        and not (
            verb in _ERROR_BUILDER_VERBS
            and stem.rpartition("_")[2] in _ERROR_BUILDER_TAILS
        )
    ):
        why = (
            "every return is an exception it builds -- §2.4.10: the error is "
            "built here and raised there, and the builder is `_prepare_*_error` "
            "(or `_resolve_*_error` where a None return means not applicable)"
        )
        return ("error-builder", why)
    if verb in PREPOSITION_TOKENS and answers_a_question(node):
        why = (
            f"`{verb}` opens a prepositional phrase that answers a question -- "
            "§2.4.8: a predicate with no part of speech is the same defect as one "
            "with no prefix; take `_is_` / `_has_` / `_can_`"
        )
        return ("preposition-predicate", why)
    if (
        verb in PREDICATE_PREFIXES
        and not returns_a_value(node)
        and not raises(node)
        and not _is_abstract_raise(node)
        and not is_declaration_only(node)
    ):
        why = (
            "a predicate prefix over a body that returns nothing -- §2.4.8's "
            "inverted claim: the caller reads a question and gets a write; take "
            "the row the body satisfies"
        )
        return ("predicate-no-return", why)
    if verb == SHOW_VERB and answers_a_question(node):
        why = (
            "`show_` answers a question about the subject and returns a bool -- "
            "§2.4.20's fourth predicate prefix: `_is_` / `_has_` / `_can_`, with "
            "the modality moved into the tail as `_should_`'s is"
        )
        return ("show-predicate", why)
    if (
        verb == RESOLVE_VERB
        and not is_declaration_only(node)
        and not has_not_applicable_path(node)
        and not annotates_optional(node)
    ):
        why = (
            "`resolve_` is reserved for a PARTIAL producer -- the object, or "
            "nothing meaning not applicable (§2.4.3). This always produces one; "
            "take _get_, or the row the body satisfies"
        )
        return ("resolve-total", why)
    if verb == "check" and returns_a_value(node) and not raises(node):
        why = (
            "`check_` promises a raise on failure and this returns instead -- "
            "§2.4.20; take the row the body satisfies (_get_, _is_, _parse_)"
        )
        return ("check-returns", why)
    if (
        verb in PREDICATE_PREFIXES
        and raises(node)
        and not returns_a_value(node)
        and not _is_abstract_raise(node)
    ):
        why = (
            "a predicate prefix on a body that RAISES and returns nothing -- "
            "§2.4.3's Predicate row says 'never raises, no side effect', and the "
            "Validation row is the one that raises on failure; take `_check_*`"
        )
        return ("predicate-raises", why)
    return weak_name_hit


def classify_name(name: str) -> tuple[str, str] | None:
    """Return (kind, why) for a name the vocabulary refuses, else None."""
    if name.startswith("__") and name.endswith("__"):
        return None
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if not rest:
        if verb in ASSEMBLE:
            return "bare", f"`{verb}` alone -- abolished, and §2.4.6 wants a noun"
        return None
    if (hit := nv.classify(name)) is not None:
        return "leading", f"{hit[0]} -> {hit[1]}*"
    if verb in ASSEMBLE:
        return "assemble", f"{verb} -> _prepare_* or _get_*, on the consumer test"
    if (entry := SYNONYMS.get(verb)) is not None:
        return "synonym", f"{verb} -> {entry[0]} -- {entry[1]}"
    if (token := nv.infix_abolished_verb(name)) is not None:
        return "infix", f"`{token}` behind a noun -- §2.4.4, unless it is a noun"
    if (token := infix_synonym(name)) is not None:
        canonical, why = SYNONYMS[token]
        return "infix-synonym", f"`{token}` behind a noun -> {canonical} -- {why}"
    if (hit := trailing_abolished_verb(name)) is not None:
        token, canonical = hit
        why = (
            f"`{token}` in the LAST token -> {canonical}, with the verb in front "
            f"-- §2.4.4, unless it is a noun there"
        )
        return "trailing", why
    return None


def is_bare_abolished(name: str) -> bool:
    """A bare abolished verb that is not an assemble verb -- §2.4.6 [review].

    The gate does not report these; `candidates` does. The allowlist covers
    both, which is why `fetch` earns an entry: nothing would flag it, and
    without the entry it would read as an open question rather than a
    reservation.
    """
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    return not rest and verb not in ASSEMBLE and verb in nv.ABOLISHED


def measure(
    root: Path | None = None,
    *,
    apply_allowlist: bool = True,
    addon: str = "core",
) -> list[Violation]:
    """Every definition the vocabulary refuses, in one scope.

    `apply_allowlist=False` is what the allowlist's own test needs: two of the
    rules read a body, so "would this name be reported" cannot be answered from
    the name, and an entry that hides nothing has to be caught by rescanning
    without it.

    `addon` selects the allowlist and, through `CORE_ONLY_KINDS`, which rules
    are gated. `root` still overrides where to look, so a planted tree can be
    measured under either scope's rules.
    """
    files = scan_files(root if root is not None else addon_src(addon))
    if not files:
        raise RuntimeError(
            f"no Python files under {root or addon_src(addon)} -- refusing to "
            f"report a count from an empty scan"
        )
    allowed = load_allowlist(addon) if apply_allowlist else {}
    namespaces = protocol_namespaces(files)
    found: list[Violation] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        exception_names = exception_class_names(tree)
        fillers = slot_fillers(tree)
        for node, cls in definitions(tree):
            if node.name in allowed or nv._overrides_same_name(node):
                continue
            if id(node) in fillers:
                continue
            hit = classify_definition(node, cls, namespaces, exception_names)
            if hit is None:
                continue
            if addon != "core" and hit[0] in CORE_ONLY_KINDS:
                continue
            if addon == "core" and hit[0] in UNSWEPT_IN_CORE_KINDS:
                continue
            found.append(
                Violation(
                    path=_sources.display(path, ROOT),
                    line=node.lineno,
                    name=node.name,
                    kind=hit[0],
                    why=hit[1],
                )
            )
    found.sort(key=lambda v: (v.path, v.line))
    return found


def candidates(root: Path | None = None, addon: str = "core") -> list[Violation]:
    """What this scope declines to gate -- a population to read, not a count.

    Two groups. Bare abolished verbs, where several are the contract they
    implement and telling those apart is what §2.4.6's `[review]` tier is for.
    And the kinds the scope holds back: `resolve-total` in core, §2.4.4's two
    infix rules in an addon. Both are held back because nobody has read the
    population, so printing it is the only thing that makes the deferral
    honest -- and the only thing that lets the next reader close it.
    """
    allowed = load_allowlist(addon)
    files = scan_files(root if root is not None else addon_src(addon))
    namespaces = protocol_namespaces(files)
    found: list[Violation] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        for node, cls in definitions(tree):
            if node.name in allowed:
                continue
            if is_bare_abolished(node.name):
                verb = node.name.lstrip("_").partition("_")[0]
                found.append(
                    Violation(
                        path=_sources.display(path, ROOT),
                        line=node.lineno,
                        name=node.name,
                        kind="bare-review",
                        why=f"`{verb}` alone -- read the body before renaming",
                    )
                )
                continue
            # The kinds this scope declines to gate are a population to READ,
            # which is the whole content of holding them back. A rule that is
            # neither blocking nor printed has been dropped, not deferred.
            unswept = UNSWEPT_IN_CORE_KINDS if addon == "core" else CORE_ONLY_KINDS
            hit = classify_definition(
                node, cls, namespaces, exception_class_names(tree)
            )
            if hit is not None and hit[0] in unswept:
                found.append(
                    Violation(
                        path=_sources.display(path, ROOT),
                        line=node.lineno,
                        name=node.name,
                        kind=f"{hit[0]}-review",
                        why=hit[1],
                    )
                )
    found.sort(key=lambda v: (v.path, v.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--allowed", action="store_true", help="print the survivors and why"
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="print bare non-assemble verbs -- §2.4.6 [review], not gated",
    )
    parser.add_argument(
        "--addon",
        default="core",
        choices=GOVERNED_ADDONS,
        help="what to measure: core (default) is the odoo/ package, and the "
        "rest are bundled addons swept against the body-reading rules. A "
        "scope refuses rather than measures cleanly, because a tree nobody "
        "has read is pinned by nothing",
    )
    args = parser.parse_args(argv)

    if args.candidates:
        for item in candidates(addon=args.addon):
            print(f"  {item}")
        return 0

    if args.allowed:
        for name, why in sorted(load_allowlist(args.addon).items()):
            print(f"  {name:34} {why}")
        return 0

    try:
        found = measure(addon=args.addon)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    where = "odoo/" if args.addon == "core" else f"addons/{args.addon}/"
    print(f"Method vocabulary over every function in {where}")
    print("=" * 72)
    for item in found if args.top == 0 else found[: args.top]:
        print(f"  {item}")
    print(
        f"\n{len(found)} definition(s); "
        f"{len(load_allowlist(args.addon))} allowed by name"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
