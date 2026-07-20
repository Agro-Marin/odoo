// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_utils - AST-to-value conversion and AST-to-string formatting for Python expressions */

import { ASTType } from "./ast_type.js";
import { PyDate, PyDateTime, PyTime } from "./py_date.js";
import { bp } from "./py_parser.js";

// Types

/**
 * AST node — a discriminated union keyed on the literal ``type`` tag (see
 * {@link ASTType}); ``.type``/``switch`` checks narrow it to each node shape.
 * @typedef {import("./ast_type.js").AST} AST
 */

// Utils

/**
 * Represent any value as a primitive AST
 *
 * @param {any} value
 * @returns {AST}
 */
export function toPyValue(value) {
    switch (typeof value) {
        case "string":
            return { type: ASTType.String, value };
        case "number":
            return { type: ASTType.Number, value };
        case "boolean":
            return { type: ASTType.Boolean, value };
        case "object":
            if (Array.isArray(value)) {
                return { type: ASTType.List, value: value.map(toPyValue) };
            } else if (value === null) {
                return { type: ASTType.None };
            } else if (value instanceof Date) {
                // Serialized eagerly so the node is a REAL string AST (it used
                // to smuggle the Py* instance as `value`, which only worked
                // because formatAST's JSON.stringify called its toJSON).
                // NB: convertDate reads LOCAL components, while datetime
                // domain values are conventionally UTC — callers passing a raw
                // JS Date get a local-time string (historical behavior, kept).
                return {
                    type: ASTType.String,
                    value: PyDateTime.convertDate(value).strftime("%Y-%m-%d %H:%M:%S"),
                };
            } else if (value instanceof PyDateTime) {
                return {
                    type: ASTType.String,
                    value: value.strftime("%Y-%m-%d %H:%M:%S"),
                };
            } else if (value instanceof PyTime) {
                // Before PyDate: PyTime extends PyDate but serializes as a time.
                return { type: ASTType.String, value: value.strftime("%H:%M:%S") };
            } else if (value instanceof PyDate) {
                return { type: ASTType.String, value: value.strftime("%Y-%m-%d") };
            } else {
                /** @type {Record<string, any>} */
                const content = {};
                // for...in intentional: evaluation contexts use Object.create(parentScope)
                // and inherited keys must be flattened into the Python dict.
                for (const key in value) {
                    content[key] = toPyValue(value[key]);
                }
                return { type: ASTType.Dictionary, value: content };
            }
        default:
            throw new Error("Invalid type");
    }
}

/**
 * Comparison operators are non-associative in Python: `(a < b) < c` and the
 * chained `a < b < c` are different expressions, so BOTH equal-precedence
 * children must be parenthesized when they are themselves comparisons.
 */
const COMPARATORS = new Set([
    "in",
    "not in",
    "is",
    "is not",
    "<",
    "<=",
    ">",
    ">=",
    "<>",
    "==",
    "!=",
]);

/**
 * @param {AST} ast
 * @param {number} [lbp] left binding power
 * @return {string}
 */
