// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_parser - Pratt parser that converts Python token streams into AST nodes */

import { binaryOperators, comparators } from "./py_tokenizer.js";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * @typedef { import("./py_tokenizer").Token } Token
 */

/**
 * @typedef {{type: 0, value: number}} ASTNumber
 * @typedef {{type: 1, value: string}} ASTString
 * @typedef {{type: 2, value: boolean}} ASTBoolean
 * @typedef {{type: 3}} ASTNone
 * @typedef {{type: 4, value: AST[]}} ASTList
 * @typedef {{type: 5, value: string}} ASTName
 * @typedef {{type: 6, op: string, right: AST}} ASTUnaryOperator
 * @typedef {{type: 7, op: string, left: AST, right: AST}} ASTBinaryOperator
 * @typedef {{type: 8, fn: AST, args: AST[], kwargs: {[key: string]: AST}}} ASTFunctionCall
 * @typedef {{type: 9, name: ASTName, value: AST}} ASTAssignment
 * @typedef {{type: 10, value: AST[]}} ASTTuple
 * @typedef {{type: 11, value: { [key: string]: AST}}} ASTDictionary
 * @typedef {{type: 12, target: AST, key: AST}} ASTLookup
 * @typedef {{type: 13, condition: AST, ifTrue: AST, ifFalse: AST}} ASTIf
 * @typedef {{type: 14, op: string, left: AST, right: AST}} ASTBooleanOperator
 * @typedef {{type: 15, obj: AST, key: string}} ASTObjLookup
 *
 * @typedef { ASTNumber | ASTString | ASTBoolean | ASTNone | ASTList | ASTName | ASTUnaryOperator | ASTBinaryOperator | ASTFunctionCall | ASTAssignment | ASTTuple | ASTDictionary |ASTLookup | ASTIf | ASTBooleanOperator | ASTObjLookup} AST
 */

class ParserError extends Error {}

// -----------------------------------------------------------------------------
// Constants and helpers
// -----------------------------------------------------------------------------

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
    return token.type === 2 /* Symbol */ ? bp(token.value) : 0;
}

/**
 * Check if a token is a symbol of a given value.
 *
 * @param {Token} token
 * @param {string} value
 * @returns {boolean}
 */
function isSymbol(token, value) {
    return token.type === 2 /* Symbol */ && token.value === value;
}

/**
 * @param {Token} current
 * @param {TokenCursor} cur
 * @returns {AST}
 */
function parsePrefix(current, cur) {
    switch (current.type) {
        case 0 /* Number */:
            return { type: 0 /* Number */, value: current.value };
        case 1 /* String */:
            return { type: 1 /* String */, value: current.value };
        case 4 /* Constant */:
            if (current.value === "None") {
                return { type: 3 /* None */ };
            } else {
                return {
                    type: 2 /* Boolean */,
                    value: current.value === "True",
                };
            }
        case 3 /* Name */:
            return { type: 5 /* Name */, value: current.value };
        case 2 /* Symbol */:
            switch (current.value) {
                case "-":
                case "+":
                case "~":
                    return {
                        type: 6 /* UnaryOperator */,
                        op: current.value,
                        right: _parse(cur, 130),
                    };
                case "not":
                    return {
                        type: 6 /* UnaryOperator */,
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
                        ? { type: 10 /* Tuple */, value: content }
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
                    return { type: 4 /* List */, value };
                }
                case "{": {
                    /** @type {Record<string, AST>} */
                    const dict = {};
                    while (cur.peek() && !isSymbol(cur.peek(), "}")) {
                        const key = _parse(cur, 0);
                        if (
                            (key.type !== 1 /* String */ &&
                                key.type !== 0) /* Number */ ||
                            !cur.peek() ||
                            !isSymbol(cur.peek(), ":")
                        ) {
                            throw new ParserError("parsing error");
                        }
                        cur.next();
                        const value = _parse(cur, 0);
                        dict[key.value] = value;
                        if (cur.peek() && isSymbol(cur.peek(), ",")) {
                            cur.next();
                        }
                    }
                    // remove the } token
                    if (!cur.next()) {
                        throw new ParserError("parsing error");
                    }
                    return { type: 11 /* Dictionary */, value: dict };
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
        case 2 /* Symbol */:
            if (infixOperators.has(current.value)) {
                let right = _parse(cur, bindingPower(current));
                if (current.value === "and" || current.value === "or") {
                    return {
                        type: 14 /* BooleanOperator */,
                        op: current.value,
                        left,
                        right,
                    };
                } else if (current.value === ".") {
                    if (right.type === 5 /* Name */) {
                        return {
                            type: 15 /* ObjLookup */,
                            obj: left,
                            key: right.value,
                        };
                    } else {
                        throw new ParserError("invalid obj lookup");
                    }
                }
                /** @type {AST} */
                let op = {
                    type: 7 /* BinaryOperator */,
                    op: /** @type {string} */ (current.value),
                    left,
                    right,
                };
                while (
                    chainedOperators.has(current.value) &&
                    cur.peek() &&
                    cur.peek().type === 2 /* Symbol */ &&
                    chainedOperators.has(cur.peek().value)
                ) {
                    const nextToken = cur.next();
                    /** @type {ASTBinaryOperator} */
                    const nextRight = {
                        type: 7 /* BinaryOperator */,
                        op: /** @type {string} */ (nextToken.value),
                        left: right,
                        right: _parse(cur, bindingPower(nextToken)),
                    };
                    op = {
                        type: 14 /* BooleanOperator */,
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
                        if (arg.type === 9 /* Assignment */) {
                            kwargs[arg.name.value] = arg.value;
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
                        type: 8 /* FunctionCall */,
                        fn: left,
                        args,
                        kwargs,
                    };
                }
                case "=":
                    if (left.type === 5 /* Name */) {
                        return {
                            type: 9 /* Assignment */,
                            name: left,
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
                        type: 12 /* Lookup */,
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
                        type: 13 /* If */,
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

// -----------------------------------------------------------------------------
// Parse function
// -----------------------------------------------------------------------------

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

/**
 * @param {any[]} args
 * @param {string[]} spec
 * @returns {{[name: string]: any}}
 */
export function parseArgs(args, spec) {
    const last = args.at(-1);
    const unnamedArgs = typeof last === "object" && last !== null ? args.slice(0, -1) : args;
    const kwargs = typeof last === "object" && last !== null ? last : {};
    for (const [index, val] of unnamedArgs.entries()) {
        kwargs[spec[index]] = val;
    }
    return kwargs;
}
