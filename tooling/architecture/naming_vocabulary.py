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
from _repo_root import find_odoo_root

ADR = "0033"

ROOT = find_odoo_root(Path(__file__).resolve())
SCAN_ROOTS = ("odoo", "addons")

SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".mypy_cache", "static", "lib", "vendored"}
)

#: ``_domain`` is deliberately absent: a domain feeds ``search()`` and a field's
#: ``domain=``, never ``create()``/``write()``, so it is not a payload. Domains
#: are their own family (ADR-0050) and are handled by ``classify`` below.
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

ABOLISHED: dict[str, tuple[str, bool]] = {
    "build": ("_prepare_", True),
    "make": ("_prepare_", True),
    "compose": ("_prepare_", True),
    "construct": ("_prepare_", True),
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
}

RESERVED = {
    "drop": "SQL DDL",
    "insert": "SQL DML",
    "push": "stack / queue",
    "discard": "set.discard — remove if present, never raise",
}


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
    if entry is None:
        return None
    canonical, payload_only = entry
    if name.endswith("_domain"):
        # A domain is neither read nor payload (ADR-0050): the abolished verb is
        # still abolished, but the target is the domain family, not _prepare_.
        return verb, "_domain_"
    if payload_only and not name.endswith(PAYLOAD_SUFFIXES):
        return None
    return verb, canonical


def infix_abolished_verb(name: str) -> str | None:
    """An abolished verb sitting where ``classify`` cannot see it, or None.

    ``classify`` reads the FIRST token, so a noun-first namespace hides the verb
    it precedes: ``_import_retrieve_customer`` reads as the verb ``import`` and
    scores clean. The shape is a candidate rather than a violation -- the token
    may belong to a field name (``_search_account_lookup_id``) or to a noun
    (``_compute_show_fetch_in_einvoices_button``) -- which is why §2.4 censuses
    it and the ratchet does not count it.
    """
    if classify(name) is not None:
        return None
    tokens = name.lstrip("_").split("_")
    for token in tokens[1:-1]:
        entry = ABOLISHED.get(token)
        if entry is None:
            continue
        _canonical, payload_only = entry
        if payload_only and not name.endswith(PAYLOAD_SUFFIXES):
            continue
        return token
    return None


#: The prefixes a field hook may carry. A method can hold TWO bindings -- five in
#: ``odoo/addons/base`` are an ``inverse=`` target that also carries
#: ``@api.onchange`` for the same field -- and then only one prefix can be spelled.
#: The rule is that the hook is named for its FIELD, so any of these satisfies it;
#: the prefix records which of the two roles the author chose to name.
HOOK_ATTRS = ("onchange", "inverse", "compute", "default", "search", "domain")


#: §2.4's *object leads its qualifier*, measured on the family that was converted
#: to it. A method answering "which fields" is ``_get_fields_<qualifier>``; the
#: mirrored spelling is what the rule abolished, so the second count is the one
#: that must stay at zero.
_FIELDS_HEAD_FIRST = re.compile(r"_?get_fields_[a-z0-9_]+")
_FIELDS_TAIL_FIRST = re.compile(r"_?get_[a-z0-9_]+_fields")

#: The rule above is general and only ``fields`` was converted. These are the
#: other head nouns a reader meets in the same position, and the pair is counted
#: over them to size what the conversion has not reached. It is a SEARCH and not
#: a verdict, exactly as ``PAYLOAD_SUFFIXES`` is: a head that never appears here
#: is measured by nothing, and a hit still has to be read. ``ids`` and the
#: payload suffixes are deliberately absent -- ``_get_partner_ids`` names a
#: FIELD, and the field-hook rule owns that spelling.
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
#: The head may be a compound -- ``model_names``, ``view_types`` -- so the tokens
#: before it are optional, and they are matched a WHOLE token at a time:
#: ``[a-z0-9_]*`` would read ``_get_surnames_x`` as the head ``names``.
_HEADS_HEAD_FIRST = tuple(
    re.compile(rf"_?get_(?:[a-z0-9]+_)*{head}_[a-z0-9_]+") for head in _COLLECTION_HEADS
)
_HEADS_TAIL_FIRST = tuple(
    re.compile(rf"_?get_[a-z0-9_]+_{head}") for head in _COLLECTION_HEADS
)


def collection_head_order(name: str) -> str | None:
    """``"head"``, ``"tail"`` or None for ``name`` against _COLLECTION_HEADS.

    ``fields`` is excluded in both directions: it has its own pair of figures,
    and a converted ``_get_fields_inheriting_views`` answers *which fields*, so
    counting its ``views`` tail would report the rule broken by a name keeping
    it.
    """
    if any(rx.fullmatch(name) for rx in _HEADS_HEAD_FIRST):
        return "head"
    if _FIELDS_HEAD_FIRST.fullmatch(name):
        return None
    if any(rx.fullmatch(name) for rx in _HEADS_TAIL_FIRST):
        return "tail"
    return None


