// @ts-check
/** @odoo-module native */

import { ASTType } from "./ast_type.js";
import { binaryOperators, comparators } from "./py_tokenizer.js";
import { TokenType } from "./token_type.js";

/**
 * @typedef { import("./py_tokenizer").Token } Token
 */

/**
 * @typedef { import("./ast_type").AST } AST
 * @typedef { import("./ast_type").ASTBinaryOperator } ASTBinaryOperator
 */

class ParserError extends Error {}

const MAX_PARSE_DEPTH = 200;

const chainedOperators = new Set(comparators.filter((op) => op !== "not"));
const infixOperators = new Set(
    [...binaryOperators, ...comparators].filter((op) => op !== "not"),
);

class TokenCursor {
    /** @param {Token[]} tokens */
    constructor(tokens) {
        this._tokens = tokens;
        this._pos = 0;
        this._depth = 0;
    }
    enter() {
        if (this._depth >= MAX_PARSE_DEPTH) {
            throw new ParserError("Maximum expression depth exceeded");
        }
        this._depth++;
    }
    leave() {
        this._depth--;
    }
    peek() {
        return this._tokens[this._pos];
    }
    next() {
        return this._tokens[this._pos++];
    }
    get remaining() {
        return this._tokens.length - this._pos;
    }
}

/**
 * @param {string} symbol
 * @returns {number}
 */
export function bp(symbol) {
    switch (symbol) {
        case "=":
            return 10;
        case "if":
            return 20;
        case "in":
        case "not in":
        case "is":
        case "is not":
        case "<":
        case "<=":
        case ">":
        case ">=":
        case "<>":
        case "==":
        case "!=":
            return 60;
        case "or":
            return 30;
        case "and":
            return 40;
        case "not":
            return 50;
        case "|":
            return 70;
        case "^":
            return 80;
        case "&":
            return 90;
        case "<<":
        case ">>":
            return 100;
        case "+":
        case "-":
            return 110;
        case "*":
        case "/":
        case "//":
        case "%":
            return 120;
        case "**":
            return 140;
        case ".":
        case "(":
        case "[":
            return 150;
    }
    return 0;
}

/**
 * @param {Token} token
 * @returns {number}
 */
function bindingPower(token) {
    return token.type === TokenType.Symbol
        ? bp(/** @type {string} */ (token.value))
        : 0;
}

/**
 * @param {Token} token
 * @param {string} value
 * @returns {boolean}
 */
function isSymbol(token, value) {
    return token.type === TokenType.Symbol && token.value === value;
}

/**
 * `(a)` is a group and `(a,)` / `()` a tuple.
 *
 * @param {TokenCursor} cur positioned after the opening parenthesis
 * @returns {AST}
 */
function parseParenthesized(cur) {
    const content = [];
    let isTuple = false;
    while (cur.peek() && !isSymbol(cur.peek(), ")")) {
        content.push(_parse(cur, 0));
        if (!cur.peek()) {
            throw new ParserError("parsing error");
        }
        if (isSymbol(cur.peek(), ",")) {
            isTuple = true;
            cur.next();
        } else if (!isSymbol(cur.peek(), ")")) {
            throw new ParserError("parsing error");
        }
    }
    if (!cur.peek() || !isSymbol(cur.peek(), ")")) {
        throw new ParserError("parsing error");
    }
    cur.next();
    isTuple = isTuple || content.length === 0;
    return isTuple ? { type: ASTType.Tuple, value: content } : content[0];
}

/**
 * @param {TokenCursor} cur positioned after the opening bracket
 * @returns {AST}
 */
function parseList(cur) {
    const value = [];
    while (cur.peek() && !isSymbol(cur.peek(), "]")) {
        value.push(_parse(cur, 0));
        if (cur.peek()) {
            if (isSymbol(cur.peek(), ",")) {
                cur.next();
            } else if (!isSymbol(cur.peek(), "]")) {
                throw new ParserError("parsing error");
            }
        }
    }
    if (!cur.peek() || !isSymbol(cur.peek(), "]")) {
        throw new ParserError("parsing error");
    }
    cur.next();
    return { type: ASTType.List, value };
}

/**
 * @param {TokenCursor} cur positioned after the opening brace
 * @returns {AST}
 */
function parseDict(cur) {
    /** @type {Record<string, AST>} */
    const dict = {};
    while (cur.peek() && !isSymbol(cur.peek(), "}")) {
        const key = _parse(cur, 0);
        if (
            (key.type !== ASTType.String && key.type !== ASTType.Number) ||
            !cur.peek() ||
            !isSymbol(cur.peek(), ":")
        ) {
            throw new ParserError("parsing error");
        }
        cur.next();
        const value = _parse(cur, 0);
        Object.defineProperty(dict, /** @type {any} */ (key).value, {
            value,
            writable: true,
            enumerable: true,
            configurable: true,
        });
        if (cur.peek() && isSymbol(cur.peek(), ",")) {
            cur.next();
        }
    }
    if (!cur.next()) {
        throw new ParserError("parsing error");
    }
    return { type: ASTType.Dictionary, value: dict };
}

/**
 * @param {Token} current
 * @param {TokenCursor} cur
 * @returns {AST}
 */
