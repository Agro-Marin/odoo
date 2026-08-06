// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_utils */

import { ASTType } from "./ast_type.js";
import { PyDate, PyDateTime, PyTime } from "./py_date.js";
import { bp } from "./py_parser.js";

/**
 * @typedef {import("./ast_type.js").AST} AST
 */

/**
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
                for (const key of Object.keys(value)) {
                    content[key] = toPyValue(value[key]);
                }
                return { type: ASTType.Dictionary, value: content };
            }
        default:
            throw new Error("Invalid type");
    }
}

const COMPARATORS = new Set([
    "in",
    "not in",
    "is",
    "is not",
    "<",
    "<=",
    ">",
    ">=",
    "==",
    "!=",
]);

/**
 * @param {AST} ast
 * @param {number} [lbp]
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
        case ASTType.Chain: {
            const abp = bp(ast.operators[0]);
            const str = ast.operands
                .map((operand, i) =>
                    i === 0
                        ? formatAST(operand, abp + 1)
                        : `${ast.operators[i - 1]} ${formatAST(operand, abp + 1)}`,
                )
                .join(" ");
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
 * Objects the interpreter has been told to treat as a Python dict, tracked
 * beside them rather than on them.
 *
 * A ``Proxy`` whose ``getPrototypeOf`` trap answered a sentinel used to carry
 * this. The trap must return the target's real prototype once the target is
 * non-extensible, so every frozen, sealed or ``preventExtensions``-ed object --
 * a context frozen by ``search_model._freezeInDevMode``, an ``immutable`` RPC
 * cache payload -- made the engine throw a ``TypeError`` about proxy
 * invariants, naming neither the expression nor the context. A ``WeakSet``
 * answers the same question without touching the object, and keeps the
 * caller's identity intact.
 *
 * @type {WeakSet<object>}
 */
const PY_DICTS = new WeakSet();

/**
 * @param {Record<string, any>} obj
 * @returns {Record<string, any>}
 */
export function toPyDict(obj) {
    PY_DICTS.add(obj);
    return obj;
}

/**
 * @param {any} value
 * @returns {boolean}
 */
export function isPyDict(value) {
    return typeof value === "object" && value !== null && PY_DICTS.has(value);
}

/**
 * @param {any} value
 * @returns {boolean}
 */
export function isPyMapping(value) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
        return false;
    }
    if (PY_DICTS.has(value)) {
        return true;
    }
    const proto = Object.getPrototypeOf(value);
    return proto === Object.prototype || proto === null;
}
