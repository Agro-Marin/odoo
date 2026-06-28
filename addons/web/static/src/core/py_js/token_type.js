// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/token_type - Canonical lexer token type tags + token typedefs */

/**
 * Numeric discriminant for every lexer {@link Token} — the single source of
 * truth shared by the tokenizer (which emits these) and the parser (which
 * dispatches on them).
 *
 * Distinct vocabulary from {@link import("./ast_type").ASTType}: the lexer and
 * the AST overlap numerically but mean different things (token ``3`` = Name,
 * AST ``3`` = None). Keeping them as two named enums is precisely what stops a
 * reader — or a refactor — from confusing ``case TokenType.Number`` (dispatch
 * on input) with ``{type: ASTType.Number}`` (build output) in ``py_parser``.
 *
 * Each member is pinned to its literal type (a per-member type annotation)
 * rather than ``@enum {number}`` / ``Object.freeze`` — both of the latter widen
 * to ``number`` across a module import and break the literal-discriminant
 * narrowing of {@link Token}. See {@link ASTType} for the full rationale.
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
