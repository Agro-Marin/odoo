import ast
import collections
import functools
import logging
import typing
from pathlib import Path

from lxml import etree

from odoo import tools

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    type Validator = Callable[..., bool]

_logger = logging.getLogger(__name__)


_validators: collections.defaultdict[str, list[Validator]] = collections.defaultdict(
    list
)
_relaxng_cache: dict[str, etree.RelaxNG | None] = {}

IGNORED_IN_EXPRESSION = {
    "True",
    "False",
    "None",
    "self",
    "uid",
    "context",
    "context_today",
    "allowed_company_ids",
    "current_company_id",
    "time",
    "datetime",
    "relativedelta",
    "current_date",
    "today",
    "now",
    "abs",
    "len",
    "bool",
    "float",
    "str",
    "set",
}


@functools.cache
def domain_operators() -> frozenset[str]:
    import odoo.orm.domain as domains

    return frozenset(
        {
            domains.DomainNot.OPERATOR,
            domains.DomainAnd.OPERATOR,
            domains.DomainOr.OPERATOR,
        }
    )


def _filter_contextual_names(contextual_values: set[str]) -> set[str]:
    value_names = set()
    for name in contextual_values:
        if name == "parent":
            continue
        root = name.split(".")[0]
        if root not in IGNORED_IN_EXPRESSION:
            value_names.add(name if root == "parent" else root)
    return value_names


_NESTED_DOMAIN_NODES = (ast.List, ast.IfExp, ast.BoolOp, ast.BinOp)


def _extract_domain_operand(
    node: ast.AST, contextual_values: set[str], field_names: set[str]
) -> None:
    if isinstance(node, _NESTED_DOMAIN_NODES):
        _extract_from_domain(node, contextual_values, field_names)
    else:
        contextual_values.update(_get_expression_contextual_values(node))


def _extract_domain_leaf(
    ast_item: ast.AST, contextual_values: set[str], field_names: set[str]
) -> None:
    if isinstance(ast_item, ast.Constant):
        if ast_item.value not in domain_operators() and ast_item.value not in (
            True,
            False,
        ):
            raise ValueError
        return
    if not isinstance(ast_item, (ast.List, ast.Tuple)):
        raise ValueError

    left, _operator, right = ast_item.elts
    contextual_values.update(_get_expression_contextual_values(right))
    if isinstance(left, ast.Constant) and isinstance(left.value, str):
        field_names.add(left.value)
    elif isinstance(left, ast.Constant) and left.value in (1, 0):
        pass
    elif isinstance(right, ast.Constant) and right.value == 1:
        contextual_values.update(_get_expression_contextual_values(left))
    else:
        raise ValueError


def _extract_from_domain(
    ast_domain: ast.AST, contextual_values: set[str], field_names: set[str]
) -> None:
    if isinstance(ast_domain, ast.IfExp):
        _extract_from_domain(ast_domain.body, contextual_values, field_names)
        _extract_from_domain(ast_domain.orelse, contextual_values, field_names)
        return
    if isinstance(ast_domain, ast.BoolOp):
        for value in ast_domain.values:
            _extract_domain_operand(value, contextual_values, field_names)
        return
    if isinstance(ast_domain, ast.BinOp):
        _extract_domain_operand(ast_domain.left, contextual_values, field_names)
        _extract_domain_operand(ast_domain.right, contextual_values, field_names)
        return
    if not isinstance(ast_domain, (ast.List, ast.Tuple)):
        raise ValueError
    for ast_item in ast_domain.elts:
        _extract_domain_leaf(ast_item, contextual_values, field_names)


def _extract_domain_list(domain: list, field_names: set[str]) -> None:
    for leaf in domain:
        if leaf in domain_operators() or leaf in (True, False):
            continue
        left, _operator, _right = leaf
        if isinstance(left, str):
            field_names.add(left)
        elif left not in (1, 0):
            raise ValueError


def get_domain_value_names(domain: list | str) -> tuple[set[str], set[str]]:
    contextual_values: set[str] = set()
    field_names: set[str] = set()

    try:
        if isinstance(domain, list):
            _extract_domain_list(domain, field_names)
        elif isinstance(domain, str):
            item_ast = ast.parse(f"({domain.strip()})", mode="eval").body
            if isinstance(item_ast, ast.Name):
                contextual_values.update(_get_expression_contextual_values(item_ast))
            else:
                _extract_from_domain(item_ast, contextual_values, field_names)

    except ValueError, TypeError, AttributeError:
        msg = "Wrong domain formatting."
        raise ValueError(msg) from None

    return field_names, _filter_contextual_names(contextual_values)


