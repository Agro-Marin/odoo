"""Restricted alternatives to eval() for simple and/or untrusted code.

Used to parse Odoo domain strings, conditions and expressions, mostly built on
locals plus condition/math builtins.
"""

import ast
import dis
import functools
import logging
import string
import sys
import types
import typing
from opcode import opmap, opname
from types import CodeType

import werkzeug
from psycopg import OperationalError

import odoo.exceptions

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

unsafe_eval = eval

__all__ = ["const_eval", "expr_eval", "safe_eval"]

_ALLOWED_MODULES = ["_strptime", "math", "time"]


def _import(
    name: str,
    globals: dict | None = None,
    locals: dict | None = None,
    fromlist: list[str] | None = None,
    level: int = -1,
) -> None:
    if name not in sys.modules:
        raise ImportError(
            f"module {name} should be imported before calling safe_eval()"
        )


for module in _ALLOWED_MODULES:
    __import__(module)


_UNSAFE_ATTRIBUTES = [
    "f_builtins",
    "f_code",
    "f_globals",
    "f_locals",
    "f_generator",
    "func_code",
    "func_globals",
    "co_code",
    "_co_code_adaptive",
    "mro",
    "tb_frame",
    "gi_code",
    "gi_frame",
    "gi_yieldfrom",
    "cr_await",
    "cr_code",
    "cr_frame",
    "ag_await",
    "ag_code",
    "ag_frame",
]


def to_opcodes(opnames: list[str], _opmap: dict[str, int] = opmap) -> Iterator[int]:
    """Map opcode *names* to numbers, silently dropping ones this Python lacks.

    Dropping is right for the *allow* lists: an entry naming an opcode that no
    longer exists simply allows nothing, and CPython renames opcodes freely
    between versions. It is wrong for :data:`_BLACKLIST`, which is why that one
    goes through :func:`to_required_opcodes` instead.
    """
    for x in opnames:
        if x in _opmap:
            yield _opmap[x]


def to_required_opcodes(
    opnames: list[str], _opmap: dict[str, int] = opmap
) -> Iterator[int]:
    """Map opcode names to numbers, raising if any does not exist.

    For lists where a missing name silently *weakens* the check. ``_BLACKLIST``
    is the whole of the "these operations are forbidden" contract, and
    :func:`to_opcodes` would drop a renamed entry without a word — the guard
    would keep passing while no longer guarding. A CPython upgrade that renames
    ``IMPORT_NAME`` should fail at import, loudly, not quietly stop rejecting
    imports.
    """
    for x in opnames:
        if x not in _opmap:
            msg = (
                f"safe_eval blacklists opcode {x!r}, which does not exist on "
                f"Python {sys.version_info.major}.{sys.version_info.minor}. "
                f"Re-derive the blacklist against this interpreter: silently "
                f"dropping it would weaken the sandbox."
            )
            raise RuntimeError(msg)
        yield _opmap[x]


#: Operations no restricted expression may perform, whatever the mode.
#:
#: ``IMPORT_STAR`` used to head this list and was removed when it stopped
#: existing: CPython 3.12 replaced the dedicated opcode with
#: ``CALL_INTRINSIC_1(INTRINSIC_IMPORT_STAR)``. ``to_opcodes`` had been dropping
#: it silently ever since, so the list *read* as seven entries and *was* six.
#: Nothing was actually permitted by that — ``from x import *`` still emits
#: ``IMPORT_NAME`` first, and that is blocked — but the discrepancy was
#: invisible, which is what :func:`to_required_opcodes` now prevents.
_BLACKLIST = frozenset(
    to_required_opcodes(
        [
            "IMPORT_NAME",
            "IMPORT_FROM",
            "STORE_ATTR",
            "DELETE_ATTR",
            "STORE_GLOBAL",
            "DELETE_GLOBAL",
        ]
    )
)
_CONST_OPCODES = (
    frozenset(
        to_opcodes(
            [
                "POP_TOP",
                "ROT_TWO",
                "ROT_THREE",
                "ROT_FOUR",
                "DUP_TOP",
                "DUP_TOP_TWO",
                "LOAD_CONST",
                "RETURN_VALUE",
                "BUILD_LIST",
                "BUILD_MAP",
                "BUILD_TUPLE",
                "BUILD_SET",
                "BUILD_CONST_KEY_MAP",
                "LIST_EXTEND",
                "SET_UPDATE",
                "COPY",
                "SWAP",
                "RESUME",
                "RETURN_CONST",
                "TO_BOOL",
                "LOAD_SMALL_INT",
                "NOT_TAKEN",
            ]
        )
    )
    - _BLACKLIST
)

