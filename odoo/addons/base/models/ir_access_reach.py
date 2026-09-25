"""Recognize the reach an access row's domain spells out.

Pure: no registry, no cursor. The source converter and base's migration both
read a row's domain text through `propose`, and apply a proposal only when
`proves` finds the old domain and the proposed rows equal for a synthetic
principal, so a row whose text the recognizer misreads keeps its domain.
"""

import ast
import typing
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

USER = {"user.id", "uid", "[user.id]", "user.ids", "(user.id,)", "[uid]"}
USER_OR_UNSET = {
    "(user.id, False)",
    "[user.id, False]",
    "(False, user.id)",
    "[False, user.id]",
}
COMPANIES = {"company_ids"}
COMPANIES_OR_UNSET = {
    "company_ids + [False]",
    "[False] + company_ids",
    "[*company_ids, False]",
}
COMMERCIAL = {
    "[user.commercial_partner_id.id]",
    "user.commercial_partner_id.id",
    "user.commercial_partner_id.ids",
    "[user.partner_id.commercial_partner_id.id]",
    "user.partner_id.commercial_partner_id.id",
}
SELF_PARTNER = {"user.partner_id.id", "[user.partner_id.id]", "user.partner_id.ids"}
TEAMS = {
    "user.team_ids.ids": None,
    "user.sale_team_ids.ids": "sale",
    "user.purchase_team_ids.ids": "purchase",
}
# a field whose search reads the principal: a condition on it is a named
# predicate, never a fixed filter
PREDICATE_FIELDS = {
    "user_has_access": "base.user_has_access",
    "is_member": "base.is_member",
    "message_partner_ids": "mail.follows",
}
PRINCIPAL_FIELDS = {*PREDICATE_FIELDS, "is_self", "message_is_follower"}
PRINCIPAL_NAMES = (
    "user",
    "uid",
    "company_ids",
    "company_id",
    "group_ids",
    "website",
    "time",
    "context",
)


@dataclass(frozen=True, slots=True)
class Part:
    """One row a domain becomes: a rung read through an anchor, and a fixed filter."""

    reach: str
    kind: str = ""
    path: str = ""
    unset: bool = False
    hierarchy: str = ""
    usage: str = ""
    static: str = ""
    predicate: str = ""
    args: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True)
class Proposal:
    parts: list[Part] = field(default_factory=list)
    split: bool = False


def _prefix_tree(elts: list[ast.expr]) -> list[Any]:
    pos = 0

    def take() -> Any:
        nonlocal pos
        node = elts[pos]
        pos += 1
        if isinstance(node, ast.Constant) and node.value in ("&", "|"):
            return (node.value, [take(), take()])
        if isinstance(node, ast.Constant) and node.value == "!":
            return ("!", [take()])
        return node

    terms = []
    while pos < len(elts):
        terms.append(take())
    return terms


def _flat(term: Any, operator: str) -> list[Any]:
    if isinstance(term, tuple) and term[0] == operator:
        return [leaf for child in term[1] for leaf in _flat(child, operator)]
    return [term]


def _text(term: Any) -> list[str]:
    # a term back to the items of a prefix domain
    if isinstance(term, tuple):
        operator, children = term
        prefix = [repr(operator)] * (1 if operator == "!" else len(children) - 1)
        return prefix + [item for child in children for item in _text(child)]
    return [ast.unparse(term)]


def _domain_text(terms: list[Any]) -> str:
    if not terms:
        return ""
    items = ["'&'"] * (len(terms) - 1) + [
        item for term in terms for item in _text(term)
    ]
    return "[" + ", ".join(items) + "]"


def _reads_principal(node: Any) -> bool:
    if isinstance(node, tuple):
        return any(_reads_principal(child) for child in node[1])
    if (leaf := _leaf(node)) is not None and (
        leaf[0].rsplit(".", 1)[-1] in PRINCIPAL_FIELDS
    ):
        return True
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    return bool(names & set(PRINCIPAL_NAMES))


def _leaf(term: Any) -> tuple[str, str, str] | None:
    if isinstance(term, (ast.Tuple, ast.List)) and len(term.elts) == 3:
        path, operator = term.elts[0], term.elts[1]
        if (
            isinstance(path, ast.Constant)
            and isinstance(path.value, str)
            and isinstance(operator, ast.Constant)
            and isinstance(operator.value, str)
        ):
            return (
                # "x.id" on a many2one is x itself
                path.value.removesuffix(".id") if "." in path.value else path.value,
                operator.value,
                ast.unparse(term.elts[2]).replace('"', "'"),
            )
    return None


def _predicate(leaf: tuple[str, str, str]) -> Part | None:
    # a condition on a field whose search reads the principal, as the named
    # predicate that says it, the path to the field as its `at` argument
    path, operator, value = leaf
    at, _dot, field_name = path.rpartition(".")
    name = PREDICATE_FIELDS.get(field_name)
    if name is None:
        return None
    if field_name == "message_partner_ids":
        if operator not in ("=", "in") or value not in SELF_PARTNER:
            return None
    elif (operator, value) != ("=", "True"):
        return None
    return Part("predicate", predicate=name, args=(("at", f"{at}." if at else ""),))


