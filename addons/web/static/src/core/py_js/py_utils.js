// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_utils - AST-to-value conversion and AST-to-string formatting for Python expressions */

import { ASTType } from "./ast_type.js";
import { PyDate, PyDateTime, PyTime } from "./py_date.js";
import { bp } from "./py_parser.js";

/**
 * AST node — a discriminated union keyed on the literal ``type`` tag (see
 * {@link ASTType}); ``.type``/``switch`` checks narrow it to each node shape.
 * @typedef {import("./ast_type.js").AST} AST
 */

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
                return { type: ASTType.String, value: value.strftime("%H:%M:%S") };
            } else if (value instanceof PyDate) {
                return { type: ASTType.String, value: value.strftime("%Y-%m-%d") };
            } else {
                /** @type {Record<string, any>} */
                const content = {};
                // OWN keys only. ``for...in`` also walks the prototype chain,
                // so a value carrying any enumerable inherited property (a
                // class instance, an object built on a non-trivial prototype)
                // emitted phantom dict entries — which reach the server, since
                // this AST is what ``Domain``/``formatAST`` serialize. Every
                // sibling here (``formatAST``, the interpreter's Dictionary
                // case) already reads own keys only.
                for (const key of Object.keys(value)) {
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
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.BinaryOperator: {
            const abp = bp(ast.op);
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
            const pairs = [];
            for (const k of Object.keys(ast.value || {})) {
                pairs.push(`${JSON.stringify(k)}: ${formatAST(ast.value[k])}`);
            }
            return `{` + pairs.join(", ") + `}`;
        }
        case ASTType.Tuple: {
            const items = ast.value.map((v) => formatAST(v));
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
            const str = `${formatAST(ifTrue, abp + 1)} if ${formatAST(
                condition,
                abp + 1,
            )} else ${formatAST(ifFalse, abp)}`;
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.BooleanOperator: {
            const abp = bp(ast.op);
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
