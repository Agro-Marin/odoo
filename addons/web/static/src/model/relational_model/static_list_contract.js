// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/static_list_contract */

/**
 * The `StaticList` operations a record, a parent list or a view invokes.
 *
 * Companion to `record_contract.js`, and derived differently. The record's
 * contract already existed — written down in the test doubles and conformance-
 * tested — and only had to be moved into production. `StaticList` has no double,
 * so this list was derived from the 86 measured cross-module accesses to its 25
 * externally-reached privates, and it is a *judgement about which of them are
 * an interface*, not a transcript of what reaches in today.
 *
 * THE DISTINCTION THIS FILE EXISTS TO DRAW. Those 86 accesses are two unlike
 * things that the private-access budget counts identically:
 *
 *  1. An OWNER invoking an operation — `record.js` calling `list._snapshot()`,
 *     `record_save.js` calling `list._clearCommands()`, `x2many_tree.js`
 *     calling `list._commitSave()`. The caller is asking the list to do
 *     something and does not care how. That is an interface, and it is what
 *     this list names.
 *
 *  2. A SATELLITE sharing internal state — `static_list_command_engine.js`
 *     reading and writing `list._currentIds`, `list._loadingStubIds`,
 *     `list._unknownRecordCommands`, `list._cache`. These are not operations;
 *     they are `StaticList`'s working memory, reached by helpers that were
 *     split out of the class and still think they are inside it.
 *
 * Only (1) belongs here. (2) is the real debt, named in `INTERNAL_STATE_REACHED`
 * below so that it is visible rather than merely absent — and so that the day a
 * helper stops reaching for one, that is a recorded win rather than a silent
 * one.
 *
 * @type {string[]}
 */
export const STATIC_LIST_OWNER_SURFACE = [
    // public shape an owner reads while walking its x2many children
    "cachedRecords",
    "getCachedRecord",
    "hasStagedCommands",
    "orderBy",
    "pendingCommands",
    // lifecycle the owner drives
    "_load",
    "_discard",
    "_snapshot",
    "_restore",
    // command staging, invoked when the owner saves or rolls back
    "_applyCommands",
    "_applyInitialCommands",
    "_clearCommands",
    "_getCommands",
    "_commitSave",
    // membership the owner changes
    "_addRecord",
    "_abandonRecords",
    "_replaceWith",
    // values pushed down from the owner
    "_applyServerValues",
    "_updateContext",
];

/**
 * `StaticList` internals that modules outside it reach today.
 *
 * NOT an interface, and deliberately not part of `StaticListContract`: a
 * satellite annotated with the contract that touches one of these is a
 * typecheck failure, which is the point. The list is here to make the residue
 * countable — every entry is a place where a helper split out of `StaticList`
 * kept the access it had when it lived inside the class.
 *
 * Reached by `static_list_command_engine`, `static_list_sort`,
 * `static_list_utils`, `dynamic_list` and `record_validator`.
 *
 * @type {string[]}
 */
export const INTERNAL_STATE_REACHED = [
    "_bumpLimit",
    "_cache",
    "_clampOffset",
    "_commands",
    "_createRecordDatapoint",
    "_currentIds",
    "_getResIdsToLoad",
    "_loadingStubIds",
    "_needsReordering",
    "_onUpdate",
    "_unknownRecordCommands",
];

/**
 * The modules that are PART OF `StaticList`, rather than consumers of it.
 *
 * `static_list.js` was split for size and testability, not into components: its
 * helpers were moved out while the state stayed behind. Measured, the class is
 * the dominant user of every member they share — `_currentIds` 25 uses against
 * the engine's 10, `_commands` 21 against 3 — so the state cannot follow the
 * behaviour out, and folding the helpers back in would delete the suites that
 * cover them separately (`static_list_command_engine.test.js` and friends).
 *
 * What is left is a module whose boundary is not a file. These three are inside
 * it. Their reach into `INTERNAL_STATE_REACHED` is intra-module access that a
 * per-file metric reports as cross-module coupling: **52 of the 59** such
 * accesses come from this list, and only 7 from anywhere else. Counting the 52
 * as debt makes the number unable to show the 7 falling.
 *
 * This list is deliberately explicit and deliberately short. Adding a module
 * here says "this file is part of `StaticList`" — a claim about design that
 * someone has to make and review, not a hole to widen when a new reach is
 * inconvenient.
 *
 * @type {string[]}
 */
export const INTERNAL_COLLABORATORS = [
    "model/relational_model/static_list_command_engine.js",
    "model/relational_model/static_list_sort.js",
    "model/relational_model/static_list_utils.js",
];

/**
 * The owner-facing surface as a type, for modules that drive a list rather than
 * implement one. Reaching past it — into the working memory above — is a
 * typecheck failure instead of an invisible entry in the private-access budget.
 *
 * `STATIC_LIST_OWNER_SURFACE` and this typedef must name the same members;
 * `tooling/architecture/test_record_contract_agreement.py` checks that.
 *
 * @typedef {{
 *  cachedRecords: any[],
 *  getCachedRecord: (resId: number) => any,
 *  hasStagedCommands: boolean,
 *  orderBy: any[],
 *  pendingCommands: Promise<any> | null,
 *  _load: (params?: { limit?: number, offset?: number, orderBy?: any[], nextCurrentIds?: any[] }) => Promise<any>,
 *  _discard: () => void,
 *  _snapshot: () => any,
 *  _restore: (snapshot: any) => void,
 *  _applyCommands: (commands: any[], options?: any) => any,
 *  _applyInitialCommands: (commands: any[]) => any,
 *  _clearCommands: () => void,
 *  _getCommands: (options?: { withReadonly?: boolean }) => any[],
 *  _commitSave: (serverValue: any) => void,
 *  _addRecord: (record: any, options?: { position?: string, sort?: boolean }) => Promise<any>,
 *  _abandonRecords: (records?: any[], options?: { force?: boolean }) => void,
 *  _replaceWith: (ids: number[], options?: { reload?: boolean }) => Promise<any>,
 *  _applyServerValues: (serverValue: any) => any,
 *  _updateContext: (context: Record<string, any>) => void,
 * }} StaticListContract
 */
