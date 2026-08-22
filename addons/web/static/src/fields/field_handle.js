// @ts-check
/** @odoo-module native */

/** @type {WeakMap<object, FieldHandle>} */
const HANDLES = new WeakMap();

/** @type {WeakMap<object, Map<string, FieldHandle>>} */
const RECORD_HANDLES = new WeakMap();

/**
 * @param {() => any} getRecord
 * @param {() => string} getName
 * @returns {FieldHandle}
 */
function makeHandle(getRecord, getName) {
    return {
        get name() {
            return getName();
        },
        get value() {
            return getRecord().data[getName()];
        },
        get definition() {
            return getRecord().fields[getName()];
        },
        get type() {
            return getRecord().fields[getName()].type;
        },
        update(value, options) {
            return getRecord().update({ [getName()]: value }, options);
        },
    };
}

/**
 * @param {any} component
 * @returns {FieldHandle}
 */
export function fieldHandle(component) {
    let handle = HANDLES.get(component);
    if (!handle) {
        handle = makeHandle(
            () => component.props.record,
            () => component.props.name,
        );
        HANDLES.set(component, handle);
    }
    return handle;
}

/**
 * @param {any} record
 * @param {string} name
 * @returns {FieldHandle}
 */
export function fieldHandleFor(record, name) {
    let byName = RECORD_HANDLES.get(record);
    if (!byName) {
        byName = new Map();
        RECORD_HANDLES.set(record, byName);
    }
    let handle = byName.get(name);
    if (!handle) {
        handle = makeHandle(
            () => record,
            () => name,
        );
        byName.set(name, handle);
    }
    return handle;
}

/**
 * @typedef {{
 * readonly name: string,
 * readonly value: any,
 * readonly definition: Record<string, any>,
 * readonly type: string,
 * update: (value: any, options?: { save?: boolean }) => Promise<void>,
 * }} FieldHandle
 */
