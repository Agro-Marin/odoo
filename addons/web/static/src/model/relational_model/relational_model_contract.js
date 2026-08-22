// @ts-check
/** @odoo-module native */

/**
 * @type {string[]}
 */
export const RELATIONAL_MODEL_SURFACE = [
    "Class",
    "activeIdsLimit",
    "closeUrgentSaveNotification",
    "displayUrgentSaveNotification",
    "hasOnRecordChangedHook",
    "hooks",
    "initialCountLimit",
    "initialLimit",
    "load",
    "multiEdit",
    "multiEditDispatch",
    "mutex",
    "notifyLifecycle",
    "notifyLifecycleSync",
    "orm",
    "root",
    "uiHooks",
    "urgentSave",
    "useSampleModel",
    "useSendBeaconToSaveUrgently",
    "_askChanges",
    "_fetchExactCount",
    "_loadNewRecord",
    "_loadRecords",
    "_onchange",
    "_patchConfig",
    "_reloadWithConfig",
    "_updateSimilarRecords",
];

/**
 * @typedef {{
 * Class: any,
 * activeIdsLimit: number | undefined,
 * closeUrgentSaveNotification: (() => void) | undefined,
 * displayUrgentSaveNotification: (message: any) => void,
 * hasOnRecordChangedHook: boolean,
 * hooks: { lifecycle: Record<string, any>, ui: Record<string, any> },
 * initialCountLimit: number,
 * initialLimit: number,
 * load: (params?: any) => Promise<any>,
 * multiEdit: boolean | undefined,
 * multiEditDispatch: (record: any, changes: Record<string, any>) => any,
 * mutex: any,
 * notifyLifecycle: (name: string, ...args: any[]) => Promise<any>,
 * notifyLifecycleSync: (name: string, ...args: any[]) => any,
 * orm: any,
 * root: any,
 * uiHooks: Record<string, any>,
 * urgentSave: any,
 * useSampleModel: boolean,
 * useSendBeaconToSaveUrgently: boolean | undefined,
 * _askChanges: () => Promise<any>,
 * _fetchExactCount: (config: any) => Promise<number>,
 * _loadNewRecord: (config: any, params?: any) => Promise<any>,
 * _loadRecords: (config: any, evalContext?: any, cache?: any, signal?: AbortSignal) => Promise<any>,
 * _onchange: (config: any, params?: any) => Promise<any>,
 * _patchConfig: (config: any, patch: any) => any,
 * _reloadWithConfig: (config: any, patch: any, options?: { commit?: (data: Record<string, unknown>) => unknown }) => Promise<any>,
 * _updateSimilarRecords: (reloadedRecord: any, serverValues: any) => void,
 * }} RelationalModelContract
 */