export function formatAST(ast, lbp = 0) {
    switch (ast.type) {
        case ASTType.None:
            return "None";
        case ASTType.String:
            return JSON.stringify(ast.value);
        case ASTType.Number: {
            const str = String(ast.value);
            // A negative literal groups like unary minus: `(-2) ** 2` must keep
            // its parens, else it re-parses as `-(2 ** 2)` (** binds tighter).
            // Mirrors the UnaryOperator case (abp = 130 for a leading sign).
            return ast.value < 0 && 130 < lbp ? `(${str})` : str;
        }
        case ASTType.Boolean:
            return ast.value ? "True" : "False";
        case ASTType.List:
            return `[${ast.value.map((v) => formatAST(v)).join(", ")}]`;
        case ASTType.UnaryOperator: {
            const abp = ast.op === "not" ? bp("not") : 130;
            const str =
                ast.op === "not"
                    ? `not ` + formatAST(ast.right, abp)
                    : ast.op + formatAST(ast.right, abp);
            // e.g. `(-a) ** b`: without parentheses this would re-parse as
            // `-(a ** b)` since `**` binds tighter than unary minus.
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.BinaryOperator: {
            const abp = bp(ast.op);
            // Associativity: an equal-precedence child on the non-associative
            // side must be parenthesized, otherwise re-parsing regroups it
            // (`a - (b - c)` would round-trip to `a - b - c`). `**` is
            // right-associative; everything else is left-associative;
            // comparators are non-associative (see COMPARATORS).
            let leftBp = abp;
            let rightBp = abp + 1;
            if (ast.op === "**") {
                leftBp = abp + 1;
                rightBp = abp;
            } else if (COMPARATORS.has(ast.op)) {
                leftBp = abp + 1;
            }
            const str = `${formatAST(ast.left, leftBp)} ${ast.op} ${formatAST(
                ast.right,
                rightBp,
            )}`;
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.Dictionary: {
            // KNOWN LIMITATION (Python 3 divergence): the Dictionary AST keys
            // its entries by a JS object, whose keys are ALWAYS strings, so an
            // integer literal key is collapsed to a string at parse time
            // (``py_parser.js``: ``{1: 2}`` → ``value: {"1": ...}``). formatAST
            // therefore cannot tell ``{1: 2}`` from ``{"1": 2}`` and emits
            // ``{"1": 2}`` for both — converting int keys to str keys where the
            // round-trip crosses back to the server, which distinguishes them.
            // Same root cause as the dict-lookup note in py_interpreter.js. A
            // proper fix carries the key AST (not a collapsed object key)
            // through Dictionary nodes; deferred because the AST shape is a
            // frozen contract asserted verbatim by py_parser's tests. Rare in
            // practice (domain/context dicts are string-keyed).
            const pairs = [];
            for (const k of Object.keys(ast.value || {})) {
                pairs.push(`${JSON.stringify(k)}: ${formatAST(ast.value[k])}`);
            }
            return `{` + pairs.join(", ") + `}`;
        }
        case ASTType.Tuple: {
            const items = ast.value.map((v) => formatAST(v));
            // A 1-element tuple needs its trailing comma: `(x)` is just `x`.
            return items.length === 1 ? `(${items[0]},)` : `(${items.join(", ")})`;
        }
        case ASTType.Name:
            return ast.value;
        case ASTType.Lookup: {
            return `${formatAST(ast.target)}[${formatAST(ast.key)}]`;
        }
        case ASTType.If: {
            const { ifTrue, condition, ifFalse } = ast;
            const abp = bp("if");
            // Python grammar: `x if C else y` — x and C are or_test (a nested
            // ternary there needs parentheses), y is a full conditional
            // expression (right-associative, no parentheses needed).
            const str = `${formatAST(ifTrue, abp + 1)} if ${formatAST(
                condition,
                abp + 1,
            )} else ${formatAST(ifFalse, abp)}`;
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.BooleanOperator: {
            const abp = bp(ast.op);
            // `and`/`or` are associative, so equal-precedence children can
            // stay bare — regrouping does not change the result.
            const str = `${formatAST(ast.left, abp)} ${ast.op} ${formatAST(ast.right, abp)}`;
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.ObjLookup:
            return `${formatAST(ast.obj, 150)}.${ast.key}`;
        case ASTType.FunctionCall: {
            const args = ast.args.map((v) => formatAST(v));
            const kwargs = [];
            for (const kwarg of Object.keys(ast.kwargs || {})) {
                kwargs.push(`${kwarg} = ${formatAST(ast.kwargs[kwarg])}`);
            }
            const argStr = [...args, ...kwargs].join(", ");
            return `${formatAST(ast.fn)}(${argStr})`;
        }
    }
    throw new Error(`invalid expression: ${ast}`);
}

/**
 * Prototype sentinel: the interpreter recognizes a value as a Python dict
 * when its [[Prototype]] is PY_DICT (see the ObjLookup case).
 */
export const PY_DICT = Object.create(null);

/**
 * Wrap a plain object as a Python dict for the interpreter: the returned
 * Proxy reports PY_DICT as its prototype so dict methods (`.get`) resolve.
 *
 * @param {Record<string, any>} obj
 * @returns {Record<string, any>}
 */
export function toPyDict(obj) {
    return new Proxy(obj, {
        getPrototypeOf() {
            return PY_DICT;
        },
    });
}