_operations = [
    "POWER",
    "MULTIPLY",
    "FLOOR_DIVIDE",
    "TRUE_DIVIDE",
    "MODULO",
    "ADD",
    "SUBTRACT",
    "LSHIFT",
    "RSHIFT",
    "AND",
    "XOR",
    "OR",
]
_EXPR_OPCODES = (
    _CONST_OPCODES.union(
        to_opcodes(
            [
                "UNARY_POSITIVE",
                "UNARY_NEGATIVE",
                "UNARY_NOT",
                "UNARY_INVERT",
                *("BINARY_" + op for op in _operations),
                "BINARY_SUBSCR",
                *("INPLACE_" + op for op in _operations),
                "BUILD_SLICE",
                "LIST_APPEND",
                "MAP_ADD",
                "SET_ADD",
                "COMPARE_OP",
                "IS_OP",
                "CONTAINS_OP",
                "DICT_MERGE",
                "DICT_UPDATE",
                "GEN_START",
                "BINARY_OP",
                "BINARY_SLICE",
            ]
        )
    )
    - _BLACKLIST
)

_SAFE_OPCODES = (
    _EXPR_OPCODES.union(
        to_opcodes(
            [
                "POP_BLOCK",
                "POP_EXCEPT",
                "SETUP_LOOP",
                "SETUP_EXCEPT",
                "BREAK_LOOP",
                "CONTINUE_LOOP",
                "EXTENDED_ARG",
                "MAKE_FUNCTION",
                "CALL_FUNCTION",
                "CALL_FUNCTION_KW",
                "CALL_FUNCTION_EX",
                "CALL_METHOD",
                "LOAD_METHOD",
                "GET_ITER",
                "FOR_ITER",
                "YIELD_VALUE",
                "JUMP_FORWARD",
                "JUMP_ABSOLUTE",
                "JUMP_BACKWARD",
                "JUMP_IF_FALSE_OR_POP",
                "JUMP_IF_TRUE_OR_POP",
                "POP_JUMP_IF_FALSE",
                "POP_JUMP_IF_TRUE",
                "SETUP_FINALLY",
                "END_FINALLY",
                "BEGIN_FINALLY",
                "CALL_FINALLY",
                "POP_FINALLY",
                "RAISE_VARARGS",
                "LOAD_NAME",
                "STORE_NAME",
                "DELETE_NAME",
                "LOAD_ATTR",
                "LOAD_FAST",
                "STORE_FAST",
                "DELETE_FAST",
                "UNPACK_SEQUENCE",
                "UNPACK_EX",
                "STORE_SUBSCR",
                "DELETE_SUBSCR",
                "LOAD_GLOBAL",
                "RERAISE",
                "JUMP_IF_NOT_EXC_MATCH",
                "PUSH_NULL",
                "PRECALL",
                "CALL",
                "KW_NAMES",
                "POP_JUMP_FORWARD_IF_FALSE",
                "POP_JUMP_FORWARD_IF_TRUE",
                "POP_JUMP_BACKWARD_IF_FALSE",
                "POP_JUMP_BACKWARD_IF_TRUE",
                "POP_JUMP_FORWARD_IF_NONE",
                "POP_JUMP_BACKWARD_IF_NONE",
                "POP_JUMP_FORWARD_IF_NOT_NONE",
                "POP_JUMP_BACKWARD_IF_NOT_NONE",
                "CHECK_EXC_MATCH",
                "RETURN_GENERATOR",
                "PUSH_EXC_INFO",
                "NOP",
                "FORMAT_VALUE",
                "BUILD_STRING",
                "END_FOR",
                "LOAD_FAST_AND_CLEAR",
                "LOAD_FAST_CHECK",
                "POP_JUMP_IF_NOT_NONE",
                "POP_JUMP_IF_NONE",
                "CALL_INTRINSIC_1",
                "STORE_SLICE",
                "CALL_KW",
                "LOAD_FAST_LOAD_FAST",
                "STORE_FAST_STORE_FAST",
                "STORE_FAST_LOAD_FAST",
                "CONVERT_VALUE",
                "FORMAT_SIMPLE",
                "FORMAT_WITH_SPEC",
                "SET_FUNCTION_ATTRIBUTE",
                "LOAD_FAST_BORROW",
                "POP_ITER",
                "LOAD_FAST_BORROW_LOAD_FAST_BORROW",
                "LOAD_COMMON_CONSTANT",
                "JUMP_BACKWARD_NO_INTERRUPT",
                "SEND",
                "END_SEND",
                "CLEANUP_THROW",
                "GET_YIELD_FROM_ITER",
                "MAKE_CELL",
                "COPY_FREE_VARS",
                "LOAD_CLOSURE",
                "LOAD_DEREF",
                "STORE_DEREF",
                "DELETE_DEREF",
            ]
        )
    )
    - _BLACKLIST
)