def _rung(term: Any) -> Part | None:
    # one AND term that is exactly one rung, its "or unset" folded in
    leaves = [_leaf(leaf) for leaf in _flat(term, "|")]
    if not leaves or any(leaf is None for leaf in leaves):
        return None
    leaves = typing.cast("list[tuple[str, str, str]]", leaves)
    if len(leaves) == 1 and (part := _predicate(leaves[0])) is not None:
        return part
    paths = {path for path, _op, _value in leaves}
    if len(paths) != 1:
        return None
    path = paths.pop()
    marks = set()
    usage = None
    for _path, operator, value in leaves:
        if operator == "=" and value == "False":
            marks.add("unset")
        elif operator == "in" and value in COMPANIES:
            marks.add("company")
        elif operator == "in" and value in COMPANIES_OR_UNSET:
            marks |= {"company", "unset"}
        elif operator == "parent_of" and value in COMPANIES:
            marks.add("parent_of")
        elif operator in ("=", "in") and value in USER:
            marks.add("user")
        elif operator == "in" and value in USER_OR_UNSET:
            marks |= {"user", "unset"}
        elif operator == "child_of" and value in COMMERCIAL:
            marks.add("commercial")
        elif operator in ("=", "in") and value in SELF_PARTNER:
            marks.add("partner")
        elif operator == "in" and value in TEAMS:
            marks.add("team")
            usage = TEAMS[value]
        else:
            return None
    unset = "unset" in marks
    marks.discard("unset")
    if marks == {"company"}:
        return Part("company", "company", path, unset)
    if marks == {"parent_of"}:
        return Part("company", "company", path, unset, "parent_of")
    if marks == {"company", "parent_of"}:
        return None
    if marks == {"user"}:
        *owner, last = path.split(".")
        if owner and owner[-1] == "employee_id" and last == "user_id":
            return Part("own", "employee", ".".join(owner), unset)
        return Part("own", "creator" if path == "create_uid" else "owner", path, unset)
    if marks == {"partner"} and not path.endswith("message_partner_ids"):
        return Part("own", "partner", path, unset)
    if marks == {"commercial"} and not unset:
        return Part("partner", "partner", path)
    if marks == {"team"}:
        return Part("team", "team", path, unset, usage=usage or "")
    return None


def _conjunction(terms: list[Any]) -> Part | None:
    rungs, statics = [], []
    for term in terms:
        if (part := _rung(term)) is not None:
            rungs.append(part)
        elif not _reads_principal(term):
            statics.append(term)
        else:
            return None
    if len(rungs) > 1:
        return None
    static = _domain_text(statics)
    if static:
        try:
            ast.literal_eval(static)
        except ValueError:
            # a fixed filter beside a reach is a literal; one calling ref()
            # keeps the row a domain
            return None
    if not rungs:
        return Part("all", static=static)
    rung = rungs[0]
    return Part(
        rung.reach,
        rung.kind,
        rung.path,
        rung.unset,
        rung.hierarchy,
        rung.usage,
        static,
        rung.predicate,
        rung.args,
    )


def _dnf(term: Any, limit: int) -> list[list[Any]]:
    if isinstance(term, tuple) and term[0] == "&":
        result: list[list[Any]] = [[]]
        for child in term[1]:
            result = [a + b for a in result for b in _dnf(child, limit)]
            if len(result) > limit:
                raise OverflowError
        return result
    if isinstance(term, tuple) and term[0] == "|":
        # a rung's own "or unset" stays one conjunction
        if _rung(term) is not None:
            return [[term]]
        result = [conj for child in term[1] for conj in _dnf(child, limit)]
        if len(result) > limit:
            raise OverflowError
        return result
    return [[term]]


def propose(domain: str | None, kind: str, split_limit: int = 8) -> Proposal | None:
    """The rows a domain becomes, or None when it is not recognized."""
    text = (domain or "").strip()
    if not text:
        return Proposal([Part("all")])
    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    compact = ast.unparse(node).replace(" ", "")
    if compact in ("[]", "[(1,'=',1)]"):
        return Proposal([Part("all")])
    if compact == "[(0,'=',1)]":
        return Proposal([Part("none")])
    try:
        terms = _prefix_tree(list(node.elts))
    except IndexError:
        return None
    conjunction = [leaf for term in terms for leaf in _flat(term, "&")]
    if (part := _conjunction(conjunction)) is not None:
        return Proposal([part])
    if kind != "permission":
        return None
    tree = conjunction[0]
    for term in conjunction[1:]:
        tree = ("&", [tree, term])
    try:
        conjunctions = _dnf(tree, split_limit)
    except OverflowError:
        return None
    parts = [
        _conjunction([leaf for t in c for leaf in _flat(t, "&")]) for c in conjunctions
    ]
    if any(part is None for part in parts):
        return None
    return Proposal(typing.cast("list[Part]", parts), split=True)


