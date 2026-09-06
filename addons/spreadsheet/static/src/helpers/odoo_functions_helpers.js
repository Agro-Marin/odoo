/** @odoo-module native */
// @ts-check

/**
 * What o-spreadsheet's `helpers.getFunctionsFromTokens` yields per matched call:
 * the function name upper-cased and its argument ASTs.
 *
 * @typedef {object} OdooFunctionDescription
 * @property {string} functionName
 * @property {import("@odoo/o-spreadsheet").AST[]} args
 */

/**
 * Extract the data source id (always the first argument) from the function
 * context of the given token.
 * @param {import("@odoo/o-spreadsheet").EnrichedToken} tokenAtCursor
 * @returns {string | undefined}
 */
export function extractDataSourceId(tokenAtCursor) {
    const idAst = tokenAtCursor.functionContext?.args[0];
    if (!idAst || !["STRING", "NUMBER"].includes(idAst.type)) {
        return;
    }
    return idAst.value;
}
