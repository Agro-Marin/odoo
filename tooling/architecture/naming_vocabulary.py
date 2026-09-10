from __future__ import annotations

import argparse
import ast
import collections
import functools
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _ast_cache
import _sources
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve())
SCAN_ROOTS = ("odoo", "addons")

# `_vendor` is how this workspace spells a vendored tree (`addons/auth_passkey/_vendor`,
# `odoo/libs/_vendor`); `vendored` matched nothing and eleven WebAuthn attestation
# verifiers under `_vendor/webauthn` were one widening away from being banked as ours.
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        "static",
        "lib",
        "vendored",
        "_vendor",
    }
)

PAYLOAD_SUFFIXES = (
    "_vals",
    "_values",
    "_data",
    "_dict",
    "_context",
    "_defaults",
    "_list",
    "_args",
    "_params",
)

READ_CANONICAL = "_get_"
PAYLOAD_CANONICAL = "_prepare_"

# Verb -> (canonical, payload_choice). The canonical is the row's spelling when
# the name carries no payload suffix; where payload_choice is True and the name
# ends in one, the Payload row wins and the canonical is `_prepare_`. That is
# §2.4.3's Payload row and Read row deciding between themselves for the assemble
# verbs (`_build_url` -> `_get_`, `_build_invoice_vals` -> `_prepare_`), and the
# reserved `_sync_` and the Payload row deciding for `synchronize`
# (`_synchronize_crons` -> `_sync_`, `_synchronize_partner_values` ->
# `_prepare_`). Every verb here is abolished unconditionally; the bool never
# decides whether the verb is seen, only which row it lands on. Reading it as a
# reach test is what let `_make_access_error` and twenty like it past the gate.
#
# The second block is §2.4.20: the table read as families rather than as a word
# list. Each is a word the guide's table does not print whose bodies satisfy one
# of its rows, and each was a core-only reading in `naming_core_vocabulary.
# SYNONYMS` until the addon floors had been read against it -- they have been,
# one repository at a time, and the counts are in the commit that moved them.
# The canonical printed for a synonym is §2.4.8's hypothesis, not a verdict:
# `detect` is the Predicate row where the body answers a question (`mail`'s six
# all were) and the Read row where it returns what it found, and only the body
# says which.
#
# What is NOT here is argued as much as what is, because a synonym table nobody
# can see the edge of is a word list again:
#
# * `refresh` has two reserved senses in `addons/` that a name cannot separate
#   from §2.4.17's cache verb: an OAuth *refresh token* (`google_account`,
#   `microsoft_account`, both calendars) and `REFRESH MATERIALIZED VIEW`
#   (`mixin_report_sql`). Core holds it as a synonym at a hard zero because
#   core's population has neither; this table cannot.
# * `find`, `filter`, `collect`, `gather` and `complete` need the body.
#   §2.4.11 keeps `_find_` out of this table in as many words (an ORM read
#   that also writes is `_get_or_create_`, a derivation is `_get_`); `_filter_`
#   is §2.4.22's `_filtered_` only where the return is the receiver reshaped;
#   a collector is the Read row only when it owns its return; `complete` is
#   three operations. `naming_core_vocabulary` reads the body for the first
#   four at its governed scopes, and that is where they are gated.
# * `emit` is `logging.Handler.emit`, `reap` and `probe` are terms of art from
#   a layer below -- §2.4.3's reserved-not-abolished terms.
# * `locate` reads 0 in every addon tree (mail's `_locate_unfollow_block` was
#   renamed by hand) and 5 in core, where `locate_node` is the view-inheritance
#   spec resolver in three modules. A row with no addon population and a core
#   population nobody has read is not a tightening; it is five allowlist entries.
ABOLISHED: dict[str, tuple[str, bool]] = {
    "build": (READ_CANONICAL, True),
    "make": (READ_CANONICAL, True),
    "compose": (READ_CANONICAL, True),
    "construct": (READ_CANONICAL, True),
    "assemble": (READ_CANONICAL, True),
    "craft": (READ_CANONICAL, True),
    "forge": (READ_CANONICAL, True),
    "fetch": ("_get_", False),
    "retrieve": ("_get_", False),
    "obtain": ("_get_", False),
    "lookup": ("_get_", False),
    "validate": ("_check_", False),
    "verify": ("_check_", False),
    "ensure": ("_check_", False),
    "control": ("_check_", False),
    "assign": ("_update_", False),
    "fill": ("_update_", False),
    "inject": ("_update_", False),
    "append": ("_add_", False),
    "delete": ("_remove_", False),
    "purge": ("_remove_", False),
    "digitize": ("_extract_", False),
    "interpret": ("_read_", False),
    "derive": ("_read_", False),
    "sniff": ("_guess_", False),
    # §2.4.20
    "populate": ("_update_", False),
    "tweak": ("_update_", False),
    "prune": ("_remove_", False),
    "sweep": ("_remove_", False),
    "seed": ("_create_", False),
    "scan": ("_read_", False),
    "detect": ("_is_", False),
    "determine": ("_get_", False),
    "calculate": ("_get_", False),
    # `calculate`'s abbreviations and its arithmetic sibling: `_cal_price` and
    # `_sum_costs` are the Read row spelled as the operation that produced the
    # answer, which §2.4.7 says is a read whatever arithmetic produced it.
    "calc": ("_get_", False),
    "cal": ("_get_", False),
    "sum": ("_get_", False),
    "synchronize": ("_sync_", True),
    "synchronise": ("_sync_", True),
    # §2.4.8: the predicate prefixes are three, and a necessity modal is not one
    # of them. `_should_`, `_need_`, `_must_` and `_want_` put the modality where
    # the question should be; the repair asks the question and moves the modality
    # into the tail (`_should_start_timer` -> `_is_timer_start_required`). mrp
    # drained its eight by hand while the gate read the addon as clean, which is
    # the shape this table exists to close.
    "should": ("_is_", False),
    "need": ("_is_", False),
    "needs": ("_is_", False),
    "must": ("_is_", False),
    "wants": ("_is_", False),
    "want": ("_is_", False),
}

