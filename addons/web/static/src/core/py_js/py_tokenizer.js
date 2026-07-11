// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_tokenizer - Lexer that splits Python expression strings into typed tokens */

import { TokenType } from "./token_type.js";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

/**
 * The {@link Token} typedefs and the {@link TokenType} discriminant legend live
 * in ``./token_type.js`` (single source of truth shared with the parser).
 *
 * @typedef { import("./token_type").Token } Token
 */

export class TokenizerError extends Error {}

// -----------------------------------------------------------------------------
// Helpers and Constants
// -----------------------------------------------------------------------------

/**
 * Directly maps a single escape code to an output character
 */
/** @type {Record<string, string>} */
const directMap = {
    "\\": "\\",
    '"': '"',
    "'": "'",
    a: "\x07",
    b: "\x08",
    f: "\x0c",
    n: "\n",
    r: "\r",
    t: "\t",
    v: "\v",
};

/**
 * Decodes a Python string literal (embedded in a JS string) into a JS
 * string, resolving escapes. Python 3 semantics: every string literal
 * decodes ``\u``/``\U``/``\x``/octal escapes (a ``u``/``U`` prefix is
 * accepted by the grammar but changes nothing, as in CPython).
 *
 * @param {string} str
 * @returns {string}
 */
function decodeStringLiteral(str) {
    const out = [];
    let code;
    for (let i = 0; i < str.length; ++i) {
        if (str[i] !== "\\") {
            out.push(str[i]);
            continue;
        }
        const escape = str[i + 1];
        if (escape in directMap) {
            out.push(directMap[escape]);
            ++i;
            continue;
        }
        switch (escape) {
            // Ignored
            case "\n":
                ++i;
                continue;
            // Character named name in the Unicode database
            case "N":
                throw new TokenizerError("SyntaxError: \\N{} escape not implemented");
            case "u": {
                const uni = str.slice(i + 2, i + 6);
                if (!/[0-9a-f]{4}/i.test(uni)) {
                    throw new TokenizerError(
                        [
                            "SyntaxError: (unicode error) 'unicodeescape' codec",
                            " can't decode bytes in position ",
                            i,
                            "-",
                            i + 4,
                            ": truncated \\uXXXX escape",
                        ].join(""),
                    );
                }
                code = Number.parseInt(uni, 16);
                out.push(String.fromCodePoint(code));
                // escape + 4 hex digits
                i += 5;
                continue;
            }
            case "U": {
                // \UXXXXXXXX — 8-digit Unicode code point escape
                const codePointHex = str.slice(i + 2, i + 10);
                if (!/[0-9a-f]{8}/i.test(codePointHex)) {
                    throw new TokenizerError(
                        `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes in position ${i}-${i + 10}: truncated \\UXXXXXXXX escape`,
                    );
                }
                const codePoint = Number.parseInt(codePointHex, 16);
                if (codePoint > 0x10ffff) {
                    throw new TokenizerError(
                        `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes in position ${i}-${i + 10}: illegal Unicode character`,
                    );
                }
                out.push(String.fromCodePoint(codePoint));
                i += 9; // escape + 8 hex digits
                continue;
            }
            case "x": {
                // get 2 hex digits
                const hex = str.slice(i + 2, i + 4);
                if (!/[0-9a-f]{2}/i.test(hex)) {
                    throw new TokenizerError(
                        [
                            "SyntaxError: (unicode error) 'unicodeescape'",
                            " codec can't decode bytes in position ",
                            i,
                            "-",
                            i + 2,
                            ": truncated \\xXX escape",
                        ].join(""),
                    );
                }
                code = Number.parseInt(hex, 16);
                out.push(String.fromCharCode(code));
                // skip escape + 2 hex digits
                i += 3;
                continue;
            }
            default: {
                // Check if octal
                if (!/[0-7]/.test(escape)) {
                    break;
                }
                const r = /[0-7]{1,3}/g;
                r.lastIndex = i + 1;
                // Guaranteed to match: `escape` already passed the octal test above.
                const m = /** @type {RegExpExecArray} */ (r.exec(str));
                const oct = m[0];
                code = Number.parseInt(oct, 8);
                out.push(String.fromCharCode(code));
                // skip matchlength
                i += oct.length;
                continue;
            }
        }
        out.push("\\");
    }
    return out.join("");
}

const constants = new Set(["None", "False", "True"]);

export const comparators = [
    "in",
    "not",
    "not in",
    "is",
    "is not",
    "<",
    "<=",
    ">",
    ">=",
    "<>",
    "!=",
    "==",
];

export const binaryOperators = [
    "or",
    "and",
    "|",
    "^",
    "&",
    "<<",
    ">>",
    "+",
    "-",
    "*",
    "/",
    "//",
    "%",
    "~",
    "**",
    ".",
];

