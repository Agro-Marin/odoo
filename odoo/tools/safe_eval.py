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

import dateutil
import werkzeug
from psycopg import OperationalError

import odoo.exceptions
from odoo.libs.datetime import tz as _tz_module

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

unsafe_eval = eval  # noqa: S307  the raw builtin, kept so safe_eval can wrap it

__all__ = ["const_eval", "expr_eval", "safe_eval"]

_ALLOWED_MODULES = ["_strptime", "math", "time"]


def _import(
    name: str,
    # A002: this replaces the `__import__` builtin inside safe_eval, so the
    # parameter names have to match its signature — callers pass positionally,
    # but keyword use must keep working too.
    globals: dict | None = None,  # noqa: A002  mirrors __import__, see comment above
    locals: dict | None = None,  # noqa: A002  mirrors __import__, see comment above
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
    for x in opnames:
        if x in _opmap:
            yield _opmap[x]


def to_required_opcodes(
    opnames: list[str], _opmap: dict[str, int] = opmap
) -> Iterator[int]:
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
    for name in (*code_obj.co_names, *code_obj.co_freevars, *code_obj.co_cellvars):
        if "__" in name or name in _UNSAFE_ATTRIBUTES:
            raise NameError("Access to forbidden name %r (%r)" % (name, expr))


_formatter_parse = string.Formatter().parse


def assert_no_dunder_format_field(code_obj: CodeType, expr: str) -> None:
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
    __slots__ = ()

    def format(self, *args, **kwargs):
        return _STRICT_FORMATTER.vformat(self, args, kwargs)

    def format_map(self, mapping):
        return _STRICT_FORMATTER.vformat(self, (), mapping)


def _guard_format(recv: typing.Any) -> typing.Any:
    if type(recv) is str:
        return _GuardedStr(recv)
    if recv is str:
        return _GuardedStr
    return recv


_GUARD_FORMAT_NAME = "_odoo_guarded_format_receiver"


class _FormatGuardTransform(ast.NodeTransformer):
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
    c = compile_codeobj(expr)
    assert_valid_codeobj(_CONST_OPCODES, c, expr)
    return unsafe_eval(c)


def expr_eval(expr: str) -> typing.Any:
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
    if type(expr) is CodeType:
        msg = "safe_eval does not allow direct evaluation of code objects."
        raise TypeError(msg)

    assert context is None or type(context) is dict, "Context must be a dict"

    check_values(context)

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
    if not d:
        return d
    seen: set[int] = set()
    for v in d.values():
        _check_module(v, seen)
    return d


class wrap_module:
    def __init__(self, module: types.ModuleType, attributes: list | dict) -> None:
        modfile = getattr(module, "__file__", "(built-in)")
        self._repr = f"<wrapped {module.__name__!r} ({modfile})>"
        for attrib in attributes:
            target = getattr(module, attrib)
            if isinstance(target, types.ModuleType):
                target = wrap_module(target, attributes[attrib])
            setattr(self, attrib, target)

    def __repr__(self) -> str:
        return self._repr


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

pytz = wrap_module(_tz_module, ["utc", "timezone"])
pytz.UTC = pytz.utc
dateutil.tz.gettz = pytz.timezone
