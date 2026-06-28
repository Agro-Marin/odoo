// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/ast_type - Canonical AST node type tags + discriminated-union typedefs */

/**
 * Numeric discriminant for every py_js AST node — the single source of truth
 * shared by the parser (which emits these), the interpreter (which switches on
 * them), and every decoder downstream (``domain.js``, ``context.js``,
 * ``core/tree/*``).
 *
 * Before this enum the same integers (0..15) were re-spelled as
 * ``N /* Name *\/`` magic literals in ~12 files; renumbering one silently
 * broke every consumer with no type error to catch it.
 *
 * **Why per-member literal type-pins and NOT ``@enum {number}`` or
 * ``Object.freeze``**: the AST is a discriminated union keyed on a *literal*
 * ``type`` (e.g. {@link ASTNumber} is ``{type: 0, ...}``). Both
 * ``@enum {number}`` and ``Object.freeze({Number: 0})`` type the member as
 * ``number`` once it crosses a module import, so ``{type: ASTType.Number}``
 * stops being assignable to ``{type: 0}`` and narrowing breaks — verified
 * empirically (an ``@enum`` version produced 26 TS2322s in py_parser). Pinning
 * each member to its literal type keeps ``ASTType.Number`` exactly ``0`` across
 * module boundaries, so construction and narrowing both hold.
 *
 * Values are in-memory only (the AST is never serialized) but are kept stable
 * so any out-of-tree reader still comparing against bare integers keeps working.
 */
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
};

/**
 * Discriminated union of every AST node. The ``type`` discriminant is kept as a
 * numeric literal here (TS cannot use an ``@enum`` member as a type position —
 * ``ASTType.Number`` is a value, not a type) but each literal is annotated with
 * its {@link ASTType} name so the legend lives beside the definition.
 *
 * @typedef {{type: 0,  value: number}}                                              ASTNumber          // ASTType.Number
 * @typedef {{type: 1,  value: string}}                                              ASTString          // ASTType.String
 * @typedef {{type: 2,  value: boolean}}                                             ASTBoolean         // ASTType.Boolean
 * @typedef {{type: 3}}                                                              ASTNone            // ASTType.None
 * @typedef {{type: 4,  value: AST[]}}                                               ASTList            // ASTType.List
 * @typedef {{type: 5,  value: string}}                                             ASTName            // ASTType.Name
 * @typedef {{type: 6,  op: string, right: AST}}                                     ASTUnaryOperator   // ASTType.UnaryOperator
 * @typedef {{type: 7,  op: string, left: AST, right: AST}}                          ASTBinaryOperator  // ASTType.BinaryOperator
 * @typedef {{type: 8,  fn: AST, args: AST[], kwargs: {[key: string]: AST}}}         ASTFunctionCall    // ASTType.FunctionCall
 * @typedef {{type: 9,  name: ASTName, value: AST}}                                  ASTAssignment      // ASTType.Assignment
 * @typedef {{type: 10, value: AST[]}}                                               ASTTuple           // ASTType.Tuple
 * @typedef {{type: 11, value: {[key: string]: AST}}}                                ASTDictionary      // ASTType.Dictionary
 * @typedef {{type: 12, target: AST, key: AST}}                                      ASTLookup          // ASTType.Lookup
 * @typedef {{type: 13, condition: AST, ifTrue: AST, ifFalse: AST}}                  ASTIf              // ASTType.If
 * @typedef {{type: 14, op: string, left: AST, right: AST}}                          ASTBooleanOperator // ASTType.BooleanOperator
 * @typedef {{type: 15, obj: AST, key: string}}                                      ASTObjLookup       // ASTType.ObjLookup
 *
 * @typedef { ASTNumber | ASTString | ASTBoolean | ASTNone | ASTList | ASTName | ASTUnaryOperator | ASTBinaryOperator | ASTFunctionCall | ASTAssignment | ASTTuple | ASTDictionary | ASTLookup | ASTIf | ASTBooleanOperator | ASTObjLookup } AST
 */
