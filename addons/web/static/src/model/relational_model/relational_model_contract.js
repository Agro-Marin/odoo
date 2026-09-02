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
    "askChanges",
    "fetchExactCount",
    "loadNewRecord",
    "loadRecords",
    "onchange",
    "patchConfig",
    "reloadWithConfig",
    "updateSimilarRecords",
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
 * askChanges: () => Promise<any>,
 * fetchExactCount: (config: any) => Promise<number>,
 * loadNewRecord: (config: any, params?: any) => Promise<any>,
 * loadRecords: (config: any, evalContext?: any, cache?: any, signal?: AbortSignal) => Promise<any>,
 * onchange: (config: any, params?: any) => Promise<any>,
 * patchConfig: (config: any, patch: any) => any,
 * reloadWithConfig: (config: any, patch: any, options?: { commit?: (data: Record<string, unknown>) => unknown }) => Promise<any>,
 * updateSimilarRecords: (reloadedRecord: any, serverValues: any) => void,
 * }} RelationalModelContract
 */
