"""View validation: assertion-based checks plus RelaxNG schema validation."""

import ast
import collections
import logging
from pathlib import Path

from lxml import etree

import odoo.orm.domain as domains
from odoo import tools

_logger = logging.getLogger(__name__)


_validators = collections.defaultdict(list)
_relaxng_cache = {}

# predefined symbols for evaluating attributes (invisible, readonly...)
IGNORED_IN_EXPRESSION = {
    "True",
    "False",
    "None",  # included for completeness alongside True and False
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
DOMAIN_OPERATORS = {
    domains.DomainNot.OPERATOR,
    domains.DomainAnd.OPERATOR,
    domains.DomainOr.OPERATOR,
}


def _filter_contextual_names(contextual_values: set[str]) -> set[str]:
    """Filter contextual value names down to reportable value names.

    Drops the bare ``parent`` reference and any name whose root is a
    predefined evaluation symbol (``IGNORED_IN_EXPRESSION``); ``parent.*``
    paths are kept whole while other names are reduced to their root.
    """
    value_names = set()
    for name in contextual_values:
        if name == "parent":
            continue
        root = name.split(".")[0]
        if root not in IGNORED_IN_EXPRESSION:
            value_names.add(name if root == "parent" else root)
    return value_names


def get_domain_value_names(domain: list | str) -> tuple[set[str], set[str]]:
    """Return the field names and contextual value names used by this domain.

    Contextual roots listed in ``IGNORED_IN_EXPRESSION`` (``context``, ``uid``,
    builtins, ...) are excluded from the second set.

    eg (string domain): '''[
            ('id', 'in', [1, 2, 3]),
            ('field_a', 'in', parent.truc),
            ('field_b', 'in', context.get('b')),
        ]'''
        returns {'id', 'field_a', 'field_b'}, {'parent.truc'}

    :param domain: list(tuple) or str
    :return: set(str), set(str)
    """
    contextual_values = set()
    field_names = set()

    try:
        if isinstance(domain, list):
            for leaf in domain:
                if leaf in DOMAIN_OPERATORS or leaf in (True, False):
                    # "&", "|", "!", True, False
                    continue
                left, _operator, _right = leaf
                if isinstance(left, str):
                    field_names.add(left)
                elif left not in (1, 0):
                    # deprecate: True leaf and False leaf
                    raise ValueError

        elif isinstance(domain, str):

            def extract_from_domain(ast_domain):
                if isinstance(ast_domain, ast.IfExp):
                    # [] if condition else []
                    extract_from_domain(ast_domain.body)
                    extract_from_domain(ast_domain.orelse)
                    return
                if isinstance(ast_domain, ast.BoolOp):
                    # condition and []
                    # this formating don't check returned domain syntax
                    for value in ast_domain.values:
                        if isinstance(
                            value, (ast.List, ast.IfExp, ast.BoolOp, ast.BinOp)
                        ):
                            extract_from_domain(value)
                        else:
                            contextual_values.update(
                                _get_expression_contextual_values(value)
                            )
                    return
                if isinstance(ast_domain, ast.BinOp):
                    # [] + []
                    # this formating don't check returned domain syntax
                    if isinstance(
                        ast_domain.left,
                        (ast.List, ast.IfExp, ast.BoolOp, ast.BinOp),
                    ):
                        extract_from_domain(ast_domain.left)
                    else:
                        contextual_values.update(
                            _get_expression_contextual_values(ast_domain.left)
                        )

                    if isinstance(
                        ast_domain.right,
                        (ast.List, ast.IfExp, ast.BoolOp, ast.BinOp),
                    ):
                        extract_from_domain(ast_domain.right)
                    else:
                        contextual_values.update(
                            _get_expression_contextual_values(ast_domain.right)
                        )
                    return
                for ast_item in ast_domain.elts:
                    if isinstance(ast_item, ast.Constant):
                        # "&", "|", "!", True, False
                        if (
                            ast_item.value not in DOMAIN_OPERATORS
                            and ast_item.value not in (True, False)
                        ):
                            raise ValueError
                    elif isinstance(ast_item, (ast.List, ast.Tuple)):
                        left, _operator, right = ast_item.elts
                        contextual_values.update(
                            _get_expression_contextual_values(right)
                        )
                        if isinstance(left, ast.Constant) and isinstance(
                            left.value, str
                        ):
                            field_names.add(left.value)
                        elif isinstance(left, ast.Constant) and left.value in (
                            1,
                            0,
                        ):
                            # deprecate: True leaf (1, '=', 1) and False leaf (0, '=', 1)
                            pass
                        elif isinstance(right, ast.Constant) and right.value == 1:
                            # deprecate: True/False leaf (py expression, '=', 1)
                            contextual_values.update(
                                _get_expression_contextual_values(left)
                            )
                        else:
                            raise ValueError
                    else:
                        raise ValueError

            expr = domain.strip()
            item_ast = ast.parse(f"({expr})", mode="eval").body
            if isinstance(item_ast, ast.Name):
                # domain="other_field_domain"
                contextual_values.update(_get_expression_contextual_values(item_ast))
            else:
                extract_from_domain(item_ast)

    # TypeError/AttributeError cover malformed leaves and unhandled AST node
    # types (e.g. "foo()", "{'a': 1}", [None]) so callers get the documented
    # ValueError instead of a raw 500.
    except ValueError, TypeError, AttributeError:
        msg = "Wrong domain formatting."
        raise ValueError(msg) from None

    return field_names, _filter_contextual_names(contextual_values)


def _get_expression_contextual_values(item_ast: ast.AST) -> set[str]:
    """Return the contextual value names referenced in this AST node.

    eg: ast from '''(
            id in [1, 2, 3]
            and field_a in parent.truc
            and field_b in context.get('b')
            or (
                True
                and bool(context.get('c'))
            )
        )
        returns {'id', 'field_a', 'parent.truc', 'field_b', 'context.get', 'bool'}

    :param item_ast: ast
    :return: set(str)
    """

    if isinstance(item_ast, ast.Constant):
        return set()
    if isinstance(item_ast, (ast.List, ast.Tuple)):
        values = set()
        for item in item_ast.elts:
            values |= _get_expression_contextual_values(item)
        return values
    if isinstance(item_ast, ast.Name):
        return {item_ast.id}
    if isinstance(item_ast, ast.Attribute):
        values = _get_expression_contextual_values(item_ast.value)
        if len(values) == 1:
            path = sorted(values).pop()
            return {f"{path}.{item_ast.attr}"}
        return values
    if isinstance(item_ast, ast.Index):  # deprecated python ast class for Subscript key
        return _get_expression_contextual_values(item_ast.value)
    if isinstance(item_ast, ast.Subscript):
        values = _get_expression_contextual_values(item_ast.value)
        values |= _get_expression_contextual_values(item_ast.slice)
        return values
    if isinstance(item_ast, ast.Compare):
        values = _get_expression_contextual_values(item_ast.left)
        for sub_ast in item_ast.comparators:
            values |= _get_expression_contextual_values(sub_ast)
        return values
    if isinstance(item_ast, ast.BinOp):
        values = _get_expression_contextual_values(item_ast.left)
        values |= _get_expression_contextual_values(item_ast.right)
        return values
    if isinstance(item_ast, ast.BoolOp):
        values = set()
        for ast_value in item_ast.values:
            values |= _get_expression_contextual_values(ast_value)
        return values
    if isinstance(item_ast, ast.UnaryOp):
        return _get_expression_contextual_values(item_ast.operand)
    if isinstance(item_ast, ast.Call):
        values = _get_expression_contextual_values(item_ast.func)
        for ast_arg in item_ast.args:
            values |= _get_expression_contextual_values(ast_arg)
        return values
    if isinstance(item_ast, ast.IfExp):
        values = _get_expression_contextual_values(item_ast.test)
        values |= _get_expression_contextual_values(item_ast.body)
        values |= _get_expression_contextual_values(item_ast.orelse)
        return values
    if isinstance(item_ast, ast.Dict):
        values = set()
        for item in item_ast.keys:
            values |= _get_expression_contextual_values(item)
        for item in item_ast.values:
            values |= _get_expression_contextual_values(item)
        return values

    raise ValueError(f"Undefined item {item_ast!r}.")


def get_expression_field_names(expression: str) -> set[str]:
    """Return all field names used by this expression.

    Contextual roots listed in ``IGNORED_IN_EXPRESSION`` (``context``, builtins,
    ...) are excluded.

    eg: expression = '''(
            id in [1, 2, 3]
            and field_a in parent.truc.id
            and field_b in context.get('b')
            or (True and bool(context.get('c')))
        )'''
        returns {'id', 'field_a', 'field_b', 'parent.truc.id'}

    :param expression: str
    :return: set(str)
    """
    if not expression:
        return set()
    item_ast = ast.parse(expression.strip(), mode="eval").body
    contextual_values = _get_expression_contextual_values(item_ast)
    return _filter_contextual_names(contextual_values)


def get_dict_asts(expr: str | ast.AST) -> dict[str, ast.AST]:
    """Check that the given string or AST node represents a dict expression
    where all keys are string literals, and return it as a dict mapping string
    keys to the AST of values.
    """
    if isinstance(expr, str):
        expr = ast.parse(expr.strip(), mode="eval").body

    if not isinstance(expr, ast.Dict):
        msg = "Non-dict expression"
        raise ValueError(msg)
    if not all(
        (isinstance(key, ast.Constant) and isinstance(key.value, str))
        for key in expr.keys
    ):
        msg = "Non-string literal dict key"
        raise ValueError(msg)
    return {key.value: val for key, val in zip(expr.keys, expr.values, strict=False)}


def valid_view(arch: etree._Element, **kwargs: object) -> bool:
    for pred in _validators[arch.tag]:
        check = pred(arch, **kwargs)
        if not check:
            _logger.warning("Invalid XML: %s", pred.__doc__)
            return False
    return True


def validate(*view_types: str) -> object:
    """Register a view-validation function for the given view types."""

    def decorator(fn):
        for arch in view_types:
            _validators[arch].append(fn)
        return fn

    return decorator


def relaxng(view_type: str) -> etree.RelaxNG | None:
    """Return a validator for the given view type, or None."""
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
    """Validate ``arch`` against its RelaxNG schema, logging any errors."""
    validator = relaxng(arch.tag)
    if validator and not validator.validate(arch):
        for error in validator.error_log:
            _logger.warning("%s", error)
        return False
    return True


# ---------------------------------------------------------------------------
# Accessibility / markup checks (pure, DB-free)
#
# Each returns a list of human-readable warning messages for a single arch
# node, so they can be unit-tested without an ir.ui.view record or an
# environment. ir.ui.view wraps every call with _log_view_warning() to attach
# the offending view's error context.
# ---------------------------------------------------------------------------


def att_names(name):
    """Yield an attribute name and its ``t-att-``/``t-attf-`` dynamic variants."""
    yield name
    yield f"t-att-{name}"
    yield f"t-attf-{name}"


def check_dropdown_menu(node):
    """Return accessibility warnings for a ``dropdown-menu`` node."""
    warnings = []
    if any("dropdown-menu" in node.get(cl, "") for cl in att_names("class")):
        if node.get("role") != "menu":
            warnings.append("dropdown-menu class must have menu role")
    return warnings


def check_progress_bar(node):
    """Return accessibility warnings for an ``o_progressbar`` node."""
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
    """Return a 0- or 1-element list of warnings for a Font Awesome node that
    lacks an accessible text alternative (in itself, a sibling, an ancestor or
    a descendant).
    """
    valid_aria_attrs = {
        *att_names("title"),
        *att_names("aria-label"),
        *att_names("aria-labelledby"),
    }
    valid_t_attrs = {"t-value", "t-raw", "t-field", "t-esc", "t-out"}

    ## Following or preceding text
    if (node.tail or "").strip() or (node.getparent().text or "").strip():
        # text<i class="fa-..."/> or <i class="fa-..."/>text
        return []

    ## Following or preceding text in span
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

    ## Aria label can be on ancestors
    if any(map(has_title_or_aria_label, node.iterancestors())):
        return []

    if node.get("string"):
        return []

    ## And we ignore all elements with describing in children
    def contains_description(node, depth=0):
        if depth > 2:
            _logger.warning("excessive depth in fa")
        if any(node.get(attr) for attr in valid_t_attrs):
            return True
        if has_title_or_aria_label(node):
            return True
        if node.tag in ("label", "field"):
            return True
        if node.text:  # not sure, does it match *[text()]
            return True
        return any(contains_description(child, depth + 1) for child in node)

    if contains_description(node):
        return []

    return [
        "%s must have title in its tag, parents, descendants or have text" % description
    ]


def check_class_accessibility(node, expr):
    """Return accessibility warnings for the classes in ``expr`` on ``node``.

    ``expr`` is the raw ``class`` attribute value, which may be a dynamic
    ``t-attf-class`` expression, hence the best-effort whitespace splitting.
    Font Awesome findings are appended before the button findings, preserving
    the original emission order.
    """
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