_logger = logging.getLogger(__name__)

_validated_bytecode_cache: dict[tuple, bool] = {}
_VALIDATED_CACHE_MAX = 8192


def assert_no_dunder_name(code_obj: CodeType, expr: str) -> None:
    """Assert the code object refers to no name containing two underscores.

    This blocks dunder names (``__name__``) and thus access to internal-ish
    Python attributes/methods, which are loaded via LOAD_ATTR by name (in
    co_names), not as a const or var.

    ``co_freevars``/``co_cellvars`` are checked alongside ``co_names`` because a
    closure cell is read by *index* (LOAD_DEREF), not by name, so a cell called
    ``__class__`` would never appear in ``co_names`` and would slip past a
    co_names-only check.  CPython creates exactly such an implicit ``__class__``
    cell for any method that mentions ``__class__`` or ``super()``.  Class
    bodies are unreachable today (LOAD_BUILD_CLASS is not in the allowlist), so
    this is defence-in-depth guarding the closure opcodes rather than a live
    hole -- but it is what makes allowing those opcodes safe by construction
    instead of safe by accident.

    :param code_obj: code object to name-validate
    :type code_obj: CodeType
    :param str expr: expression for the code object, for debugging
    :raises NameError: a forbidden name (a dunder or unsafe attribute) is found
    """
    for name in (*code_obj.co_names, *code_obj.co_freevars, *code_obj.co_cellvars):
        if "__" in name or name in _UNSAFE_ATTRIBUTES:
            raise NameError("Access to forbidden name %r (%r)" % (name, expr))


_formatter_parse = string.Formatter().parse


def assert_no_dunder_format_field(code_obj: CodeType, expr: str) -> None:
    """Reject literal ``str.format``/``str.format_map`` templates whose
    replacement fields navigate dunder attributes or items.

    ``"{0.__class__}".format(x)`` and ``"{0.__globals__[k]}".format_map(d)``
    reach ``x.__class__`` / a module's globals through the format machinery,
    which resolves those field names at *runtime*.  They never appear in
    ``co_names``, so ``assert_no_dunder_name`` cannot see them — a sandbox
    escape reaching ``object`` and, via any function/recordset in the context,
    ``__globals__`` (env vars, DB credentials).

    Scope — this is best-effort defence-in-depth, not an airtight barrier:
    it inspects string *constants*, so it catches the literal exploit (and the
    constant-folded ``"{0.__" "class__}"`` form), but a format string assembled
    at runtime (``("{0.%sclass__}" % "__").format(x)``, or one passed in through
    a context variable) still slips through. Fully closing the hole means
    blocking the ``format``/``format_map`` methods outright, which cannot be done
    here: they are public model methods (``res.currency.format``,
    ``res.lang.format``) that customer templates and server actions call, so a
    name-level block would break legitimate code. Upstream applies no mitigation
    at all; this raises the bar for the common case without any false positives.

    Gated on a ``format``/``format_map`` name being present so that ordinary
    strings containing braces (and model methods also named ``format``) are
    unaffected: ``getattr`` is not exposed, so ``str.format`` is unreachable
    without the name appearing in co_names.
    """
    if not _FORMAT_METHOD_NAMES.intersection(code_obj.co_names):
        return
    for const in code_obj.co_consts:
        if not isinstance(const, str) or "__" not in const:
            continue
        try:
            fields = [field for _, field, _, _ in _formatter_parse(const) if field]
        except ValueError:
            continue
        if any("__" in field for field in fields):
            raise NameError(
                "Access to forbidden format field in %r (%r)" % (const, expr)
            )