#: §2.4's *``_find_`` is three operations wearing one verb*. The split is by what
#: the body does, because the verb does not say: an ORM read is the Read family,
#: a find-or-create WRITES and must not be renamed to ``_get_``, and the rest are
#: in-memory scans and derivations that the verb flatters.
_ORM_READ_CALLS = frozenset(
    {"search", "search_read", "search_count", "search_fetch", "browse", "read_group"}
)
#: The Payload row's four abolished spellings. ``classify`` reports one only when
#: the name also ends in a payload suffix, so the gap between these two counts is
#: what §2.4 states as the enforcement's reach.
#: §2.4's *wearing a dispatch prefix does not make a name a key*. ``_render``
#: builds its target from ``ir.actions.report.report_type``, whose Selection is
#: closed, so the keys are these three while the prefix is worn by many more.
_RENDER_DISPATCH_PREFIX = "_render_qweb_"
_RENDER_DISPATCH_KEYS = ("_render_qweb_html", "_render_qweb_pdf", "_render_qweb_text")

_ASSEMBLE_VERBS = frozenset({"build", "make", "compose", "construct"})
_FIND_OR_CREATE = re.compile(r"find_or_create(_|$)")
_GET_OR_CREATE = re.compile(r"get_or_create(_|$)")
#: §2.4's *a canonical verb can be wrong too*. A payload builder hands a mapping
#: to the ORM; it does not call the ORM itself, so a ``_prepare_*`` whose own body
#: writes is a candidate for the wrong family rather than the wrong spelling.
_ORM_WRITE_CALLS = frozenset({"create", "write", "unlink"})
#: §2.4's *an error is built here and raised there*. A method whose last statement
#: is a bare ``raise`` never returns, and the tree annotates none of them
#: ``NoReturn``; one that raises only sometimes is a validator and belongs to the
#: ``_check_`` row instead. The pair separates the two without reading a name.
_NORETURN = "NoReturn"
#: §2.4's *the converter idiom names two representations*. The strict shape only:
#: one token, ``_to_``, one token. ``_str_to_date`` matches and
#: ``_should_invite_members_to_join_call`` does not, which is the point -- the
#: second is a verb-first name whose ``to`` is a preposition.
_CONVERTER_IDIOM = re.compile(r"_?(?P<src>[a-z0-9]+)_to_(?P<dst>[a-z0-9]+)")


def _performs_orm_read(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _ORM_READ_CALLS
        for n in ast.walk(node)
    )


