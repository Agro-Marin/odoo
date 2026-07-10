// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/token_type - Canonical lexer token type tags + token typedefs */

/**
 * Numeric discriminant for every lexer {@link Token}, shared by the tokenizer
 * (emits) and the parser (dispatches on).
 *
 * Distinct from {@link import("./ast_type").ASTType}: token and AST numbers
 * overlap but mean different things (token ``3`` = Name, AST ``3`` = None) —
 * two named enums stop dispatch (``case TokenType.Number``) from being
 * confused with output construction (``{type: ASTType.Number}``).
 *
 * Each member is pinned to its literal type rather than ``@enum {number}`` /
 * ``Object.freeze``, which would widen to ``number`` across a module import
 * and break the literal-discriminant narrowing of {@link Token}. See
 * {@link ASTType} for the full rationale.
 */
export const TokenType = {
    /** @type {0} */ Number: 0,
    /** @type {1} */ String: 1,
    /** @type {2} */ Symbol: 2,
    /** @type {3} */ Name: 3,
    /** @type {4} */ Constant: 4,
};

/**
 * @typedef {{type: 0, value: number}} TokenNumber   // TokenType.Number
 * @typedef {{type: 1, value: string}} TokenString   // TokenType.String
 * @typedef {{type: 2, value: string}} TokenSymbol   // TokenType.Symbol
 * @typedef {{type: 3, value: string}} TokenName      // TokenType.Name
 * @typedef {{type: 4, value: string}} TokenConstant // TokenType.Constant
 *
 * @typedef {TokenNumber | TokenString | TokenSymbol | TokenName | TokenConstant} Token
 */
