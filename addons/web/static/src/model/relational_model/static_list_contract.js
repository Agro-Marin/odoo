// @ts-check
/** @odoo-module native */

/**
 * @type {string[]}
 */
export const STATIC_LIST_OWNER_SURFACE = [
    "cachedRecords",
    "getCachedRecord",
    "hasStagedCommands",
    "orderBy",
    "pendingCommands",
    "_load",
    "_discard",
    "_snapshot",
    "_restore",
    "_applyCommands",
    "_applyInitialCommands",
    "_clearCommands",
    "_commitCommands",
    "_commitCurrentIds",
    "_insertMemberAt",
    "_appendMember",
    "_getCommands",
    "_commitSave",
    "healFailedReplay",
    "_addRecord",
    "_abandonRecords",
    "_replaceWith",
    "_applyServerValues",
    "_updateContext",
];

/**
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
 * Modules allowed to reach the internals above.
 *
 * Nothing imports this. `tooling/architecture/js_private_access.py` reads it
 * out of this file with a regular expression, so it is gate input rather than
 * dead code -- an import-graph sweep will offer to delete it, and deleting it
 * silently widens what the gate permits.
 *
 * @type {string[]}
 */
export const INTERNAL_COLLABORATORS = [
    "model/relational_model/static_list_command_engine.js",
    "model/relational_model/static_list_sort.js",
    "model/relational_model/static_list_utils.js",
];

/**
 * @typedef {{
 * _bumpLimit: (n: number) => void,
 * _cache: Map<number | string, any>,
 * _clampOffset: () => void,
 * _commands: [number, any, any?][],
 * _createRecordDatapoint: (data: any, params?: any) => any,
 * _currentIds: (number | string)[],
 * _getResIdsToLoad: (resIds: any[], fieldNames?: string[]) => any[],
 * _loadingStubIds: Set<number | string>,
 * _needsReordering: boolean,
 * _onUpdate: (options?: any) => any,
 * _unknownRecordCommands: Map<number | string, [number, any, any?][]>,
 * _commitCommands: (commands: any[]) => void,
 * _commitCurrentIds: (ids: (number | string)[]) => void,
 * _insertMemberAt: (index: number, id: number | string) => void,
 * _appendMember: (id: number | string) => void,
 * records: any[],
 * offset: number,
 * limit: number,
 * fields: Record<string, any>,
 * activeFields: Record<string, any>,
 * config: any,
 * model: any,
 * resModel: string,
 * evalContext: any,
 * }} StaticListInternals
 */

/**
 * @typedef {{
 * cachedRecords: any[],
 * getCachedRecord: (resId: number) => any,
 * hasStagedCommands: boolean,
 * orderBy: any[],
 * pendingCommands: Promise<any> | null,
 * _load: (params?: { limit?: number, offset?: number, orderBy?: any[], nextCurrentIds?: any[] }) => Promise<any>,
 * _discard: () => void,
 * _snapshot: () => any,
 * _restore: (snapshot: any) => void,
 * _applyCommands: (commands: any[], options?: any) => any,
 * _applyInitialCommands: (commands: any[]) => any,
 * _clearCommands: () => void,
 * _commitCommands: (commands: any[]) => void,
 * _commitCurrentIds: (ids: (string|number)[]) => void,
 * _insertMemberAt: (index: number, id: number | string) => void,
 * _appendMember: (id: number | string) => void,
 * _getCommands: (options?: { withReadonly?: boolean }) => any[],
 * _commitSave: (serverValue: any) => void,
 * healFailedReplay: () => void,
 * _addRecord: (record: any, options?: { position?: string, sort?: boolean }) => Promise<any>,
 * _abandonRecords: (records?: any[], options?: { force?: boolean }) => void,
 * _replaceWith: (ids: number[]) => Promise<any>,
 * _applyServerValues: (serverValue: any) => any,
 * _updateContext: (context: Record<string, any>) => void,
 * }} StaticListContract
 */