RESERVED = {
    "parse": "one string in, one typed value out — a file is _read_ (§2.4.18)",
    "decode": "an encoding with a key or a scheme — a file format is _read_ (§2.4.18)",
    "index": "building a key→member mapping — text for a search index is _read_ (§2.4.18)",
    "drop": "SQL DDL",
    "insert": "SQL DML",
    "push": "stack / queue",
    "discard": "set.discard — remove if present, never raise",
}


# `RESERVED` was read by the census and by nothing that could fail: `measure()`
# consulted only `classify()`, and `classify()` returns None for every verb in
# it. So a reserved verb worn by a method that does not do the reserved thing
# was the one shape this gate defined and never enforced.
#
# Two of the seven state their reservation as a fact about the BODY rather than
# about the caller's intent, and only those two are enforced. `drop` is SQL DDL
# and `insert` is SQL DML or `list.insert`, both of which a reader can settle
# from the definition. The other five cannot be: nothing in an AST separates
# "one string in, one typed value out" from a `_read_` of a file, a keyed
# encoding from a format, a key→member mapping from a search index, a stack
# from any other append, or `set.discard` from a raise. A gate guessing at those
# would report `_parse_date` wrong for doing exactly what its verb reserves, so
# they stay documentation. Enforcing two is not a claim that five are fine — it
# is the whole checkable half, and §2.4.3's table owns the rest.
SQL_RESERVED: dict[str, str] = {"insert": "_add_", "drop": "_remove_"}

_SQL_CURSOR_METHODS = frozenset({"execute", "executemany"})
# `list.insert` is the other reservation the verb carries, and the caller-given
# index is what distinguishes it. A method that computes its own position is
# being asked to ADD a member, not to place one: `project`'s `_add_view_mode(
# xmlids, view_type, before=None)` derives the index from `before` and pairs
# with `_remove_view_mode`, so it was renamed out of `insert`;
# `ir.asset.paths.insert_paths(paths, bundle, index)` takes the position from
# its caller and is the idiom, which is why it keeps the verb.
_POSITION_PARAMS = frozenset({"index", "position", "pos"})
_DDL_DML = re.compile(
    r"\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\w+\s+SET"
    r"|DROP\s+(?:TABLE|INDEX|COLUMN|CONSTRAINT|SEQUENCE|VIEW|FUNCTION|TRIGGER))\b",
    re.IGNORECASE,
)


