"""Restricted alternatives to eval() for simple and/or untrusted code.

Used to parse Odoo domain strings, conditions and expressions, mostly built on
locals plus condition/math builtins.
"""

import dis
import functools
import logging
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

unsafe_eval = eval  # noqa: S307  # eval is the intentional core of the safe_eval sandbox

__all__ = ["const_eval", "expr_eval", "safe_eval"]

# `time` is usually already present, but some code imports it, e.g.
# datetime.datetime.now() on Windows/Python 2.5.2 (bug lp:703841).
_ALLOWED_MODULES = ["_strptime", "math", "time"]


# Mock __import__ as called by cpython's import emulator `PyImport_Import` inside
# timemodule.c, _datetimemodule.c and others. It need not do anything: its only
# job is to make the module available in `sys.modules`, which the imports of
# _ALLOWED_MODULES below ensure.
def _import(
    name: str,
    globals: dict | None = None,  # noqa: A002  # mirrors builtin __import__ signature
    locals: dict | None = None,  # noqa: A002  # mirrors builtin __import__ signature
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
    # Frames
    "f_builtins",
    "f_code",
    "f_globals",
    "f_locals",
    "f_generator",  # Python 3.14 frame attribute
    # Legacy Python 2 names: don't exist in Python 3, blocked for defence-in-depth
    "func_code",
    "func_globals",
    # Code object
    "co_code",
    "_co_code_adaptive",
    # Method resolution order,
    "mro",
    # Tracebacks
    "tb_frame",
    # Generators
    "gi_code",
    "gi_frame",
    "gi_yieldfrom",
    # Coroutines
    "cr_await",
    "cr_code",
    "cr_frame",
    # Coroutine generators
    "ag_await",
    "ag_code",
    "ag_frame",
]


def to_opcodes(opnames: list[str], _opmap: dict[str, int] = opmap) -> Iterator[int]:
    for x in opnames:
        if x in _opmap:
            yield _opmap[x]


# Opcodes that must never be usable in safe_eval; subtracted from every
# allowed-opcode set as defence-in-depth.
_BLACKLIST = set(
    to_opcodes(
        [
            # can't provide access to accessing arbitrary modules
            "IMPORT_STAR",
            "IMPORT_NAME",
            "IMPORT_FROM",
            # could allow replacing or updating core attributes on models & al, setitem
            # can be used to set field values
            "STORE_ATTR",
            "DELETE_ATTR",
            # no reason to allow this
            "STORE_GLOBAL",
            "DELETE_GLOBAL",
        ]
    )
)
# opcodes necessary to build literal values
_CONST_OPCODES = (
    set(
        to_opcodes(
            [
                # stack manipulations
                "POP_TOP",
                "ROT_TWO",
                "ROT_THREE",
                "ROT_FOUR",
                "DUP_TOP",
                "DUP_TOP_TWO",
                "LOAD_CONST",
                "RETURN_VALUE",  # return the result of the literal/expr evaluation
                # literal collections
                "BUILD_LIST",
                "BUILD_MAP",
                "BUILD_TUPLE",
                "BUILD_SET",
                # 3.6: literal map with constant keys https://bugs.python.org/issue27140
                "BUILD_CONST_KEY_MAP",
                "LIST_EXTEND",
                "SET_UPDATE",
                # 3.11 replace DUP_TOP, DUP_TOP_TWO, ROT_TWO, ROT_THREE, ROT_FOUR
                "COPY",
                "SWAP",
                # Added in 3.11 https://docs.python.org/3/whatsnew/3.11.html#new-opcodes
                "RESUME",
                # 3.12 https://docs.python.org/3/whatsnew/3.12.html#cpython-bytecode-changes
                "RETURN_CONST",
                # 3.13
                "TO_BOOL",
                # 3.14 https://docs.python.org/3.14/whatsnew/3.14.html#cpython-bytecode-changes
                "LOAD_SMALL_INT",  # replaces LOAD_CONST for small integers
                "NOT_TAKEN",  # branch prediction hint (no-op)
            ]
        )
    )
    - _BLACKLIST
)