_FORMAT_METHOD_NAMES = frozenset(("format", "format_map"))


class _StrictFormatter(string.Formatter):
    """A :class:`string.Formatter` that forbids attribute navigation in fields.

    ``str.format`` resolves replacement-field names at *runtime*, so
    ``"{0.__globals__[k]}".format(x)`` reaches ``x.__globals__`` — and
    ``"{0.env.cr.dbname}".format(record)`` reaches a live cursor through
    ordinary public attributes. Neither name appears in ``co_names``, so
    :func:`assert_no_dunder_name` never sees it, and
    :func:`assert_no_dunder_format_field` only catches the *constant* literal
    form.  Forbidding attribute access inside the field closes both — the whole
    pivot, not just dunders — while leaving index access, positional/keyword
    fields and format specs (the entire legitimate surface) untouched.
    """

    def get_field(self, field_name, args, kwargs):
        _first, rest = string._string.formatter_field_name_split(field_name)
        for is_attr, key in rest:
            if is_attr:
                raise ValueError(
                    f"attribute access is not allowed in a format field (.{key})"
                )
        return super().get_field(field_name, args, kwargs)


_STRICT_FORMATTER = _StrictFormatter()


class _GuardedStr(str):
    """A ``str`` whose ``format`` / ``format_map`` go through :data:`_STRICT_FORMATTER`."""

    __slots__ = ()

    def format(self, *args, **kwargs):
        # ``self`` is the template; ``vformat`` parses it, it never calls
        # ``self.format`` again, so there is no recursion.
        return _STRICT_FORMATTER.vformat(self, args, kwargs)

    def format_map(self, mapping):
        return _STRICT_FORMATTER.vformat(self, (), mapping)


def _guard_format(recv: typing.Any) -> typing.Any:
    """Wrap ``recv`` so a ``str.format`` reached through it cannot navigate attrs.

    A ``str`` *instance* becomes a :class:`_GuardedStr`; the ``str`` *class*
    itself becomes :class:`_GuardedStr` too, because ``str`` is a safe_eval
    builtin and ``str.format(template, x)`` would otherwise reach the unguarded
    C method. Any other receiver — notably a recordset with its own ``format``
    method (``res.currency``, ``res.lang``) — is returned untouched.
    """
    if type(recv) is str:
        return _GuardedStr(recv)
    if recv is str:
        return _GuardedStr
    return recv


#: The name the AST transform binds the guard to; installed as a builtin so a
#: user expression cannot shadow it with a plain global. Dunder-free (no ``__``
#: anywhere) so it does not trip ``assert_no_dunder_name``.
_GUARD_FORMAT_NAME = "_odoo_guarded_format_receiver"


class _FormatGuardTransform(ast.NodeTransformer):
    """Wrap the *receiver* of every ``.format`` / ``.format_map`` access.

    ``x.format(a, b)`` becomes ``_guard(x).format(a, b)`` — the call arguments
    are left exactly as written, so only which ``format`` runs changes, never
    what it is called with.
    """

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        if node.attr in _FORMAT_METHOD_NAMES:
            node.value = ast.Call(
                func=ast.Name(id=_GUARD_FORMAT_NAME, ctx=ast.Load()),
                args=[node.value],
                keywords=[],
            )
        return node