def _contextual_values_of(*nodes: ast.AST | None) -> set[str]:
    values: set[str] = set()
    for node in nodes:
        if node is not None:
            values |= _get_expression_contextual_values(node)
    return values


_CONTEXTUAL_CHILDREN: dict[type, Callable[[typing.Any], tuple]] = {
    ast.List: lambda n: tuple(n.elts),
    ast.Tuple: lambda n: tuple(n.elts),
    # ast.Slice, not ast.Index. Index was the pre-3.9 wrapper and the parser has
    # not produced one since -- ast.Index.__new__ returns its argument, so
    # nothing is ever an instance of it and the entry could not fire. Its
    # replacement was never added, which left Subscript half-supported: `a[b]`
    # resolved and `a[b:c]` raised "Unsupported expression: Slice", surfacing as
    # "Wrong domain formatting." _contextual_values_of skips the None bounds.
    ast.Slice: lambda n: (n.lower, n.upper, n.step),
    ast.Subscript: lambda n: (n.value, n.slice),
    ast.Compare: lambda n: (n.left, *n.comparators),
    ast.BinOp: lambda n: (n.left, n.right),
    ast.BoolOp: lambda n: tuple(n.values),
    ast.UnaryOp: lambda n: (n.operand,),
    ast.Call: lambda n: (n.func, *n.args),
    ast.IfExp: lambda n: (n.test, n.body, n.orelse),
    ast.Dict: lambda n: (*n.keys, *n.values),
}


def _get_expression_contextual_values(item_ast: ast.AST) -> set[str]:
    if isinstance(item_ast, ast.Constant):
        return set()
    if isinstance(item_ast, ast.Name):
        return {item_ast.id}
    if isinstance(item_ast, ast.Attribute):
        values = _get_expression_contextual_values(item_ast.value)
        if len(values) == 1:
            return {f"{sorted(values).pop()}.{item_ast.attr}"}
        return values

    # Exact type only: there are no subclass relationships among the keys above,
    # so the isinstance sweep that used to follow this lookup could never match
    # anything the lookup missed.
    children = _CONTEXTUAL_CHILDREN.get(type(item_ast))
    if children is None:
        raise ValueError(f"Unsupported expression: {type(item_ast).__name__}.")
    return _contextual_values_of(*children(item_ast))


def get_expression_field_names(expression: str) -> set[str]:
    if not expression:
        return set()
    item_ast = ast.parse(expression.strip(), mode="eval").body
    contextual_values = _get_expression_contextual_values(item_ast)
    return _filter_contextual_names(contextual_values)


def get_dict_asts(expr: str | ast.AST) -> dict[str, ast.AST]:
    if isinstance(expr, str):
        expr = ast.parse(expr.strip(), mode="eval").body

    if not isinstance(expr, ast.Dict):
        msg = "Non-dict expression"
        raise ValueError(msg)
    # the comprehension below used to repeat this predicate as a filter, which
    # could not drop anything the raise has not already stopped
    if not all(
        (isinstance(key, ast.Constant) and isinstance(key.value, str))
        for key in expr.keys
    ):
        msg = "Non-string literal dict key"
        raise ValueError(msg)
    return {
        key.value: val  # type: ignore[union-attr]
        for key, val in zip(expr.keys, expr.values, strict=False)
    }


def valid_view(arch: etree._Element, **kwargs: object) -> bool:
    for pred in _validators.get(arch.tag, ()):
        if not pred(arch, **kwargs):
            _logger.warning(
                "Invalid XML for view type %r: %s",
                arch.tag,
                pred.__doc__ or pred.__name__,
            )
            return False
    return True


def validate(*view_types: str) -> Callable[[Validator], Validator]:
    def decorator(fn: Validator) -> Validator:
        for arch in view_types:
            _validators[arch].append(fn)
        return fn

    return decorator


def relaxng(view_type: str) -> etree.RelaxNG | None:
    if view_type not in _relaxng_cache:
        with tools.file_open(str(Path("base", "rng", f"{view_type}_view.rng"))) as frng:
            try:
                relaxng_doc = etree.parse(frng)
                _relaxng_cache[view_type] = etree.RelaxNG(relaxng_doc)
            except Exception:
                _logger.exception(
                    "Failed to load RelaxNG XML schema for views validation"
                )
                _relaxng_cache[view_type] = None
    return _relaxng_cache[view_type]


@validate("calendar", "graph", "pivot", "search", "list", "activity")
def schema_valid(arch, **kwargs):
    validator = relaxng(arch.tag)
    if validator and not validator.validate(arch):
        for error in validator.error_log:
            _logger.warning("%s", error)
        return False
    return True


def att_names(name):
    yield name
    yield f"t-att-{name}"
    yield f"t-attf-{name}"


