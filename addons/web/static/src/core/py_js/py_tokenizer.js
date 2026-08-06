// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_tokenizer */

import { TokenType } from "./token_type.js";

/**
 * @typedef { import("./token_type").Token } Token
 */

export class TokenizerError extends Error {}

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
            case "\n":
                ++i;
                continue;
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
                i += 5;
                continue;
            }
            case "U": {
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
                i += 9;
                continue;
            }
            case "x": {
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
                i += 3;
                continue;
            }
            default: {
                if (!/[0-7]/.test(escape)) {
                    break;
                }
                const r = /[0-7]{1,3}/g;
                r.lastIndex = i + 1;
                const m = /** @type {RegExpExecArray} */ (r.exec(str));
                const oct = m[0];
                code = Number.parseInt(oct, 8);
                out.push(String.fromCharCode(code));
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

const symbols = new Set([
    ...["(", ")", "[", "]", "{", "}", ":", ","],
    ...["if", "else", "lambda", "="],
    ...comparators,
    ...binaryOperators,
]);

/** @param {...string} args */
function group(...args) {
    return "(" + args.join("|") + ")";
}

/**
 * @param {string} token
 * @returns {number}
 */
function parseNumberLiteral(token) {
    return Number(token.replace(/_/g, "").replace(/[lL]$/, ""));
}

const Name = "[a-zA-Z_]\\w*";
const Whitespace = "[ \\f\\t]*";
const Digitpart = "\\d(?:_?\\d)*";
const DecNumber = `${Digitpart}(L|l)?`;
const HexNumber = "0[xX](?:_?[0-9a-fA-F])+";
const OctNumber = "0[oO](?:_?[0-7])+";
const BinNumber = "0[bB](?:_?[01])+";
const IntNumber = group(HexNumber, OctNumber, BinNumber, DecNumber);

const Exponent = `[eE][+-]?${Digitpart}`;
const PointFloat = group(
    `${Digitpart}\\.(?:${Digitpart})?(${Exponent})?`,
    `\\.${Digitpart}(${Exponent})?`,
);
const FloatNumber = group(PointFloat, `${Digitpart}${Exponent}`);

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
const pseudoprog = new RegExp(PseudoToken, "g");
const NumberPattern = new RegExp("^" + NumberToken + "$");
const StringPattern = new RegExp("^" + ContStr + "$");
const NamePattern = new RegExp("^" + Name + "$");
const strip = new RegExp("^" + Whitespace);

/**
 * @param {string} str
 * @returns {Token[]}
 */
export function tokenize(str) {
    /** @type {Token[]} */
    const tokens = [];
    const max = str.length;
    let end = 0;
    pseudoprog.lastIndex = 0;
    while (pseudoprog.lastIndex < max) {
        const pseudomatch = pseudoprog.exec(str);
        if (!pseudomatch) {
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
                value: parseNumberLiteral(token),
            });
        } else if (StringPattern.test(token)) {
            const m = /** @type {RegExpExecArray} */ (StringPattern.exec(token));
            tokens.push({
                type: TokenType.String,
                value: decodeStringLiteral(m[3] !== undefined ? m[3] : m[5]),
            });
        } else if (symbols.has(token)) {
            if (token === "<>") {
                token = "!=";
            }
            const prev = tokens.at(-1);
            if (
                token === "in" &&
                prev?.type === TokenType.Symbol &&
                prev.value === "not"
            ) {
                token = "not in";
                tokens.pop();
            } else if (
                token === "not" &&
                prev?.type === TokenType.Symbol &&
                prev.value === "is"
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