def assert_valid_codeobj(
    allowed_codes: set[int], code_obj: CodeType, expr: str
) -> None:
    """Assert the code object validates against the bytecode and name constraints.

    Also recurses into code objects nested in co_consts, so lambdas (which get
    their own separate code objects) are validated too.

    :param allowed_codes: permissible bytecode instructions
    :type allowed_codes: set(int)
    :param code_obj: code object to validate
    :type code_obj: CodeType
    :param str expr: expression for the code object, for debugging
    :raises ValueError: forbidden bytecode in ``code_obj``
    :raises NameError: a forbidden name (a dunder or unsafe attribute) is found
    """
    nested_code = [c for c in code_obj.co_consts if isinstance(c, CodeType)]
    cacheable = not nested_code

    cache_key = None
    if cacheable:
        cache_key = (
            code_obj.co_code,
            code_obj.co_names,
            code_obj.co_consts,
            code_obj.co_freevars,
            code_obj.co_cellvars,
            frozenset(allowed_codes),
        )
        if cache_key in _validated_bytecode_cache:
            return

    assert_no_dunder_name(code_obj, expr)
    assert_no_dunder_format_field(code_obj, expr)

    code_codes = {i.opcode for i in dis.get_instructions(code_obj)}
    if not allowed_codes >= code_codes:
        raise ValueError(
            "forbidden opcode(s) in %r: %s"
            % (expr, ", ".join(opname[x] for x in (code_codes - allowed_codes)))
        )

    for const in nested_code:
        assert_valid_codeobj(allowed_codes, const, "lambda")

    if cacheable:
        if len(_validated_bytecode_cache) >= _VALIDATED_CACHE_MAX:
            try:
                oldest = next(iter(_validated_bytecode_cache), None)
            except RuntimeError:
                oldest = None
            if oldest is not None:
                _validated_bytecode_cache.pop(oldest, None)
        _validated_bytecode_cache[cache_key] = True


def compile_codeobj(
    expr: str,
    /,
    filename: str = "<unknown>",
    mode: typing.Literal["eval", "exec"] = "eval",
    guard_format: bool = False,
) -> CodeType:
    """Compile ``expr`` into a code object.

    :param str expr: the source to compile
    :param str filename: optional pseudo-filename for the compiled expression,
                         displayed for example in traceback frames
    :param str mode: 'eval' if single expression
                     'exec' if sequence of statements
    :param bool guard_format: route ``str.format`` / ``format_map`` through the
                         attribute-forbidding :class:`_StrictFormatter` (see
                         :func:`_guard_format`). Set by :func:`safe_eval`; the
                         constant evaluators leave it off so they stay
                         byte-identical. Applied only when ``expr`` mentions
                         ``format`` at all, so format-free expressions compile
                         exactly as before.
    :return: compiled code object
    :rtype: types.CodeType
    """
    assert mode in ("eval", "exec")
    try:
        if mode == "eval":
            expr = expr.strip()
        if guard_format and "format" in expr:
            tree = ast.parse(expr, filename or "", mode)
            _FormatGuardTransform().visit(tree)
            ast.fix_missing_locations(tree)
            code_obj = compile(tree, filename or "", mode)
        else:
            code_obj = compile(expr, filename or "", mode)
    except SyntaxError, TypeError, ValueError:
        raise
    except Exception as e:
        raise ValueError("%r while compiling\n%r" % (e, expr)) from e
    return code_obj


def const_eval(expr: str) -> typing.Any:
    """Safely evaluate a string describing a Python constant.

    Strings that are not valid Python expressions raise SyntaxError; those
    that contain code beyond the constant raise ValueError.

    >>> const_eval("10")
    10
    >>> const_eval("[1,2, (3,4), {'foo':'bar'}]")
    [1, 2, (3, 4), {'foo': 'bar'}]
    >>> const_eval("[1,2]*2")
    Traceback (most recent call last):
    ...
    ValueError: forbidden opcode(s) in '[1,2]*2': BINARY_OP
    """
    c = compile_codeobj(expr)
    assert_valid_codeobj(_CONST_OPCODES, c, expr)
    return unsafe_eval(c)