function parsePrefix(current, cur) {
    switch (current.type) {
        case TokenType.Number:
            return { type: ASTType.Number, value: current.value };
        case TokenType.String:
            return { type: ASTType.String, value: current.value };
        case TokenType.Constant:
            if (current.value === "None") {
                return { type: ASTType.None };
            } else {
                return { type: ASTType.Boolean, value: current.value === "True" };
            }
        case TokenType.Name:
            return { type: ASTType.Name, value: current.value };
        case TokenType.Symbol:
            switch (current.value) {
                case "-":
                case "+":
                case "~":
                    return {
                        type: ASTType.UnaryOperator,
                        op: current.value,
                        right: _parse(cur, 130),
                    };
                case "not":
                    return {
                        type: ASTType.UnaryOperator,
                        op: current.value,
                        right: _parse(cur, 50),
                    };
                case "(":
                    return parseParenthesized(cur);
                case "[":
                    return parseList(cur);
                case "{":
                    return parseDict(cur);
            }
    }
    throw new ParserError("Token cannot be parsed");
}

/**
 * `a < b < c` is one chain of comparisons, evaluated left to right.
 *
 * @param {AST} left
 * @param {AST} right
 * @param {Token} current
 * @param {TokenCursor} cur
 * @returns {AST | null} the chain, or null when there is nothing after `right`
 */
function parseChain(left, right, current, cur) {
    const continuesAChain = () =>
        cur.peek() &&
        cur.peek().type === TokenType.Symbol &&
        chainedOperators.has(/** @type {string} */ (cur.peek().value));
    if (
        !chainedOperators.has(/** @type {string} */ (current.value)) ||
        !continuesAChain()
    ) {
        return null;
    }
    const operands = [left, right];
    const operators = [/** @type {string} */ (current.value)];
    while (continuesAChain()) {
        const nextToken = cur.next();
        operators.push(/** @type {string} */ (nextToken.value));
        operands.push(_parse(cur, bindingPower(nextToken)));
    }
    return { type: ASTType.Chain, operands, operators };
}

/**
 * @param {AST} left
 * @param {Token} current an infix operator
 * @param {TokenCursor} cur
 * @returns {AST}
 */
function parseBinary(left, current, cur) {
    const rightBp =
        current.value === "**" ? bindingPower(current) - 1 : bindingPower(current);
    const right = _parse(cur, rightBp);
    if (current.value === "and" || current.value === "or") {
        return { type: ASTType.BooleanOperator, op: current.value, left, right };
    } else if (current.value === ".") {
        if (right.type === ASTType.Name) {
            return {
                type: ASTType.ObjLookup,
                obj: left,
                key: /** @type {any} */ (right).value,
            };
        } else {
            throw new ParserError("invalid obj lookup");
        }
    }
    return (
        parseChain(left, right, current, cur) || {
            type: ASTType.BinaryOperator,
            op: /** @type {string} */ (current.value),
            left,
            right,
        }
    );
}

/**
 * @param {AST} fn
 * @param {TokenCursor} cur positioned after the opening parenthesis
 * @returns {AST}
 */
function parseCall(fn, cur) {
    const args = [];
    /** @type {Record<string, AST>} */
    const kwargs = {};
    while (cur.peek() && !isSymbol(cur.peek(), ")")) {
        const arg = _parse(cur, 0);
        if (arg.type === ASTType.Assignment) {
            Object.defineProperty(kwargs, /** @type {any} */ (arg).name.value, {
                value: /** @type {any} */ (arg).value,
                writable: true,
                enumerable: true,
                configurable: true,
            });
        } else {
            args.push(arg);
        }
        if (cur.peek() && isSymbol(cur.peek(), ",")) {
            cur.next();
        }
    }
    if (!cur.peek() || !isSymbol(cur.peek(), ")")) {
        throw new ParserError("parsing error");
    }
    cur.next();
    return { type: ASTType.FunctionCall, fn, args, kwargs };
}

/**
 * @param {AST} left
 * @param {Token} current
 * @param {TokenCursor} cur
 * @returns {AST}
 */
function parseInfix(left, current, cur) {
    switch (current.type) {
        case TokenType.Symbol:
            if (infixOperators.has(/** @type {string} */ (current.value))) {
                return parseBinary(left, current, cur);
            }
            switch (current.value) {
                case "(":
                    return parseCall(left, cur);
                case "=":
                    if (left.type === ASTType.Name) {
                        return {
                            type: ASTType.Assignment,
                            name: /** @type {any} */ (left),
                            value: _parse(cur, 10),
                        };
                    }
                    break;
                case "[": {
                    const key = _parse(cur);
                    if (!cur.peek() || !isSymbol(cur.peek(), "]")) {
                        throw new ParserError("parsing error");
                    }
                    cur.next();
                    return { type: ASTType.Lookup, target: left, key: key };
                }
                case "if": {
                    const condition = _parse(cur);
                    if (!cur.peek() || !isSymbol(cur.peek(), "else")) {
                        throw new ParserError("parsing error");
                    }
                    cur.next();
                    const ifFalse = _parse(cur);
                    return { type: ASTType.If, condition, ifTrue: left, ifFalse };
                }
            }
    }
    throw new ParserError("Token cannot be parsed");
}

/**
 * @param {TokenCursor} cur
 * @param {number} [bpVal]
 * @returns {AST}
 */
function _parse(cur, bpVal = 0) {
    cur.enter();
    try {
        const token = cur.next();
        let expr = parsePrefix(token, cur);
        while (cur.peek() && bindingPower(cur.peek()) > bpVal) {
            expr = parseInfix(expr, cur.next(), cur);
        }
        return expr;
    } finally {
        cur.leave();
    }
}

/**
 * @param {Token[]} tokens
 * @returns {AST}
 */
export function parse(tokens) {
    if (tokens.length) {
        const cur = new TokenCursor(tokens);
        const ast = _parse(cur, 0);
        if (cur.remaining) {
            throw new ParserError("Token(s) unused");
        }
        return ast;
    }
    throw new ParserError("Missing token");
}
