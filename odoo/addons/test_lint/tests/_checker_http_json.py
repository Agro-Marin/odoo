import ast
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Violation:
    lineno: int
    col_offset: int
    message: str = (
        'type="http" route returns json.dumps() bare, so the JSON goes out as '
        "text/html; answer with request.prepare_json_response(...)"
    )


def _route_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Call | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name.endswith("route"):
            return decorator
    return None


def _is_http_route(decorator: ast.Call) -> bool:
    for keyword in decorator.keywords:
        if keyword.arg == "type":
            value = keyword.value
            return isinstance(value, ast.Constant) and value.value == "http"
    return True


def _is_json_dumps(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "dumps" and getattr(func.value, "id", "") == "json"
    return getattr(func, "id", "") == "dumps"


def _returns(node: ast.AST) -> Iterator[ast.Return]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Return):
            yield child
        yield from _returns(child)


def check(tree: ast.Module, nodes=None) -> Iterator[Violation]:
    for node in nodes if nodes is not None else ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorator = _route_decorator(node)
        if decorator is None or not _is_http_route(decorator):
            continue
        for ret in _returns(node):
            if ret.value is not None and _is_json_dumps(ret.value):
                yield Violation(ret.lineno, ret.col_offset)