# operations that are both binary and in-place (same order as the docs)
_operations = [
    "POWER",
    "MULTIPLY",  # 'MATRIX_MULTIPLY', # matrix operator (3.5+)
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
# operations on literal values
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
                # comprehensions
                "LIST_APPEND",
                "MAP_ADD",
                "SET_ADD",
                "COMPARE_OP",
                # specialised comparisons
                "IS_OP",
                "CONTAINS_OP",
                "DICT_MERGE",
                "DICT_UPDATE",
                # Used in any "generator literal"
                "GEN_START",  # added in 3.10 but already removed from 3.11.
                # Added in 3.11, replacing all BINARY_* and INPLACE_*
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
                # note: removed in 3.8
                "SETUP_LOOP",
                "SETUP_EXCEPT",
                "BREAK_LOOP",
                "CONTINUE_LOOP",
                "EXTENDED_ARG",  # P3.6 for long jump offsets.
                "MAKE_FUNCTION",
                "CALL_FUNCTION",
                "CALL_FUNCTION_KW",
                "CALL_FUNCTION_EX",
                # Added in P3.7 https://bugs.python.org/issue26110
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
                # Added in 3.8 https://bugs.python.org/issue17611
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
                "STORE_SUBSCR",
                "LOAD_GLOBAL",
                "RERAISE",
                "JUMP_IF_NOT_EXC_MATCH",
                # Following opcodes were Added in 3.11
                # replacement of opcodes CALL_FUNCTION, CALL_FUNCTION_KW, CALL_METHOD
                "PUSH_NULL",
                "PRECALL",
                "CALL",
                "KW_NAMES",
                # replacement of POP_JUMP_IF_TRUE and POP_JUMP_IF_FALSE
                "POP_JUMP_FORWARD_IF_FALSE",
                "POP_JUMP_FORWARD_IF_TRUE",
                "POP_JUMP_BACKWARD_IF_FALSE",
                "POP_JUMP_BACKWARD_IF_TRUE",
                # special case of the previous for IS NONE / IS NOT NONE
                "POP_JUMP_FORWARD_IF_NONE",
                "POP_JUMP_BACKWARD_IF_NONE",
                "POP_JUMP_FORWARD_IF_NOT_NONE",
                "POP_JUMP_BACKWARD_IF_NOT_NONE",
                # replacement of JUMP_IF_NOT_EXC_MATCH
                "CHECK_EXC_MATCH",
                # new opcodes
                "RETURN_GENERATOR",
                "PUSH_EXC_INFO",
                "NOP",
                "FORMAT_VALUE",
                "BUILD_STRING",
                # 3.12 https://docs.python.org/3/whatsnew/3.12.html#cpython-bytecode-changes
                "END_FOR",
                "LOAD_FAST_AND_CLEAR",
                "LOAD_FAST_CHECK",
                "POP_JUMP_IF_NOT_NONE",
                "POP_JUMP_IF_NONE",
                "CALL_INTRINSIC_1",
                "STORE_SLICE",
                # 3.13
                "CALL_KW",
                "LOAD_FAST_LOAD_FAST",
                "STORE_FAST_STORE_FAST",
                "STORE_FAST_LOAD_FAST",
                "CONVERT_VALUE",
                "FORMAT_SIMPLE",
                "FORMAT_WITH_SPEC",
                "SET_FUNCTION_ATTRIBUTE",
                # 3.14
                "LOAD_FAST_BORROW",  # optimized LOAD_FAST for borrowed references
                "POP_ITER",  # replaces END_FOR for iterator cleanup
                "LOAD_FAST_BORROW_LOAD_FAST_BORROW",  # compound load optimization
                "LOAD_COMMON_CONSTANT",  # loads common constants (None, NotImplemented, etc.)
            ]
        )
    )
    - _BLACKLIST
)


_logger = logging.getLogger(__name__)

# Cache keyed by (co_code, co_names, allowed_codes_id): identical bytecode need
# not be re-scanned for opcodes and names. Only populated for code objects with
# no nested code object (lambda/comprehension), whose validation verdict the key
# fully captures — see assert_valid_codeobj for why nested code is never cached.
_validated_bytecode_cache: dict[tuple, bool] = {}
_VALIDATED_CACHE_MAX = 8192


