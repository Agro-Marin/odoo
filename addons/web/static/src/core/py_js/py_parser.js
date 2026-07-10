// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_parser - Pratt parser that converts Python token streams into AST nodes */

import { ASTType } from "./ast_type.js";
import { binaryOperators, comparators } from "./py_tokenizer.js";
import { TokenType } from "./token_type.js";

// Types

/**
 * @typedef { import("./py_tokenizer").Token } Token
 */

/**
 * The AST node typedefs and the {@link ASTType} discriminant legend live in
 * ``./ast_type.js`` (single source of truth shared with the interpreter and the
 * domain/context/tree decoders).
 *
 * @typedef { import("./ast_type").AST } AST
 * @typedef { import("./ast_type").ASTBinaryOperator } ASTBinaryOperator
 */

class ParserError extends Error {}

// Constants and helpers

const chainedOperators = new Set(comparators);
const infixOperators = new Set([...binaryOperators, ...comparators]);

/**
 * A lightweight cursor wrapping a token array for O(1) consumption.
 * Replaces Array.shift() (O(n)) with index-based access.
 */
class TokenCursor {
    /** @param {Token[]} tokens */
    constructor(tokens) {
        this._tokens = tokens;
        this._pos = 0;
    }
    /** Peek at the current token without consuming it. */
    peek() {
        return this._tokens[this._pos];
    }
    /** Consume and return the current token, advancing the position. */
    next() {
        return this._tokens[this._pos++];
    }
    /** Number of unconsumed tokens remaining. */
    get remaining() {
        return this._tokens.length - this._pos;
    }
}

/**
 * Compute the "binding power" of a symbol
 *
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
 * Compute binding power of a token.
 *
 * @param {Token} token
 * @returns {number}
 */
function bindingPower(token) {
    return token.type === TokenType.Symbol
        ? bp(/** @type {string} */ (token.value))
        : 0;
}

/**
 * Check if a token is a symbol of a given value.
 *
 * @param {Token} token
 * @param {string} value
 * @returns {boolean}
 */
function isSymbol(token, value) {
    return token.type === TokenType.Symbol && token.value === value;
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
                return {
                    type: ASTType.Boolean,
                    value: current.value === "True",
                };
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
                case "(": {
                    const content = [];
                    let isTuple = false;
                    while (cur.peek() && !isSymbol(cur.peek(), ")")) {
                        content.push(_parse(cur, 0));
                        if (cur.peek()) {
                            if (cur.peek() && isSymbol(cur.peek(), ",")) {
                                isTuple = true;
                                cur.next();
                            } else if (!isSymbol(cur.peek(), ")")) {
                                throw new ParserError("parsing error");
                            }
                        } else {
                            throw new ParserError("parsing error");
                        }
                    }
                    if (!cur.peek() || !isSymbol(cur.peek(), ")")) {
                        throw new ParserError("parsing error");
                    }
                    cur.next();
                    isTuple = isTuple || content.length === 0;
                    return isTuple
                        ? { type: ASTType.Tuple, value: content }
                        : content[0];
                }
                case "[": {
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
                case "{": {
                    /** @type {Record<string, AST>} */
                    const dict = {};
                    while (cur.peek() && !isSymbol(cur.peek(), "}")) {
                        const key = _parse(cur, 0);
                        if (
                            (key.type !== ASTType.String &&
                                key.type !== ASTType.Number) ||
                            !cur.peek() ||
                            !isSymbol(cur.peek(), ":")
                        ) {
                            throw new ParserError("parsing error");
                        }
                        cur.next();
                        const value = _parse(cur, 0);
                        // A literal '__proto__' key must become a plain OWN entry
                        // via defineProperty, not a [[Prototype]] write that
                        // swallows it. (A null-prototype dict would also fix this
                        // but breaks Object-typed consumers, e.g. OWL props validation.)
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
                    // remove the } token
                    if (!cur.next()) {
                        throw new ParserError("parsing error");
                    }
                    return { type: ASTType.Dictionary, value: dict };
                }
            }
    }
    throw new ParserError("Token cannot be parsed");
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
                // ``**`` is right-associative (``2**3**2`` == 2**(3**2) == 512).
                // Parsing its right operand with a binding power one below its
                // own lets a following ``**`` bind into the right subtree.
                const rightBp =
                    current.value === "**"
                        ? bindingPower(current) - 1
                        : bindingPower(current);
                let right = _parse(cur, rightBp);
                if (current.value === "and" || current.value === "or") {
                    return {
                        type: ASTType.BooleanOperator,
                        op: current.value,
                        left,
                        right,
                    };
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
                /** @type {AST} */
                let op = {
                    type: ASTType.BinaryOperator,
                    op: /** @type {string} */ (current.value),
                    left,
                    right,
                };
                while (
                    chainedOperators.has(/** @type {string} */ (current.value)) &&
                    cur.peek() &&
                    cur.peek().type === TokenType.Symbol &&
                    chainedOperators.has(/** @type {string} */ (cur.peek().value))
                ) {
                    const nextToken = cur.next();
                    /** @type {ASTBinaryOperator} */
                    const nextRight = {
                        type: ASTType.BinaryOperator,
                        op: /** @type {string} */ (nextToken.value),
                        left: right,
                        right: _parse(cur, bindingPower(nextToken)),
                    };
                    op = {
                        type: ASTType.BooleanOperator,
                        op: "and",
                        left: op,
                        right: nextRight,
                    };
                    right = nextRight.right;
                }
                return op;
            }
            switch (current.value) {
                case "(": {
                    // function call
                    const args = [];
                    /** @type {Record<string, AST>} */
                    const kwargs = {};
                    while (cur.peek() && !isSymbol(cur.peek(), ")")) {
                        const arg = _parse(cur, 0);
                        if (arg.type === ASTType.Assignment) {
                            kwargs[/** @type {any} */ (arg).name.value] =
                                /** @type {any} */ (arg).value;
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
                    return {
                        type: ASTType.FunctionCall,
                        fn: left,
                        args,
                        kwargs,
                    };
                }
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
                    // lookup in dictionary
                    const key = _parse(cur);
                    if (!cur.peek() || !isSymbol(cur.peek(), "]")) {
                        throw new ParserError("parsing error");
                    }
                    cur.next();
                    return {
                        type: ASTType.Lookup,
                        target: left,
                        key: key,
                    };
                }
                case "if": {
                    const condition = _parse(cur);
                    if (!cur.peek() || !isSymbol(cur.peek(), "else")) {
                        throw new ParserError("parsing error");
                    }
                    cur.next();
                    const ifFalse = _parse(cur);
                    return {
                        type: ASTType.If,
                        condition,
                        ifTrue: left,
                        ifFalse,
                    };
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
    const token = cur.next();
    let expr = parsePrefix(token, cur);
    while (cur.peek() && bindingPower(cur.peek()) > bpVal) {
        expr = parseInfix(expr, cur.next(), cur);
    }
    return expr;
}

// Parse function

/**
 * Parse a list of tokens.
 *
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
