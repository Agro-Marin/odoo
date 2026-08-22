// @ts-check
/** @odoo-module native */

export const TokenType = {
    /** @type {0} */ Number: 0,
    /** @type {1} */ String: 1,
    /** @type {2} */ Symbol: 2,
    /** @type {3} */ Name: 3,
    /** @type {4} */ Constant: 4,
};

/**
 * @typedef {{type: 0, value: number}} TokenNumber
 * @typedef {{type: 1, value: string}} TokenString
 * @typedef {{type: 2, value: string}} TokenSymbol
 * @typedef {{type: 3, value: string}} TokenName
 * @typedef {{type: 4, value: string}} TokenConstant
 * @typedef {TokenNumber | TokenString | TokenSymbol | TokenName | TokenConstant} Token
 */
