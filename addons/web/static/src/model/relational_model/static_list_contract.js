// @ts-check
/** @odoo-module native */

/** @type {string[]} */
export const STATIC_LIST_OWNER_SURFACE = [
    "cachedRecords",
    "getCachedRecord",
    "hasStagedCommands",
    "orderBy",
    "pendingCommands",
    "loadLocked",
    "discardLocked",
    "snapshot",
    "restoreSnapshot",
    "applyCommandsLocked",
    "applyInitialCommands",
    "clearCommands",
    "commitCommands",
    "commitCurrentIds",
    "insertMemberAt",
    "appendMember",
    "getCommands",
    "commitSave",
    "healFailedReplay",
    "notifyParentUpdate",
    "addRecord",
    "abandonRecords",
    "replaceWith",
    "applyServerValues",
    "updateContext",
];

/** @type {string[]} */
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
    "_unknownRecordCommands",
];

/** @type {string[]} */
export const INTERNAL_COLLABORATORS = [
    "model/relational_model/static_list_command_engine.js",
    "model/relational_model/static_list_sort.js",
    "model/relational_model/static_list_utils.js",
];

/** @typedef {{ */

/** @typedef {{ */