def expr_eval(expr: str) -> typing.Any:
    """Evaluate a string expression that uses only Python constants.

    Useful e.g. to evaluate a numerical expression from an untrusted source.

    >>> expr_eval("1+2")
    3
    >>> expr_eval("[1,2]*2")
    [1, 2, 1, 2]
    >>> expr_eval("__import__('sys').modules")
    Traceback (most recent call last):
    ...
    NameError: Access to forbidden name '__import__' ("__import__('sys').modules")
    """
    c = compile_codeobj(expr)
    assert_valid_codeobj(_EXPR_OPCODES, c, expr)
    return unsafe_eval(c)


_BUILTINS = {
    "__import__": _import,
    "True": True,
    "False": False,
    "None": None,
    "bytes": bytes,
    "str": str,
    "unicode": str,
    "bool": bool,
    "int": int,
    "float": float,
    "enumerate": enumerate,
    "dict": dict,
    "list": list,
    "tuple": tuple,
    "map": map,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "reduce": functools.reduce,
    "filter": filter,
    "sorted": sorted,
    "round": round,
    "len": len,
    "repr": repr,
    "set": set,
    "all": all,
    "any": any,
    "ord": ord,
    "chr": chr,
    "divmod": divmod,
    "isinstance": isinstance,
    "range": range,
    "xrange": range,
    "zip": zip,
    "Exception": Exception,
}


_BUBBLEUP_EXCEPTIONS = (
    odoo.exceptions.UserError,
    odoo.exceptions.RedirectWarning,
    werkzeug.exceptions.HTTPException,
    OperationalError,
    ZeroDivisionError,
)


def safe_eval(
    expr: str | bytes,
    /,
    context: dict | None = None,
    *,
    mode: typing.Literal["eval", "exec"] = "eval",
    filename: str | None = None,
) -> typing.Any:
    """Evaluate an expression using Python constants, arithmetic, and the
    objects provided in ``context``.

    Useful e.g. to evaluate a domain expression from an untrusted source.

    :param expr: Python expression (or block, if ``mode='exec'``) to evaluate
    :type expr: string | bytes
    :param context: namespace available to the expression; mutated with any
                    variables created during evaluation
    :type context: dict
    :param mode: ``exec`` or ``eval``
    :type mode: str
    :param filename: optional pseudo-filename for the compiled expression,
                     shown e.g. in traceback frames
    :type filename: string
    :raises TypeError: the expression is a code object
    :raises SyntaxError: the expression is not valid Python
    :raises NameError: the expression accesses forbidden names
    :raises ValueError: the expression uses forbidden bytecode
    """
    if type(expr) is CodeType:
        msg = "safe_eval does not allow direct evaluation of code objects."
        raise TypeError(msg)

    assert context is None or type(context) is dict, "Context must be a dict"

    check_values(context)

    # The format guard is installed inside ``__builtins__`` rather than at the
    # top level of ``globals_dict``: LOAD_GLOBAL falls back to builtins, so the
    # transformed calls still resolve it, but it stays out of the caller's
    # ``context`` (the ``finally`` below only copies top-level names back) and a
    # user global cannot shadow it by accident.
    builtins = dict(_BUILTINS)
    builtins[_GUARD_FORMAT_NAME] = _guard_format
    globals_dict = dict(context or {}, __builtins__=builtins)

    c = compile_codeobj(expr, filename=filename, mode=mode, guard_format=True)
    assert_valid_codeobj(_SAFE_OPCODES, c, expr)
    try:
        return unsafe_eval(c, globals_dict, None)

    except _BUBBLEUP_EXCEPTIONS:
        raise

    except Exception as e:
        raise ValueError("%r while evaluating\n%r" % (e, expr)) from e

    finally:
        if context is not None:
            del globals_dict["__builtins__"]
            context.update(globals_dict)


def test_python_expr(expr: str, mode: str = "eval") -> str | typing.Literal[False]:
    try:
        c = compile_codeobj(expr, mode=mode)
        assert_valid_codeobj(_SAFE_OPCODES, c, expr)
    except (SyntaxError, TypeError, ValueError, NameError) as err:
        if len(err.args) >= 2 and len(err.args[1]) >= 4:
            error = {
                "message": err.args[0],
                "filename": err.args[1][0],
                "lineno": err.args[1][1],
                "offset": err.args[1][2],
                "error_line": err.args[1][3],
            }
            msg = "%s : %s at line %d\n%s" % (
                type(err).__name__,
                error["message"],
                error["lineno"],
                error["error_line"],
            )
        else:
            msg = str(err)
        return msg
    return False


