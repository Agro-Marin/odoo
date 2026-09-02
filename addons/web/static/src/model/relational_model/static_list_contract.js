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
    "_unknownRecordCommands",
];

/**
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
 * _unknownRecordCommands: Map<number | string, [number, any, any?][]>,
 * commitCommands: (commands: any[]) => void,
 * commitCurrentIds: (ids: (number | string)[]) => void,
 * insertMemberAt: (index: number, id: number | string) => void,
 * appendMember: (id: number | string) => void,
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
 * loadLocked: (params?: { limit?: number, offset?: number, orderBy?: any[], nextCurrentIds?: any[] }) => Promise<any>,
 * discardLocked: () => void,
 * snapshot: () => any,
 * restoreSnapshot: (snapshot: any) => void,
 * applyCommandsLocked: (commands: any[], options?: any) => any,
 * applyInitialCommands: (commands: any[]) => any,
 * clearCommands: () => void,
 * commitCommands: (commands: any[]) => void,
 * commitCurrentIds: (ids: (string|number)[]) => void,
 * insertMemberAt: (index: number, id: number | string) => void,
 * appendMember: (id: number | string) => void,
 * getCommands: (options?: { withReadonly?: boolean }) => any[],
 * commitSave: (serverValue: any) => void,
 * healFailedReplay: () => void,
 * notifyParentUpdate: (options?: { withoutOnchange?: boolean }) => any,
 * addRecord: (record: any, options?: { position?: string, sort?: boolean }) => Promise<any>,
 * abandonRecords: (records?: any[], options?: { force?: boolean }) => void,
 * replaceWith: (ids: number[]) => Promise<any>,
 * applyServerValues: (serverValue: any) => any,
 * updateContext: (context: Record<string, any>) => void,
 * }} StaticListContract
 */
