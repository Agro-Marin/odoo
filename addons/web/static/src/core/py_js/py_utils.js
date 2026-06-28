// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_utils - AST-to-value conversion and AST-to-string formatting for Python expressions */

import { PyDate, PyDateTime } from "./py_date.js";
import { bp } from "./py_parser.js";
import { ASTType } from "./ast_type.js";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * AST node — a discriminated union keyed on the literal ``type`` tag (see
 * {@link ASTType}); ``.type``/``switch`` checks narrow it to each node shape.
 * @typedef {import("./ast_type.js").AST} AST
 */

// -----------------------------------------------------------------------------
// Utils
// -----------------------------------------------------------------------------

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
                    value: /** @type {any} */ (PyDateTime.convertDate(value)),
                };
            } else if (value instanceof PyDate || value instanceof PyDateTime) {
                return { type: ASTType.String, value: /** @type {any} */ (value) };
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
        case ASTType.Number:
            return String(ast.value);
        case ASTType.Boolean:
            return ast.value ? "True" : "False";
        case ASTType.List:
            return `[${ast.value.map(formatAST).join(", ")}]`;
        case ASTType.UnaryOperator:
            if (ast.op === "not") {
                return `not ` + formatAST(ast.right, 50);
            }
            return ast.op + formatAST(ast.right, 130);
        case ASTType.BinaryOperator: {
            const abp = bp(ast.op);
            const str = `${formatAST(ast.left, abp)} ${ast.op} ${formatAST(ast.right, abp)}`;
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.Dictionary: {
            const pairs = [];
            for (const k of Object.keys(ast.value || {})) {
                pairs.push(`"${k}": ${formatAST(ast.value[k])}`);
            }
            return `{` + pairs.join(", ") + `}`;
        }
        case ASTType.Tuple:
            return `(${ast.value.map(formatAST).join(", ")})`;
        case ASTType.Name:
            return ast.value;
        case ASTType.Lookup: {
            return `${formatAST(ast.target)}[${formatAST(ast.key)}]`;
        }
        case ASTType.If: {
            const { ifTrue, condition, ifFalse } = ast;
            return `${formatAST(ifTrue)} if ${formatAST(condition)} else ${formatAST(ifFalse)}`;
        }
        case ASTType.BooleanOperator: {
            const abp = bp(ast.op);
            const str = `${formatAST(ast.left, abp)} ${ast.op} ${formatAST(ast.right, abp)}`;
            return abp < lbp ? `(${str})` : str;
        }
        case ASTType.ObjLookup:
            return `${formatAST(ast.obj, 150)}.${ast.key}`;
        case ASTType.FunctionCall: {
            const args = ast.args.map(formatAST);
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

export const PY_DICT = Object.create(null);

/**
 * @param {Object} obj
 * @returns {AST} a python dictionary
 */
export function toPyDict(obj) {
    return /** @type {AST} */ (
        new Proxy(obj, {
            getPrototypeOf() {
                return PY_DICT;
            },
        })
    );
}