_UNSEARCHABLE = (str, bytes, bytearray, int, float, complex, bool, type(None))
_CONTAINERS = (dict, list, tuple, set, frozenset)


def _check_module(value: object, seen: set[int] | None = None) -> None:
    """Recursively check that no module is hidden in containers.

    Scalars short-circuit before the identity bookkeeping: this walks the whole
    render/eval payload on every call, so on a data-heavy ``ir.qweb`` render the
    leaves (a few hundred thousand strings and ints) are the entire cost.
    """
    if isinstance(value, _UNSEARCHABLE):
        return
    if isinstance(value, types.ModuleType):
        raise TypeError(f"""Module {value} can not be used in evaluation contexts

Prefer providing only the items necessary for your intended use.

If a "module" is necessary for backwards compatibility, use
`odoo.tools.safe_eval.wrap_module` to generate a wrapper recursively
whitelisting allowed attributes.

Pre-wrapped modules are provided as attributes of `odoo.tools.safe_eval`.
""")
    if not isinstance(value, _CONTAINERS):
        return
    if seen is None:
        seen = set()
    obj_id = id(value)
    if obj_id in seen:
        return
    seen.add(obj_id)
    if isinstance(value, dict):
        for k, v in value.items():
            _check_module(k, seen)
            _check_module(v, seen)
    else:
        for v in value:
            _check_module(v, seen)


def check_values(d: dict | None) -> dict | None:
    """Reject module objects reachable from ``d``'s values.

    One ``seen`` set is shared across the top-level values so a structure
    referenced under several keys is walked once, not once per key.
    """
    if not d:
        return d
    seen: set[int] = set()
    for v in d.values():
        _check_module(v, seen)
    return d


class wrap_module:
    def __init__(self, module: types.ModuleType, attributes: list | dict) -> None:
        """Helper for wrapping a package/module to expose selected attributes

        :param module: the actual package/module to wrap, as returned by ``import <module>``
        :param iterable attributes: attributes to expose / whitelist. If a dict,
                                    the keys are the attributes and the values
                                    are used as an ``attributes`` in case the
                                    corresponding item is a submodule
        """
        modfile = getattr(module, "__file__", "(built-in)")
        self._repr = f"<wrapped {module.__name__!r} ({modfile})>"
        for attrib in attributes:
            target = getattr(module, attrib)
            if isinstance(target, types.ModuleType):
                target = wrap_module(target, attributes[attrib])
            setattr(self, attrib, target)

    def __repr__(self) -> str:
        return self._repr


import dateutil

mods = ["parser", "relativedelta", "rrule", "tz"]
for mod in mods:
    __import__("dateutil.%s" % mod)

datetime = wrap_module(
    __import__("datetime"),
    [
        "date",
        "datetime",
        "time",
        "timedelta",
        "timezone",
        "tzinfo",
        "MAXYEAR",
        "MINYEAR",
    ],
)
dateutil = wrap_module(
    dateutil,
    {
        "tz": ["UTC", "tzutc"],
        "parser": ["isoparse", "parse"],
        "relativedelta": [
            "relativedelta",
            "MO",
            "TU",
            "WE",
            "TH",
            "FR",
            "SA",
            "SU",
        ],
        "rrule": [
            "rrule",
            "rruleset",
            "rrulestr",
            "YEARLY",
            "MONTHLY",
            "WEEKLY",
            "DAILY",
            "HOURLY",
            "MINUTELY",
            "SECONDLY",
            "MO",
            "TU",
            "WE",
            "TH",
            "FR",
            "SA",
            "SU",
        ],
    },
)
json = wrap_module(__import__("json"), ["loads", "dumps"])
time = wrap_module(__import__("time"), ["time", "strptime", "strftime"])
from odoo.libs.datetime import tz as _tz_module

pytz = wrap_module(_tz_module, ["utc", "timezone"])
pytz.UTC = pytz.utc
dateutil.tz.gettz = pytz.timezone