def check_dropdown_menu(node):
    warnings = []
    if any("dropdown-menu" in node.get(cl, "") for cl in att_names("class")):
        if node.get("role") != "menu":
            warnings.append("dropdown-menu class must have menu role")
    return warnings


def check_progress_bar(node):
    warnings = []
    if any("o_progressbar" in node.get(cl, "") for cl in att_names("class")):
        if node.get("role") != "progressbar":
            warnings.append("o_progressbar class must have progressbar role")
        if not any(node.get(at) for at in att_names("aria-valuenow")):
            warnings.append("o_progressbar class must have aria-valuenow attribute")
        if not any(node.get(at) for at in att_names("aria-valuemin")):
            warnings.append("o_progressbar class must have aria-valuemin attribute")
        if not any(node.get(at) for at in att_names("aria-valuemax")):
            warnings.append("o_progressbar class must have aria-valuemax attribute")
    return warnings


def check_fa_class_accessibility(node, description):
    valid_aria_attrs = {
        *att_names("title"),
        *att_names("aria-label"),
        *att_names("aria-labelledby"),
    }
    valid_t_attrs = {"t-value", "t-raw", "t-field", "t-esc", "t-out"}

    # getparent() is None for the arch root, and a root element carries a class
    # like any other: `<form class="fa-star">` reached here through
    # ir.ui.view._check_attr_class and raised AttributeError out of create().
    # Every other traversal in this function is already None-safe.
    parent = node.getparent()
    if (node.tail or "").strip() or (
        parent is not None and (parent.text or "").strip()
    ):
        return []

    def has_text(elem):
        if elem is None:
            return False
        if elem.tag == "span" and elem.text:
            return True
        if elem.tag in ["field", "label"] and elem.get("string"):
            return True
        return bool(elem.tag == "t" and (elem.get("t-esc") or elem.get("t-raw")))

    if has_text(node.getnext()) or has_text(node.getprevious()):
        return []

    def has_title_or_aria_label(node):
        return any(node.get(attr) for attr in valid_aria_attrs)

    if any(map(has_title_or_aria_label, node.iterancestors())):
        return []

    if node.get("string"):
        return []

    def contains_description(node, depth=0):
        if any(node.get(attr) for attr in valid_t_attrs):
            return True
        if has_title_or_aria_label(node):
            return True
        if node.tag in ("label", "field"):
            return True
        if node.text:
            return True
        return any(contains_description(child, depth + 1) for child in node)

    if contains_description(node):
        return []

    return [
        "%s must have title in its tag, parents, descendants or have text" % description
    ]


def check_class_accessibility(node, expr):
    warnings = []
    classes = set(expr.split(" "))
    if "modal" in classes and node.get("role") != "dialog":
        warnings.append('"modal" class should only be used with "dialog" role')
    if "modal-header" in classes and node.tag != "header":
        warnings.append('"modal-header" class should only be used in "header" tag')
    if "modal-body" in classes and node.tag != "main":
        warnings.append('"modal-body" class should only be used in "main" tag')
    if "modal-footer" in classes and node.tag != "footer":
        warnings.append('"modal-footer" class should only be used in "footer" tag')
    if "tab-pane" in classes and node.get("role") != "tabpanel":
        warnings.append('"tab-pane" class should only be used with "tabpanel" role')
    if "nav-tabs" in classes and node.get("role") != "tablist":
        warnings.append('A tab list with class nav-tabs must have role="tablist"')
    if any(klass.startswith("alert-") for klass in classes):
        if (
            node.get("role") not in ("alert", "alertdialog", "status")
            and "alert-link" not in classes
        ):
            warnings.append(
                "An alert (class alert-*) must have an alert, alertdialog or "
                "status role or an alert-link class. Please use alert and "
                "alertdialog only for what expects to stop any activity to "
                "be read immediately."
            )
    if any(klass.startswith("fa-") for klass in classes):
        description = f"A <{node.tag}> with fa class ({expr})"
        warnings += check_fa_class_accessibility(node, description)
    if any(klass.startswith("btn") for klass in classes):
        if (
            node.tag in ("a", "button", "select")
            or (
                node.tag == "input"
                and node.get("type") in ("button", "submit", "reset")
            )
            or any(
                klass in classes for klass in ("btn-group", "btn-toolbar", "btn-addr")
            )
            or (node.tag == "field" and node.get("widget") == "url")
        ):
            pass
        else:
            warnings.append(
                "A simili button must be in tag a/button/select or tag `input` "
                "with type button/submit/reset or have class in "
                "btn-group/btn-toolbar/btn-addr"
            )
    return warnings
