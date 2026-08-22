// @ts-check

import { markRaw } from "@odoo/owl";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * @param {any} record
 * @returns {number | string}
 */
export function doubleListId(record) {
    return record.resId || record._virtualId;
}

/**
 * @param {any[]} [records]
 * @returns {Map<number | string, any>}
 */
export function makeStaticListCache(records = []) {
    return markRaw(new Map(records.map((record) => [doubleListId(record), record])));
}

/**
 * @param {Record<string, any>} [overrides]
 * @returns {any}
 */
export function makeStaticListConfig(overrides = {}) {
    return {
        resModel: "res.partner",
        resIds: [],
        activeFields: {},
        fields: {},
        context: {},
        orderBy: [],
        limit: 5,
        offset: 0,
        ...overrides,
    };
}

/**
 * @param {Record<string, any>} [overrides]
 * @returns {any}
 */
export function makeStaticListDouble(overrides = {}) {
    const { config, records, _currentIds, _tmpIncreaseLimit, _cache, model, ...rest } =
        overrides;

    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        _config: makeStaticListConfig(config),
        _parent: undefined,
        _onUpdate: async () => {},
        _cache: _cache ?? makeStaticListCache(),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: new Map(),
        _loadingStubIds: new Set(),
        _replayFailed: false,
        _membership: new ListMembership(),
        _needsReordering: false,
        _extendedRecords: new Set(),
        handleField: undefined,
        model: {
            _patchConfig: (/** @type {any} */ target, /** @type {any} */ patch) =>
                Object.assign(target, patch),
            /** @returns {Promise<any[]>} */
            _loadRecords: async () => [],
            ...model,
        },
    });

    if (_currentIds) {
        list._currentIds = [..._currentIds];
    }
    if (records) {
        list.records = [...records];
    }
    if (_tmpIncreaseLimit !== undefined) {
        list._tmpIncreaseLimit = _tmpIncreaseLimit;
    }
    Object.assign(list, rest);
    return list;
}
