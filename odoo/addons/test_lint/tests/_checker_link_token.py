import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass

# A bearer token that opens a record: named `token`, `access_token`,
# `document_token`, `booking_token`...; a device's or a vendor's credential
# (`*_api_token`, `oauth_*`) is a receiver's business, not a link's.
LINK_TOKEN = re.compile(r"(^|_)token$")
NOT_A_LINK = re.compile(r"(api|oauth|refresh|csrf|push|sync|page|next|bot|iot)_token$|^oauth")
COMPARES = frozenset({"consteq", "compare_digest"})
LOOKUPS = frozenset({"search", "search_count", "search_fetch", "search_read", "_search"})
# the one door that may compare a bearer token
RESOLVER = "/addons/base/models/access_link.py"


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str


def _terminal(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _terminal(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_link_token(name: str) -> bool:
    return bool(LINK_TOKEN.search(name)) and not NOT_A_LINK.search(name)


def _looked_up_field(node: ast.AST) -> str | None:
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Tuple)
            and len(sub.elts) == 3
            and isinstance(sub.elts[0], ast.Constant)
            and isinstance(sub.elts[0].value, str)
            and isinstance(sub.elts[1], ast.Constant)
            and sub.elts[1].value in ("=", "in")
            and _is_link_token(sub.elts[0].value.rpartition(".")[2])
        ):
            return sub.elts[0].value
    return None


def check(tree: ast.Module, path: str) -> Iterator[Violation]:
    if path.endswith(RESOLVER):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _terminal(node.func)
        if name in COMPARES and any(_is_link_token(_terminal(a)) for a in node.args):
            yield Violation(
                node.lineno,
                node.col_offset,
                "a bearer token compared outside access.link's resolver",
            )
        elif name in LOOKUPS and node.args and (field := _looked_up_field(node.args[0])):
            yield Violation(
                node.lineno,
                node.col_offset,
                f"a record looked up by its bearer token ({field}) outside "
                "access.link's resolver",
            )