def assert_no_dunder_name(code_obj: CodeType, expr: str) -> None:
    """Assert the code object refers to no name containing two underscores.

    This blocks dunder names (``__name__``) and thus access to internal-ish
    Python attributes/methods, which are loaded via LOAD_ATTR by name (in
    co_names), not as a const or var.

    :param code_obj: code object to name-validate
    :type code_obj: CodeType
    :param str expr: expression for the code object, for debugging
    :raises NameError: a forbidden name (a dunder or unsafe attribute) is found
    """
    for name in code_obj.co_names:
        if "__" in name or name in _UNSAFE_ATTRIBUTES:
            raise NameError("Access to forbidden name %r (%r)" % (name, expr))


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
    # Code objects nested in co_consts (lambdas, comprehensions, generator
    # expressions) carry their OWN bytecode and names, which (co_code, co_names)
    # do not capture. Two expressions can share an identical *parent*
    # (co_code, co_names) while differing only inside a nested lambda — e.g.
    # ``[(lambda v: v.foo)(x) for x in xs]`` vs
    # ``[(lambda v: v.__class__)(x) for x in xs]`` compile to the same parent
    # code object. Caching on the parent key alone let the second expression
    # reuse the first's "validated" verdict and skip the nested dunder/opcode
    # checks entirely — a sandbox escape (reaching ``object`` via ``__class__``).
    # The cache is therefore only sound for code objects with no nested code
    # object: for those, (co_code, co_names) fully determines the validation
    # outcome (every other const is an inert literal). Anything containing a
    # nested code object is validated in full, every time.
    nested_code = [c for c in code_obj.co_consts if isinstance(c, CodeType)]
    cacheable = not nested_code

    # Fast path: identical bytecode + names + allowed set already validated.
    # Key on the allowlist's CONTENT (frozenset), not id(): a garbage-collected
    # allowlist set's id can be reused by a *different* set, which would let the
    # new allowlist silently inherit the old one's "validated" verdicts — a
    # cache-poisoning seam in a sandbox primitive. frozenset() of ~50 opcode ints
    # is negligible next to the dis.get_instructions() it guards.
    cache_key = (code_obj.co_code, code_obj.co_names, frozenset(allowed_codes))
    if cacheable and cache_key in _validated_bytecode_cache:
        return

    assert_no_dunder_name(code_obj, expr)

    # set operations are almost twice as fast as a manual iteration + condition
    # when loading /web according to line_profiler
    code_codes = {i.opcode for i in dis.get_instructions(code_obj)}
    if not allowed_codes >= code_codes:
        raise ValueError(
            "forbidden opcode(s) in %r: %s"
            % (expr, ", ".join(opname[x] for x in (code_codes - allowed_codes)))
        )

    for const in nested_code:
        assert_valid_codeobj(allowed_codes, const, "lambda")

    # Only cache after full validation succeeds, and only for nested-code-free
    # objects whose verdict the key actually captures (see above).
    if cacheable and len(_validated_bytecode_cache) < _VALIDATED_CACHE_MAX:
        _validated_bytecode_cache[cache_key] = True


def compile_codeobj(
    expr: str,
    /,
    filename: str = "<unknown>",
    mode: typing.Literal["eval", "exec"] = "eval",
) -> CodeType:
    """
    :param str filename: optional pseudo-filename for the compiled expression,
                         displayed for example in traceback frames
    :param str mode: 'eval' if single expression
                     'exec' if sequence of statements
    :return: compiled code object
    :rtype: types.CodeType
    """
    assert mode in ("eval", "exec")
    try:
        if mode == "eval":
            expr = expr.strip()  # eval() does not like leading/trailing whitespace
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
    "xrange": range,  # Python 2 compat shim — user expressions may use xrange
    "zip": zip,
    "Exception": Exception,
}


_BUBBLEUP_EXCEPTIONS = (
    odoo.exceptions.UserError,
    odoo.exceptions.RedirectWarning,
    werkzeug.exceptions.HTTPException,
    OperationalError,  # let auto-replay of serialized transactions work its magic
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

    globals_dict = dict(context or {}, __builtins__=dict(_BUILTINS))

    c = compile_codeobj(expr, filename=filename, mode=mode)
    assert_valid_codeobj(_SAFE_OPCODES, c, expr)
    try:
        # locals=None makes locals default to globals, like top-level code
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


def _check_module(value: object, seen: set[int] | None = None) -> None:
    """Recursively check that no module is hidden in containers."""
    if isinstance(value, types.ModuleType):
        raise TypeError(f"""Module {value} can not be used in evaluation contexts

Prefer providing only the items necessary for your intended use.

If a "module" is necessary for backwards compatibility, use
`odoo.tools.safe_eval.wrap_module` to generate a wrapper recursively
whitelisting allowed attributes.

Pre-wrapped modules are provided as attributes of `odoo.tools.safe_eval`.
""")
    if seen is None:
        seen = set()
    obj_id = id(value)
    if obj_id in seen:
        return
    seen.add(obj_id)
    if isinstance(value, dict):
        for v in value.values():
            _check_module(v, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            _check_module(v, seen)


def check_values(d: dict | None) -> dict | None:
    if not d:
        return d
    for v in d.values():
        _check_module(v)
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
        # builtin modules don't have a __file__ at all
        modfile = getattr(module, "__file__", "(built-in)")
        self._repr = f"<wrapped {module.__name__!r} ({modfile})>"
        for attrib in attributes:
            target = getattr(module, attrib)
            if isinstance(target, types.ModuleType):
                target = wrap_module(target, attributes[attrib])
            setattr(self, attrib, target)

    def __repr__(self) -> str:
        return self._repr


# dateutil submodules are lazy so need to import them for them to "exist"
import dateutil  # noqa: E402

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
time = wrap_module(__import__("time"), ["time", "strptime", "strftime", "sleep"])
# Expose timezone utilities (pytz-compatible interface for server actions)
from odoo.libs.datetime import tz as _tz_module  # noqa: E402

pytz = wrap_module(_tz_module, ["utc", "timezone"])
pytz.UTC = pytz.utc  # pytz.UTC is an alias for pytz.utc
dateutil.tz.gettz = pytz.timezone
