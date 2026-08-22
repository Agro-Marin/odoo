// @ts-check
/** @odoo-module native */

export const ASTType = {
    /** @type {0} */ Number: 0,
    /** @type {1} */ String: 1,
    /** @type {2} */ Boolean: 2,
    /** @type {3} */ None: 3,
    /** @type {4} */ List: 4,
    /** @type {5} */ Name: 5,
    /** @type {6} */ UnaryOperator: 6,
    /** @type {7} */ BinaryOperator: 7,
    /** @type {8} */ FunctionCall: 8,
    /** @type {9} */ Assignment: 9,
    /** @type {10} */ Tuple: 10,
    /** @type {11} */ Dictionary: 11,
    /** @type {12} */ Lookup: 12,
    /** @type {13} */ If: 13,
    /** @type {14} */ BooleanOperator: 14,
    /** @type {15} */ ObjLookup: 15,
    /** @type {16} */ Chain: 16,
};

/**
 * @typedef {{type: 0,  value: number}} ASTNumber
 * @typedef {{type: 1,  value: string}} ASTString
 * @typedef {{type: 2,  value: boolean}} ASTBoolean
 * @typedef {{type: 3}} ASTNone
 * @typedef {{type: 4,  value: AST[]}} ASTList
 * @typedef {{type: 5,  value: string}} ASTName
 * @typedef {{type: 6,  op: string, right: AST}} ASTUnaryOperator
 * @typedef {{type: 7,  op: string, left: AST, right: AST}} ASTBinaryOperator
 * @typedef {{type: 8,  fn: AST, args: AST[], kwargs: {[key: string]: AST}}} ASTFunctionCall
 * @typedef {{type: 9,  name: ASTName, value: AST}} ASTAssignment
 * @typedef {{type: 10, value: AST[]}} ASTTuple
 * @typedef {{type: 11, value: {[key: string]: AST}}} ASTDictionary
 * @typedef {{type: 12, target: AST, key: AST}} ASTLookup
 * @typedef {{type: 13, condition: AST, ifTrue: AST, ifFalse: AST}} ASTIf
 * @typedef {{type: 14, op: string, left: AST, right: AST}} ASTBooleanOperator
 * @typedef {{type: 15, obj: AST, key: string}} ASTObjLookup
 * @typedef {{type: 16, operands: AST[], operators: string[]}} ASTChain
 * @typedef { ASTNumber | ASTString | ASTBoolean | ASTNone | ASTList | ASTName | ASTUnaryOperator | ASTBinaryOperator | ASTFunctionCall | ASTAssignment | ASTTuple | ASTDictionary | ASTLookup | ASTIf | ASTBooleanOperator | ASTObjLookup | ASTChain } AST
 */