export const unaryOperators = ["-"];

const symbols = new Set([
    ...["(", ")", "[", "]", "{", "}", ":", ","],
    ...["if", "else", "lambda", "="],
    ...comparators,
    ...binaryOperators,
    ...unaryOperators,
]);

// Regexps
/** @param {...string} args */
function group(...args) {
    return "(" + args.join("|") + ")";
}

const Name = "[a-zA-Z_]\\w*";
const Whitespace = "[ \\f\\t]*";
const DecNumber = "\\d+(L|l)?";
const IntNumber = DecNumber;

const Exponent = "[eE][+-]?\\d+";
const PointFloat = group(`\\d+\\.\\d*(${Exponent})?`, `\\.\\d+(${Exponent})?`);
// Exponent not optional when no decimal point
const FloatNumber = group(PointFloat, `\\d+${Exponent}`);

const NumberToken = group(FloatNumber, IntNumber);
const Operator = group(
    "\\*\\*=?",
    ">>=?",
    "<<=?",
    "<>",
    "!=",
    "//=?",
    "[+\\-*/%&|^=<>]=?",
    "~",
);
const Bracket = "[\\[\\]\\(\\)\\{\\}]";
const Special = "[:;.,`@]";
const Funny = group(Operator, Bracket, Special);
const ContStr = group(
    "([uU])?'([^\n'\\\\]*(?:\\\\.[^\n'\\\\]*)*)'",
    '([uU])?"([^\n"\\\\]*(?:\\\\.[^\n"\\\\]*)*)"',
);
const PseudoToken = Whitespace + group(NumberToken, Funny, ContStr, Name);
/** Module-level regex — reused across tokenize() calls, reset via lastIndex. */
const pseudoprog = new RegExp(PseudoToken, "g");
const NumberPattern = new RegExp("^" + NumberToken + "$");
const StringPattern = new RegExp("^" + ContStr + "$");
const NamePattern = new RegExp("^" + Name + "$");
const strip = new RegExp("^" + Whitespace);

// -----------------------------------------------------------------------------
// Tokenize function
// -----------------------------------------------------------------------------

/**
 * Transform a string into a list of tokens
 *
 * @param {string} str
 * @returns {Token[]}
 */
export function tokenize(str) {
    /** @type {Token[]} */
    const tokens = [];
    const max = str.length;
    let end = 0;
    // /g flag makes repeated exec() have memory — reuse module-level regex
    pseudoprog.lastIndex = 0;
    while (pseudoprog.lastIndex < max) {
        const pseudomatch = pseudoprog.exec(str);
        if (!pseudomatch) {
            // if match failed on trailing whitespace, end tokenizing
            if (/^\s+$/.test(str.slice(end))) {
                break;
            }
            throw new TokenizerError(
                "Failed to tokenize <<" +
                    str +
                    ">> at index " +
                    (end || 0) +
                    "; parsed so far: " +
                    tokens,
            );
        }
        if (pseudomatch.index > end) {
            if (str.slice(end, pseudomatch.index).trim()) {
                throw new TokenizerError("Invalid expression");
            }
        }
        const start = pseudomatch.index;
        end = pseudoprog.lastIndex;
        let token = str.slice(start, end).replace(strip, "");
        if (NumberPattern.test(token)) {
            tokens.push({
                type: TokenType.Number,
                value: Number.parseFloat(token),
            });
        } else if (StringPattern.test(token)) {
            // Guaranteed to match: the `StringPattern.test(token)` branch above.
            const m = /** @type {RegExpExecArray} */ (StringPattern.exec(token));
            tokens.push({
                type: TokenType.String,
                value: decodeStringLiteral(m[3] !== undefined ? m[3] : m[5]),
            });
        } else if (symbols.has(token)) {
            if (token === "<>") {
                // Normalize the legacy Python 2 inequality to `!=`, mirroring
                // the server (orm/domain/optimizations.py: `a <> b => a != b`,
                // deprecated since 19.0). Downstream consumers (tree
                // comparators, formatAST) then only ever see `!=`.
                token = "!=";
            }
            // transform 'not in' and 'is not' in a single token
            if (token === "in" && tokens.length > 0 && tokens.at(-1)?.value === "not") {
                token = "not in";
                tokens.pop();
            } else if (
                token === "not" &&
                tokens.length > 0 &&
                tokens.at(-1)?.value === "is"
            ) {
                token = "is not";
                tokens.pop();
            }
            tokens.push({
                type: TokenType.Symbol,
                value: token,
            });
        } else if (constants.has(token)) {
            tokens.push({
                type: TokenType.Constant,
                value: token,
            });
        } else if (NamePattern.test(token)) {
            tokens.push({
                type: TokenType.Name,
                value: token,
            });
        } else {
            throw new TokenizerError("Invalid expression");
        }
    }
    return tokens;
}