# a principal nothing else is: every id distinct, so a proof that swaps two
# of them fails
_PRINCIPAL = {
    "user": 900001,
    "partner": 900002,
    "commercial_partner": 900003,
    "companies": [900011, 900012],
    "employees": [900021, 900022],
    "teams": {None: [900031, 900032], "sale": [900033], "purchase": [900034]},
    "units": [900041],
}


def _eval_context() -> dict[str, Any]:
    p = _PRINCIPAL

    def records(ids: list[int]) -> SimpleNamespace:
        return SimpleNamespace(ids=ids, id=ids[0] if ids else False)

    partner = SimpleNamespace(
        id=p["partner"],
        ids=[p["partner"]],
        commercial_partner_id=records([p["commercial_partner"]]),
    )
    user = SimpleNamespace(
        id=p["user"],
        ids=[p["user"]],
        partner_id=partner,
        commercial_partner_id=records([p["commercial_partner"]]),
        team_ids=records(p["teams"][None]),
        sale_team_ids=records(p["teams"]["sale"]),
        purchase_team_ids=records(p["teams"]["purchase"]),
        employee_ids=records(p["employees"]),
    )
    return {
        "user": user,
        "uid": p["user"],
        "company_ids": list(p["companies"]),
        "company_id": p["companies"][0],
        "ref": lambda xmlid: 900000 + len(xmlid),
    }


def compile_part(part: Part) -> Domain:
    # the part's domain for the synthetic principal, as ir.access compiles it
    p = _PRINCIPAL
    static = Domain(ast.literal_eval(part.static)) if part.static else Domain.TRUE
    if part.reach == "all":
        return static
    if part.reach == "none":
        return Domain.FALSE
    if part.reach == "predicate":
        at = dict(part.args).get("at", "")
        field_name = next(f for f, n in PREDICATE_FIELDS.items() if n == part.predicate)
        if field_name == "message_partner_ids":
            return Domain(at + field_name, "in", [p["partner"]]) & static
        return Domain(at + field_name, "=", True) & static
    path = part.path
    if part.reach == "own" and part.kind == "employee":
        # the employees bind is every employee whose user is the principal
        domain = Domain(f"{path}.user_id", "in", [p["user"]])
    elif part.reach == "own":
        values = {
            "owner": [p["user"]],
            "creator": [p["user"]],
            "partner": [p["partner"]],
        }[part.kind]
        domain = Domain(path, "in", values)
    elif part.reach == "team":
        domain = Domain(path, "in", p["teams"][part.usage or None])
    elif part.reach == "company":
        domain = Domain(path, part.hierarchy or "in", p["companies"])
    elif part.reach == "partner":
        domain = Domain(path, "child_of", [p["commercial_partner"]])
    else:
        raise ValueError(part.reach)
    if part.unset:
        domain |= Domain(path, "=", False)
    return domain & static


def _literals(field: str, operator: str, value: Any) -> list[Any]:
    # a condition as the literals it ORs: "= x" is "in (x,)", a value list
    # holding False is the list or "= False", a scalar tree value a 1-list
    if operator in ("child_of", "parent_of") and not isinstance(value, (list, tuple)):
        value = [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        values = tuple(sorted({v for v in value if v is not False}, key=repr))
        unset = False in value
    elif operator in ("=", "in") and value is not False:
        values, unset = (value,), False
    else:
        return [(field, operator, value)]
    if operator == "=":
        operator = "in"
    if operator != "in" or not unset:
        return [(field, operator, values)]
    return ([(field, "in", values)] if values else []) + [(field, "=", False)]


def _dnf_of(domain: Domain, limit: int = 256) -> frozenset[frozenset[Any]]:
    # a domain as a set of conjunctions of literals, so neither the text's
    # association, nor its order, nor a filter repeated across a split counts
    operator = getattr(domain, "OPERATOR", None)
    if operator == "|":
        result: set[frozenset[Any]] = set()
        for child in domain.children:
            result |= _dnf_of(child, limit)
        return frozenset(result)
    if operator == "&":
        conjunctions: set[frozenset[Any]] = {frozenset()}
        for child in domain.children:
            conjunctions = {a | b for a in conjunctions for b in _dnf_of(child, limit)}
            if len(conjunctions) > limit:
                raise OverflowError
        return frozenset(conjunctions)
    if operator == "!":
        return frozenset({frozenset({("!", _dnf_of(domain.child, limit))})})
    if domain.is_true():
        return frozenset({frozenset()})
    if domain.is_false():
        return frozenset()
    field = domain.field_expr
    field = field.removesuffix(".id") if "." in field else field
    return frozenset(
        frozenset({literal})
        for literal in _literals(field, domain.operator, domain.value)
    )


def proves(domain: str | None, proposal: Proposal) -> bool:
    """Whether the proposed rows reach what the domain did, for a principal."""
    old = (
        Domain(safe_eval(domain, _eval_context()))
        if (domain or "").strip()
        else Domain.TRUE
    )
    new = Domain.OR([compile_part(part) for part in proposal.parts])
    try:
        return _dnf_of(old) == _dnf_of(new)
    except OverflowError:
        return False