def _always_raises(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether ``node``'s body ends in a bare ``raise``, docstring ignored."""
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


def _performs_orm_write(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _ORM_WRITE_CALLS
        for n in ast.walk(node)
    )


def _bool_annotated(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Functions annotated ``-> bool``, at module level or on a model class.

    §2.4's predicate row used to be written as a signature test. It is not one:
    ``write`` and ``unlink`` return ``True`` by ORM convention, and a converter
    such as ``_coerce_bool`` returns a converted value -- neither is an answer to
    a question about a subject. The split below is what makes that measurable.
    """

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
    """Whether ``@api.ondelete`` decorates this method.

    A third decorator-bound family, after ``@api.constrains`` and
    ``@api.onchange``. It binds to no field at all -- the ORM calls it during
    ``unlink()`` -- so neither ``field_hook_naming.py`` nor the prefix table
    reaches it, and its first token is ``unlink``, which is reserved rather than
    abolished, so ``classify`` passes it too.
    """
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
    """The field names ``@api.onchange`` binds this method to, in order.

    An onchange hook names its fields from a DECORATOR argument, where the other
    five attributes name their method from inside the field declaration. That is
    why ``field_hook_naming.py`` -- which reads declarations -- cannot see this
    family at all, and why §2.4 censuses it here instead.
    """
    return _decorator_fields(node, "onchange")


def constrains_fields(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The field names ``@api.constrains`` binds this method to, in order.

    Read the same way as ``onchange_fields`` and counted for the opposite
    reason. §2.4 asks an onchange hook to be named for its field; it asks a
    constraint to be named for the CONDITION it enforces, because a constrains
    argument is a trigger and not a subject. The census exists to keep the
    field-hook rule from being extended here by analogy.
    """
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


#: §2.4's fourth binding: a method name written inside a server action's ``code``
#: field. That field stores **Python source in a database column**, so a shipped
#: data file is greppable and a database is not -- and the method is typically
#: PRIVATE, which is why the public/RPC test does not reach it.
_SERVER_ACTION_CODE = re.compile(
    r'<field[^>]*name="code"[^>]*>(.*?)</field>', re.DOTALL
)
_PRIVATE_CALL = re.compile(r"\.\s*(_[a-z][a-z0-9_]*)\s*\(")


def stored_code_references(
    roots: tuple[Path, ...] | None = None,
) -> tuple[int, int, int]:
    """``(files, code blocks, distinct private names)`` reached from stored code.

    Counted over the shipped data files, which is the half a grep can see. The
    other half -- server actions typed into the UI, which live only in a
    customer's ``ir_act_server`` rows -- is unenumerable by construction, so
    every figure here is a floor on a population whose true size nobody knows.
    """
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


def _display(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


#: Verbs §2.4 makes canonical. Together with ``ABOLISHED`` — which maps every
#: abolished spelling onto the canonical it loses to — these ARE the semantic
#: families the section prints, so the census below is derived from the rule
#: rather than from a second list that could drift away from it.
CANONICAL_VERBS = frozenset({"prepare", "get", "check", "update", "add", "remove"})

#: §2.4's *provisional* EXEC rule: verbs naming the act of running.
EXEC_VERBS = frozenset({"do", "run", "perform", "execute", "process", "handle"})


def family_of(verb: str) -> str | None:
    """The semantic family ``verb`` belongs to, or None if it carries no rule."""
    entry = ABOLISHED.get(verb)
    if entry is not None:
        return entry[0]
    return f"_{verb}_" if verb in CANONICAL_VERBS else None


@dataclass(frozen=True)
class Census:
    """The figures §2.4 states about the tree, measured in one pass.

    Every field is restated in ``doc/coding_guidelines.rst`` §2.4 and checked by
    ``tooling/architecture/doc_restated_counts.py``; none is a literal in prose.
    The population is the same one the ratchet counts -- methods declared
    directly on a model class, non-test, in this repository only -- so the
    section's sizing and its enforcement cannot disagree about scope.
    """

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
    set_: int
    update: int
    post: int
    family_stems: int
    identical_bodies: int

    @property
    def get_share(self) -> float:
        return 100.0 * self.get / self.methods


def _body_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Structure of ``node``'s body, docstring stripped; None if it says nothing.

    ``ast.dump`` rather than the source segment so that indentation, comments and
    line wrapping cannot make two identical bodies look different.
    """
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
    """Measure every figure §2.4 restates. Cached -- the walk is seconds long."""
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
    bool_pred = bool_other = 0
    find_read = find_oc = get_oc = find_misc = 0
    prepare_writing = 0
    converters: collections.Counter[str] = collections.Counter()
    raise_total = raise_unconditional = raise_noreturn = 0
    assemble_seen = assemble_flagged = 0
    render_prefixed = 0
    bodies: dict[str, set[str]] = collections.defaultdict(set)
    for path in files:
        try:
            tree = _ast_cache.parse_file(path)
        except SyntaxError, UnicodeDecodeError:
            continue
        # The directory test alone is a filename standing in for a scope, and it
        # matches `odoo/orm/models/mixins/`. §2.4's carve-out is about PACKAGES:
        # odoo/db, odoo/http, odoo/tools and odoo/orm internals speak SQL and
        # Python data-structure vocabulary wherever their files sit, so
        # `ensure_one` and `_fetch_query` are not ungoverned helpers -- the
        # vocabulary does not reach them at all. Requiring `addons` keeps the
        # count to the population the rule actually governs.
        parts = set(path.parts)
        if {"models", "wizard", "wizards"} & parts and "addons" in parts:
            module_level_helpers += sum(
                isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in tree.body
            )
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
                _stem = item.name.lstrip("_")
                if item.name.startswith(_RENDER_DISPATCH_PREFIX):
                    render_prefixed += 1
                if (
                    _stem.partition("_")[0] in _ASSEMBLE_VERBS
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
        set_=tally("set"),
        update=tally("update"),
        post=tally("post"),
        family_stems=sum(1 for verbs in stems.values() if len(verbs) >= 2),
        identical_bodies=sum(1 for n in bodies.values() if len(n) >= 2),
    )


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
        try:
            tree = _ast_cache.parse_file(path)
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not is_model_class(node):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                hit = classify(item.name)
                if hit is None:
                    continue
                out.append(
                    Violation(
                        path=str(_display(path)),
                        line=item.lineno,
                        name=item.name,
                        verb=hit[0],
                        canonical=hit[1],
                    )
                )
    out.sort(key=lambda v: (v.path, v.line))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