def _emits_sql(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # The annotation is here because the statement is often assembled by the
    # caller: `_insert_xmlids_extra_columns` returns `dict[str, SQL]` of columns
    # for an INSERT it never runs, and naming it for that statement is right.
    if node.returns is not None and "SQL" in ast.unparse(node.returns):
        return True
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            if (
                isinstance(func, ast.Attribute) and func.attr in _SQL_CURSOR_METHODS
            ) or (isinstance(func, ast.Name) and func.id == "SQL"):
                return True
        if (
            isinstance(inner, ast.Constant)
            and isinstance(inner.value, str)
            and _DDL_DML.search(inner.value)
        ):
            return True
    return False


def _takes_a_position(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    return any(
        arg.arg in _POSITION_PARAMS
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
    )


def _delegates_to_same_verb(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the body hands the operation to a sibling of the same verb.

    The measured tree has no instance of this: every `_drop_*` that survives
    `_emits_sql` runs its own DDL. It is here for the shape the discriminator
    would otherwise get wrong -- a `_drop_indexes` looping over `_drop_index`,
    where the statement is one frame down and the outer name is still honest.
    Same verb only, so it cannot be used to launder `_drop_stale` into calling
    an unrelated helper. The callee must also carry an OBJECT: `modes.insert(1,
    mode)` is `list.insert`, the builtin the verb is reserved FOR, and reading a
    bare `.insert` as delegation exempted `_add_view_mode` from the rule that
    renamed it.
    """
    verb = node.name.lstrip("_").partition("_")[0]

    def is_sibling(name: str) -> bool:
        callee_verb, _, rest = name.lstrip("_").partition("_")
        return bool(rest) and callee_verb == verb and name != node.name

    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and is_sibling(inner.func.attr)
        for inner in ast.walk(node)
    )


def reserved_misuse(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The canonical for a name wearing a reserved verb its body does not earn."""
    stem = node.name.lstrip("_")
    verb, _, rest = stem.partition("_")
    canonical = SQL_RESERVED.get(verb)
    if canonical is None or not rest:
        return None
    if (
        _emits_sql(node)
        or _delegates_to_same_verb(node)
        or (verb == "insert" and _takes_a_position(node))
    ):
        return None
    return canonical


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    verb: str
    canonical: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.name}  ->  {self.canonical}*"


def classify(name: str) -> tuple[str, str] | None:
    if name.startswith("__") and name.endswith("__"):
        return None
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if not rest:
        return None
    entry = ABOLISHED.get(verb)
    if name.endswith("_domain") and (entry is not None or verb in DOMAIN_TAIL_VERBS):
        return verb, DOMAIN_CANONICAL
    if entry is None:
        return None
    canonical, payload_choice = entry
    if payload_choice and name.endswith(PAYLOAD_SUFFIXES):
        return verb, PAYLOAD_CANONICAL
    return verb, canonical


PREDICATE_PREFIXES = frozenset({"is", "has", "can"})

# §2.4's table spells a free-standing domain `_get_domain_<what>`, and the
# `_domain` tail already routes every abolished verb there. `prepare` is a
# canonical verb on the wrong row for it: a domain is handed to `search()`, not
# to `create()`, so `_prepare_po_get_domain` claimed a payload it never was.
# Measured when this landed: 4 in addons, 5 in enterprise, 1 in agromarin, all
# renamed first so no floor moved.
# `get` is NOT in `DOMAIN_TAIL_VERBS`, and the rule for it lives in
# `domain_tail_under_get` below rather than in `classify`, on purpose:
# `naming_core_vocabulary.classify_name` reads `classify` as its `leading`
# kind and pins `_get_x_domain` as accepted there -- its question is whether
# `domain` is a trailing VERB, and it is not. Widening the shared name test
# would have moved every one of that gate's hard zeros (twenty in `stock`
# alone) through a file this rule does not own. So the name test stays as
# it was and the addon gate asks the fuller question in `measure()`.
DOMAIN_TAIL_VERBS = frozenset({"prepare"})
DOMAIN_CANONICAL = "_get_domain_"

# §2.4.1: a free-standing domain is `_get_domain_<what>`, and the tail-marked
# `_get_<what>_domain` is the spelling it retired. `base` was read by hand and
# `_get_eval_domain`, `_get_action_domain`, `_get_inheriting_views_domain` and
# `_get_name_search_domain` all returned a `Domain` under it, while the
# fieldhooks gate's `unmarked` kind sees only a body whose every return is a
# literal -- a domain assembled in a variable, or through `Domain.AND`, escaped
# both. The name is the claim: a `_domain` tail promises a `Domain`, and
# §2.4.1's converse says a method that does not return one must not wear the
# word either way. Two honest exceptions share one test: a hostname
# (`website`'s `_get_http_domain -> str`) and a record of a model whose own
# noun is *domain* (`mail.alias.domain`'s `_get_default_domain -> Self`). Both
# are read off the RETURN ANNOTATION, not the name, because the name cannot
# say which `domain` it means -- an annotation naming a type that is not a
# domain exempts, and an unannotated body is held to its name.
_DOMAIN_LIKE_ANNOTATION = re.compile(r"\b(?:Domain|list|tuple|Sequence|Iterable|Any)\b")


def returns_something_other_than_a_domain(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return node.returns is not None and not _DOMAIN_LIKE_ANNOTATION.search(
        ast.unparse(node.returns)
    )


def domain_tail_under_get(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    stem = node.name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if verb != "get" or not rest or not node.name.endswith("_domain"):
        return None
    if returns_something_other_than_a_domain(node):
        return None
    return DOMAIN_CANONICAL


def infix_abolished_verb(name: str) -> str | None:
    if classify(name) is not None:
        return None
    tokens = name.lstrip("_").split("_")
    # §2.4.20: a predicate does not perform the operation its tail names, it
    # answers a question ABOUT it, so behind `is_` / `has_` / `can_` / `should_`
    # there is no hidden verb -- `can_scan_identity` asks whether a cache admits
    # an identity scan. The core gate carried this carve-out for its synonym
    # table; it moves here with the words.
    if tokens[0] in PREDICATE_PREFIXES:
        return None
    for token in tokens[1:-1]:
        if token not in ABOLISHED:
            continue
        # Deliberately narrower than classify(): an assemble verb behind a noun
        # is only read as a verb when the payload suffix agrees. §2.4.4 owns
        # this population and calls it a candidate list, not a defect list --
        # most infix tokens belong to a field name (_compute_auto_delete_keep_log)
        # rather than to an operation, and nothing here can tell the two apart.
        if token in ASSEMBLE_VERBS and not name.endswith(PAYLOAD_SUFFIXES):
            continue
        return token
    return None


HOOK_ATTRS = ("onchange", "inverse", "compute", "default", "search", "domain")


_FIELDS_HEAD_FIRST = re.compile(r"_?get_fields_[a-z0-9_]+")
_FIELDS_TAIL_FIRST = re.compile(r"_?get_[a-z0-9_]+_fields")

_COLLECTION_HEADS = (
    "names",
    "types",
    "relations",
    "selections",
    "keys",
    "models",
    "modes",
    "records",
    "rules",
    "domains",
    "groups",
    "options",
    "columns",
    "tables",
    "actions",
    "views",
    "menus",
    "attachments",
    "urls",
)
_HEADS_HEAD_FIRST = tuple(
    re.compile(rf"_?get_(?:[a-z0-9]+_)*{head}_[a-z0-9_]+") for head in _COLLECTION_HEADS
)
_HEADS_TAIL_FIRST = tuple(
    re.compile(rf"_?get_[a-z0-9_]+_{head}") for head in _COLLECTION_HEADS
)


def collection_head_order(name: str) -> str | None:
    if any(rx.fullmatch(name) for rx in _HEADS_HEAD_FIRST):
        return "head"
    if _FIELDS_HEAD_FIRST.fullmatch(name):
        return None
    if any(rx.fullmatch(name) for rx in _HEADS_TAIL_FIRST):
        return "tail"
    return None


_ORM_READ_CALLS = frozenset(
    {"search", "search_read", "search_count", "search_fetch", "browse", "read_group"}
)
_RENDER_DISPATCH_PREFIX = "_render_qweb_"
# §2.4.4: a word in front of the verb that is not a namespace is a modality and
# belongs in the tail as a condition. `_safe_` and `_maybe_` are separate
# tokens and a reader sees them; `auto` FUSES with the verb (`_autoprint_`,
# `_autoconfirm_`), so `classify` reads `autoprint` as a verb carrying no rule
# and the name passes. A candidate population rather than a rule: `autovacuum`
# is a term of art, and nothing mechanical separates a fused modality from one.
_FUSED_MODALITY = re.compile(r"auto[a-z]{3,}")


def fused_modality_verb(name: str) -> str | None:
    token = name.lstrip("_").partition("_")[0]
    return token[4:] if _FUSED_MODALITY.fullmatch(token) else None


# §2.4.4: a canonical verb one token behind a first token that carries no rule
# is the shape `_push_prepare_move_copy_values` and `_log_activity_get_documents`
# wore -- the rule's own verb, hidden from a `classify` that partitions on the
# first token. Like the abolished-infix row it is a CANDIDATE list, not a defect
# list: `_ubl_add_*` and `_stripe_get_*` are namespaces §2.4.4 admits, and no
# reading of a name separates a protocol prefix from a noun parked in front of
# the verb. The first tokens excluded are the ones that already carry a rule of
# their own -- a verb from the abolished, canonical or execution tables, a hook or
# predicate prefix, an ORM operation,
# `action_`/`button_`, the four protocol namespaces §2.4.4 names, and the
# adverbs `post_`/`pre_` §2.4.12 reads as *when*.
_RULED_FIRST_TOKENS = frozenset(
    {
        "action",
        "button",
        "message",
        "notify",
        "track",
        "portal",
        "post",
        "pre",
        "unlink",
        "create",
        "write",
        "read",
        "copy",
        "name",
        "fields",
        "web",
        "view",
        "filtered",
        "sorted",
        "with",
        "selection",
        "constrains",
        "sync",
    }
)


def infix_canonical_verb(name: str) -> str | None:
    if classify(name) is not None:
        return None
    tokens = name.lstrip("_").split("_")
    first = tokens[0]
    if (
        first in _RULED_FIRST_TOKENS
        or first in CANONICAL_VERBS
        or first in ABOLISHED
        or first in EXEC_VERBS
        or first in PREDICATE_PREFIXES
        or first in HOOK_ATTRS
    ):
        return None
    return next((t for t in tokens[1:-1] if t in CANONICAL_VERBS), None)


_RENDER_DISPATCH_KEYS = ("_render_qweb_html", "_render_qweb_pdf", "_render_qweb_text")

ASSEMBLE_VERBS = frozenset(
    verb
    for verb, (canonical, payload) in ABOLISHED.items()
    if payload and canonical == READ_CANONICAL
)
_FIND_OR_CREATE = re.compile(r"find_or_create(_|$)")
_GET_OR_CREATE = re.compile(r"get_or_create(_|$)")
_ORM_WRITE_CALLS = frozenset({"create", "write", "unlink"})
_NORETURN = "NoReturn"
_CONVERTER_IDIOM = re.compile(r"_?(?P<src>[a-z0-9]+)_to_(?P<dst>[a-z0-9]+)")


def _performs_orm_read(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _ORM_READ_CALLS
        for n in ast.walk(node)
    )


def _always_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = [
        n
        for n in node.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    return bool(body) and isinstance(body[-1], ast.Raise)


def _overrides_same_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == node.name
        and isinstance(n.func.value, ast.Call)
        and isinstance(n.func.value.func, ast.Name)
        and n.func.value.func.id == "super"
        for n in ast.walk(node)
    )


def _performs_orm_write(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _ORM_WRITE_CALLS
        for n in ast.walk(node)
    )


def _bool_annotated(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    def _is_bool(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return isinstance(node.returns, ast.Name) and node.returns.id == "bool"

    found = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and _is_bool(n)
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and is_model_class(node):
            found += [
                n
                for n in node.body
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and _is_bool(n)
            ]
    return found


def is_ondelete_hook(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        func = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "ondelete":
            return True
    return False


def _decorator_fields(
    node: ast.FunctionDef | ast.AsyncFunctionDef, decorator_name: str
) -> list[str]:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != decorator_name:
            continue
        return [a.value for a in decorator.args if isinstance(a, ast.Constant)]
    return []


def onchange_fields(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return _decorator_fields(node, "onchange")


def constrains_fields(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return _decorator_fields(node, "constrains")


MODEL_BASES = frozenset({"Model", "TransientModel", "AbstractModel", "BaseModel"})


def is_model_class(node: ast.ClassDef) -> bool:

    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in MODEL_BASES:
            return True
    return any(
        isinstance(stmt, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id in ("_name", "_inherit")
            for t in stmt.targets
        )
        for stmt in node.body
    )


_SERVER_ACTION_CODE = re.compile(
    r'<field[^>]*name="code"[^>]*>(.*?)</field>', re.DOTALL
)
_PRIVATE_CALL = re.compile(r"\.\s*(_[a-z][a-z0-9_]*)\s*\(")


def stored_code_references(
    roots: tuple[Path, ...] | None = None,
) -> tuple[int, int, int]:
    scan = list(roots) if roots else [ROOT / r for r in SCAN_ROOTS]
    names: set[str] = set()
    files: set[Path] = set()
    blocks = 0
    for root in scan:
        if not root.is_dir():
            continue
        for path in root.rglob("*.xml"):
            if set(path.parts) & SKIP_DIRS:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if 'name="code"' not in text:
                continue
            for block in _SERVER_ACTION_CODE.findall(text):
                found = set(_PRIVATE_CALL.findall(block))
                if found:
                    files.add(path)
                    blocks += 1
                names |= found
    return len(files), blocks, len(names)


def _python_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if parts & SKIP_DIRS:
                continue
            if "tests" in parts or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


CANONICAL_VERBS = frozenset({"prepare", "get", "check", "update", "add", "remove"})

EXEC_VERBS = frozenset({"do", "run", "perform", "execute", "process", "handle"})


def family_of(verb: str) -> str | None:
    if verb in ASSEMBLE_VERBS:
        return PAYLOAD_CANONICAL
    entry = ABOLISHED.get(verb)
    if entry is not None:
        return entry[0]
    return f"_{verb}_" if verb in CANONICAL_VERBS else None


@dataclass(frozen=True)
class Census:
    methods: int
    get: int
    get_payload: int
    prepare: int
    check: int
    validate: int
    validate_synonyms: int
    exec_verbs: int
    generate: int
    assemble_verbs: int
    onchange_single: int
    onchange_named_for_field: int
    ondelete_hooks: int
    ondelete_canonical: int
    constrains_hooks: int
    constrains_canonical: int
    constrains_unruled: int
    constrains_single: int
    constrains_named_for_field: int
    constrains_multi_named_for_one: int
    fields_family_head_first: int
    fields_family_names: int
    fields_family_tail_first: int
    heads_head_first: int
    heads_tail_first: int
    heads_searched: int
    sync: int
    synchronize: int
    stored_code_files: int
    stored_code_blocks: int
    stored_code_names: int
    module_level_helpers: int
    helper_class_methods: int
    helper_classes: int
    nested_helpers: int
    nested_abolished: int
    nested_reserved: int
    calculate: int
    bool_returning_predicates: int
    bool_returning_others: int
    render_dispatch_prefixed: int
    render_dispatch_keys: int
    assemble_verb_methods: int
    assemble_verb_flagged: int
    find_total: int
    find_orm_read: int
    find_or_create: int
    get_or_create: int
    find_other: int
    resolve_total: int
    prepare_writing: int
    converter_idiom: int
    converter_idiom_names: int
    raise_total: int
    raise_unconditional: int
    raise_noreturn: int
    infix_abolished: int
    infix_canonical: int
    fused_modality: int
    set_: int
    update: int
    post: int
    family_stems: int
    identical_bodies: int

    @property
    def get_share(self) -> float:
        return 100.0 * self.get / self.methods


def _body_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body or (len(body) == 1 and isinstance(body[0], ast.Pass)):
        return None
    return hashlib.sha1(
        "\n".join(ast.dump(stmt, annotate_fields=False) for stmt in body).encode()
    ).hexdigest()


@functools.cache
def census(roots: tuple[Path, ...] | None = None) -> Census:
    scan = list(roots) if roots else [ROOT / r for r in SCAN_ROOTS]
    files = _python_files(scan)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in scan)} — "
            f"refusing to report a census from an empty scan"
        )

    names: list[str] = []
    onchange_single = onchange_named = 0
    ondelete_hooks = ondelete_canonical = 0
    constrains_hooks = constrains_canonical = constrains_unruled = 0
    constrains_single = constrains_named = constrains_multi_one = 0
    head_first: collections.Counter[str] = collections.Counter()
    tail_first = 0
    heads_head = heads_tail = 0
    _stored_files, _stored_blocks, _stored_names = stored_code_references(
        tuple(scan) if roots else None
    )
    module_level_helpers = 0
    helper_class_methods = helper_classes = 0
    nested_helpers = 0
    nested_abolished = nested_reserved = 0
    calculate = 0
    bool_pred = bool_other = 0
    find_read = find_oc = get_oc = find_misc = 0
    prepare_writing = 0
    converters: collections.Counter[str] = collections.Counter()
    raise_total = raise_unconditional = raise_noreturn = 0
    assemble_seen = assemble_flagged = 0
    render_prefixed = 0
    bodies: dict[str, set[str]] = collections.defaultdict(set)
    for path in files:
        tree = _ast_cache.parse_file(path)
        parts = set(path.parts)
        if {"models", "wizard", "wizards"} & parts and "addons" in parts:
            # The same scope hole `_module_scope_defs` closes in
            # `governed_definitions`, declared a second time here because the
            # census does not go through it. Reads 354 either way today -- no
            # addon `models/` or `wizard/` file currently declares a function
            # inside a `try` / `if` / `with` -- so closing it while it is free
            # costs no row. Left as `tree.body`, the first import shim added
            # under one of those directories would move a published figure and
            # read as drift.
            module_level_helpers += len(_module_scope_defs(tree))
            for top in tree.body:
                if isinstance(top, ast.ClassDef) and not is_model_class(top):
                    helper_classes += 1
                    helper_class_methods += sum(
                        isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                        for n in top.body
                    )
        for func in _bool_annotated(tree):
            if func.name.lstrip("_").startswith(("is_", "has_", "can_")):
                bool_pred += 1
            else:
                bool_other += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not is_model_class(node):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                names.append(item.name)
                for inner in ast.walk(item):
                    if inner is item or not isinstance(
                        inner, ast.FunctionDef | ast.AsyncFunctionDef
                    ):
                        continue
                    nested_helpers += 1
                    if classify(inner.name) is not None:
                        nested_abolished += 1
                    elif inner.name.lstrip("_").partition("_")[0] in RESERVED:
                        nested_reserved += 1
                _stem = item.name.lstrip("_")
                if _stem.partition("_")[0] == "calculate" and _stem.partition("_")[2]:
                    calculate += 1
                if item.name.startswith(_RENDER_DISPATCH_PREFIX):
                    render_prefixed += 1
                if (
                    _stem.partition("_")[0] in ASSEMBLE_VERBS
                    and _stem.partition("_")[2]
                ):
                    assemble_seen += 1
                    assemble_flagged += classify(item.name) is not None
                if _FIND_OR_CREATE.match(_stem):
                    find_oc += 1
                elif _GET_OR_CREATE.match(_stem):
                    get_oc += 1
                elif _stem.startswith("find_"):
                    if _performs_orm_read(item):
                        find_read += 1
                    else:
                        find_misc += 1
                if _stem.startswith("raise_"):
                    raise_total += 1
                    raise_unconditional += _always_raises(item)
                    raise_noreturn += (
                        isinstance(item.returns, ast.Name)
                        and item.returns.id == _NORETURN
                    )
                if _stem.startswith("prepare_") and _performs_orm_write(item):
                    prepare_writing += 1
                if _CONVERTER_IDIOM.fullmatch(item.name):
                    converters[item.name] += 1
                if _FIELDS_HEAD_FIRST.fullmatch(item.name):
                    head_first[item.name] += 1
                elif _FIELDS_TAIL_FIRST.fullmatch(item.name):
                    tail_first += 1
                match collection_head_order(item.name):
                    case "head":
                        heads_head += 1
                    case "tail":
                        heads_tail += 1
                if is_ondelete_hook(item):
                    ondelete_hooks += 1
                    ondelete_canonical += item.name.startswith("_unlink_except_")
                bound = onchange_fields(item)
                if len(bound) == 1:
                    onchange_single += 1
                    onchange_named += item.name in {
                        f"_{attr}_{bound[0]}" for attr in HOOK_ATTRS
                    }
                if constrained := constrains_fields(item):
                    constrains_hooks += 1
                    constrains_canonical += _stem.startswith("check_")
                    constrains_unruled += (
                        "check" not in _stem.split("_")
                        and _stem.partition("_")[0] not in ABOLISHED
                    )
                    if len(constrained) == 1:
                        constrains_single += 1
                        constrains_named += item.name == f"_check_{constrained[0]}"
                    else:
                        constrains_multi_one += any(
                            item.name == f"_check_{field}" for field in constrained
                        )
                fingerprint = _body_fingerprint(item)
                if fingerprint is not None:
                    bodies[fingerprint].add(item.name)

    def split(name: str) -> tuple[str, str]:
        verb, _, rest = name.lstrip("_").partition("_")
        return verb, rest

    def tally(*verbs: str) -> int:
        return sum(1 for n in names if split(n)[0] in verbs and split(n)[1])

    stems: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for name in names:
        verb, rest = split(name)
        family = family_of(verb)
        if family is not None and rest:
            stems[family, rest].add(verb)

    return Census(
        methods=len(names),
        get=tally("get"),
        get_payload=sum(
            1 for n in names if split(n)[0] == "get" and n.endswith(PAYLOAD_SUFFIXES)
        ),
        prepare=tally("prepare"),
        check=tally("check"),
        validate=tally("validate"),
        validate_synonyms=tally("verify", "ensure", "control"),
        exec_verbs=tally(*EXEC_VERBS),
        generate=tally("generate"),
        assemble_verbs=tally("build", "make", "compose", "construct"),
        onchange_single=onchange_single,
        onchange_named_for_field=onchange_named,
        ondelete_hooks=ondelete_hooks,
        ondelete_canonical=ondelete_canonical,
        constrains_hooks=constrains_hooks,
        constrains_canonical=constrains_canonical,
        constrains_unruled=constrains_unruled,
        constrains_single=constrains_single,
        constrains_named_for_field=constrains_named,
        constrains_multi_named_for_one=constrains_multi_one,
        fields_family_head_first=sum(head_first.values()),
        fields_family_names=len(head_first),
        fields_family_tail_first=tail_first,
        heads_head_first=heads_head,
        heads_tail_first=heads_tail,
        heads_searched=len(_COLLECTION_HEADS),
        sync=tally("sync"),
        synchronize=tally("synchronize", "synchronise"),
        stored_code_files=_stored_files,
        stored_code_blocks=_stored_blocks,
        stored_code_names=_stored_names,
        module_level_helpers=module_level_helpers,
        helper_class_methods=helper_class_methods,
        helper_classes=helper_classes,
        nested_helpers=nested_helpers,
        nested_abolished=nested_abolished,
        nested_reserved=nested_reserved,
        calculate=calculate,
        bool_returning_predicates=bool_pred,
        bool_returning_others=bool_other,
        render_dispatch_prefixed=render_prefixed,
        render_dispatch_keys=len(_RENDER_DISPATCH_KEYS),
        assemble_verb_methods=assemble_seen,
        assemble_verb_flagged=assemble_flagged,
        find_total=find_read + find_oc + find_misc,
        find_orm_read=find_read,
        find_or_create=find_oc,
        get_or_create=get_oc,
        find_other=find_misc,
        resolve_total=tally("resolve"),
        prepare_writing=prepare_writing,
        converter_idiom=sum(converters.values()),
        converter_idiom_names=len(converters),
        raise_total=raise_total,
        raise_unconditional=raise_unconditional,
        raise_noreturn=raise_noreturn,
        infix_abolished=sum(1 for n in names if infix_abolished_verb(n)),
        infix_canonical=sum(1 for n in names if infix_canonical_verb(n)),
        fused_modality=sum(1 for n in names if fused_modality_verb(n)),
        set_=tally("set"),
        update=tally("update"),
        post=tally("post"),
        family_stems=sum(1 for verbs in stems.values() if len(verbs) >= 2),
        identical_bodies=sum(1 for n in bodies.values() if len(n) >= 2),
    )


# §2.4.13 gives the vocabulary three populations this gate could not see. It
# governs "every function in the core package `odoo/`, at module level and on
# plain classes alike", and in an addon it governs "the module's own helpers
# too" -- a function declared at module level, a method on a plain class in the
# same file, and a function nested inside either. `measure()` implemented the
# scope as a class-membership test, so all three were counted by `census()` and
# gated by nothing.
#
# The directory list that the first widening introduced stopped at `models/`
# and `wizard/`, and §2.4.13 records what that cost: a controller class derives
# from `http.Controller`, so `is_model_class` was false for it and its directory
# was in no list, and every route handler and every helper under an addon's
# `controllers/`, `tools/`, `report/` and `utils/` was in the population of
# nothing. Measured over EVERY directory of an addon the hole was 243
# definitions, 75 of them under directories no earlier scan had thought to
# name -- which is the argument for a rule with no list in it. The discriminator
# is a `__manifest__.py` above the file, which is what makes a directory an
# addon and what the core package has none of.
#
# Migration scripts are governed. §2.4.13 recorded that the two gates answered
# that question differently by mechanism rather than by decision -- this one
# reached 318 migration files and governed none of their 500 functions, while
# `naming_core_vocabulary` reads every function at a governed scope and had
# already renamed one. A helper in an upgrade script is this repository's code,
# is reviewed like any other, and has no binding a rename could miss, so the
# cheaper answer is also the consistent one.
#
# The core package is deliberately NOT widened here. `naming_core_vocabulary.py`
# already reads every function under `odoo/odoo/` on sharper rules and holds a
# hard zero with an argued allowlist, so widening this gate over the same tree
# would ask one question twice and answer it two ways -- `append_paths` is the
# case in point, a name §2.4.13 argues is correct and that gate allowlists.


@functools.cache
def _is_addon_directory(directory: Path) -> bool:
    return any(
        (parent / "__manifest__.py").is_file()
        for parent in (directory, *directory.parents)
    )


def governs_module_helpers(path: Path) -> bool:
    if path.is_relative_to(ROOT / "odoo"):
        return False
    return _is_addon_directory(path.parent)


def _module_scope_defs(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function whose nearest enclosing scope is the module.

    `for node in tree.body` was statement-correct and the question is
    scope-correct: a `def` at module scope but inside a compound statement lives
    in `tree.body[i].body`, so a `try` / `if` / `with` hid it from that loop --
    and from the closure walk below, which starts from functions and these are
    inside none. The shape that found it is the import shim, where the same name
    is defined twice under `try` and `except ImportError` and neither definition
    was in any gate's population:

        try:
            def _make_linestring_wkt(coords): ...
        except ImportError:
            def _make_linestring_wkt(coords): raise ...

    Measured when this landed: 0 newly reported in odoo, enterprise and
    design-themes, and 0 in agromarin -- the two it found there were renamed in
    agromarin `125a5ceec` first, so the widened scan met a tree that already
    satisfied it. `agromarin` is a §9.4 hard zero and a contract rather than a
    floor, which is why the order mattered.
    """
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def walk(node: ast.AST, inside_a_scope: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                if not inside_a_scope:
                    found.append(child)
                walk(child, True)
            elif isinstance(child, ast.ClassDef):
                walk(child, True)
            else:
                walk(child, inside_a_scope)

    walk(tree, False)
    return found


def governed_definitions(
    path: Path, tree: ast.Module
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every definition the vocabulary reaches in one file, each exactly once."""
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    seen: set[int] = set()

    def take(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if id(node) not in seen:
            seen.add(id(node))
            found.append(node)

    widened = governs_module_helpers(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and (is_model_class(node) or widened):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    take(item)
    if widened:
        for node in _module_scope_defs(tree):
            take(node)
        # A `def` at any depth inside any other one. Walking from every function
        # rather than from the module reaches a closure inside a closure, and
        # `take` is what keeps the deeper ones from being counted once per
        # enclosing frame.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(node):
                    if inner is not node and isinstance(
                        inner, ast.FunctionDef | ast.AsyncFunctionDef
                    ):
                        take(inner)
    return found


# `generate` is §2.4.7's largest payload verb and claims a product like the
# other three; a `_generate_missing_avatars` that writes `image_1920` on the
# receiver and returns nothing did the Mutation row's work under it.
_PRODUCER_VERBS = frozenset({"get", "resolve", "prepare", "generate"})
_TRIVIAL_CALLS = frozenset({"check_singleton", "ensure_one"})
_ORM_CREATE_CALL = "create"


def _own_scope(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(
            child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef
        ):
            continue
        yield child
        yield from _own_scope(child)


def _returns_a_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for inner in _own_scope(node):
        if isinstance(inner, ast.Yield | ast.YieldFrom):
            return True
        if isinstance(inner, ast.Return) and inner.value is not None:
            if not (
                isinstance(inner.value, ast.Constant) and inner.value.value is None
            ):
                return True
    return False


def _stores_into_something(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for inner in _own_scope(node):
        if isinstance(inner, ast.AugAssign) and isinstance(
            inner.target, ast.Attribute | ast.Subscript
        ):
            return True
        if isinstance(inner, ast.Attribute | ast.Subscript) and isinstance(
            inner.ctx, ast.Store
        ):
            return True
    return False


def _is_trivial_statement(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass | ast.Raise):
        return True
    if isinstance(stmt, ast.Return):
        return stmt.value is None or isinstance(stmt.value, ast.Constant)
    if isinstance(stmt, ast.Expr):
        value = stmt.value
        if isinstance(value, ast.Constant):
            return True
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr in _TRIVIAL_CALLS
        )
    return False


def _is_extension_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return all(_is_trivial_statement(stmt) for stmt in node.body)


def _is_hook_bound(name: str, tree: ast.AST) -> bool:
    return any(
        isinstance(inner, ast.keyword)
        and inner.arg in HOOK_ATTRS
        and isinstance(inner.value, ast.Constant)
        and inner.value.value == name
        for inner in ast.walk(tree)
    )


def producer_without_product(
    node: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.AST
) -> str | None:
    """The canonical for a producer prefix on a body that hands nothing back.

    `_get_`, `_resolve_` and `_prepare_` each claim a return: the Read row's
    value, §2.4.11's object-or-None, the Payload row's mapping. A body under
    one of them that never returns or yields a value, and instead stores into
    something -- a dict the caller owns, a field on the receiver -- or writes
    records, did the Mutation row's work under a producer's name, and
    `_update_` is its canonical whatever the prefix says.

    The store-or-write test is what keeps this from being "no return means
    mutation". A body with no product and no store is some other question:
    `_get_reconciled_checks_error` only raises and is §2.4.8's, a
    `_get_..._vals` whose base branch raises NotImplementedError and whose
    override returns is an extension point. Three more bodies are left alone
    on the same argument. An extension stub -- docstring, `pass`, a bare
    `return`, `check_singleton()`, a `raise` -- returns nothing because it
    does nothing yet. A body whose last statement raises is §2.4.10's. And a
    name a field declaration in the same file binds as a hook belongs to
    `field_hook_naming.py`, whose `unprefixed` kind names it (`_get_mo_count`
    assigning five `count_mo_*` fields is a `_compute_`); reporting it here
    too would be one question answered by two gates. A same-name override
    reaching `super()` is excluded upstream of every rule in `measure()`.
    """
    stem = node.name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if verb not in _PRODUCER_VERBS or not rest:
        return None
    if _returns_a_value(node) or _is_extension_stub(node) or _always_raises(node):
        return None
    if not (_stores_into_something(node) or _performs_orm_write(node)):
        return None
    if _is_hook_bound(node.name, tree):
        return None
    # A body whose only ORM write is `create()` took the domain operation's
    # name, not the Mutation row's: §2.4.7 renamed `_generate_consume_moves` to
    # `_create_consume_moves` on exactly that reading. Any `write()` or
    # `unlink()` beside it makes the body a mutation again.
    writes = {
        n.func.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _ORM_WRITE_CALLS
    }
    if writes == {_ORM_CREATE_CALL} and not _stores_into_something(node):
        return "_create_"
    return "_update_"


# §2.4.22: a body that is one ORM shaping call hands back the receiver
# reshaped -- a subset of it, or the same rows in another envelope -- and a
# producer prefix on it promises a value the caller never gets. The rule is
# for a body that is ONE such call and nothing else; a method that searches
# and then filters returns rows the caller never held and is a read.
_SHAPING_CALLS = {
    "filtered": "_filtered_",
    "filtered_domain": "_filtered_",
    "sorted": "_sorted_",
    "grouped": "_grouped_",
}
_ENVELOPE_CANONICAL = "_with_"
_RESHAPED_PREFIXES = frozenset({"get", "check", "set", "prepare", "resolve"})


def reshaped_receiver(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    stem = node.name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if verb not in _RESHAPED_PREFIXES or not rest:
        return None
    body = [
        stmt
        for stmt in node.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    value = body[0].value
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "self"
    ):
        return None
    attr = value.func.attr
    if attr in _SHAPING_CALLS:
        return _SHAPING_CALLS[attr]
    if attr == "sudo" or attr.startswith("with_"):
        return _ENVELOPE_CANONICAL
    return None


def measure(roots: list[Path] | None = None) -> list[Violation]:

    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    files = _python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    out: list[Violation] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        for item in governed_definitions(path, tree):
            if _overrides_same_name(item):
                continue
            hit = classify(item.name)
            if hit is None:
                canonical = (
                    reserved_misuse(item)
                    or domain_tail_under_get(item)
                    or producer_without_product(item, tree)
                    or reshaped_receiver(item)
                )
                if canonical is None:
                    continue
                hit = (item.name.lstrip("_").partition("_")[0], canonical)
            out.append(
                Violation(
                    path=_sources.display(path, ROOT),
                    line=item.lineno,
                    name=item.name,
                    verb=hit[0],
                    canonical=hit[1],
                )
            )
    out.sort(key=lambda v: (v.path, v.line))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verb", help="restrict the report to one abolished verb")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of odoo/ and addons/"
    )
    parser.add_argument(
        "--top", type=int, default=20, help="offenders to list (0 = all)"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.verb:
        found = [v for v in found if v.verb == args.verb]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Method-naming vocabulary (§2.4 abolished verbs)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_verb = collections.Counter(v.verb for v in found)
    by_canon: collections.Counter[str] = collections.Counter()
    for v in found:
        by_canon[v.canonical] += 1
    print(f"\n{len(found)} definition(s) using an abolished verb\n")
    print("  by canonical target:")
    for canon, n in by_canon.most_common():
        verbs = sorted({v.verb for v in found if v.canonical == canon})
        print(f"    {canon + '*':<12}{n:>5}   from {', '.join(verbs)}")
    print("\n  by verb:")
    for verb, n in by_verb.most_common():
        print(f"    _{verb}_{'':<8}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/naming_vocabulary.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py naming --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
