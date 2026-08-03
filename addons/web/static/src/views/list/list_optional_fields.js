// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_optional_fields */

/**
 * @param {string} keyOptionalFields
 * @param {string} keyDebugOpenView
 * @param {import("./list_renderer").ListGridContext} ctx
 * @returns {{
 *   debugOpenView: boolean,
 *   computeOptionalActiveFields: () => Record<string, boolean>,
 *   saveOptionalActiveFields: () => void,
 *   toggleOptionalField: (fieldName: string, render: () => void) => void,
 *   toggleOptionalFieldGroup: (groupId: string, render: () => void) => void,
 *   toggleDebugOpenView: (render: () => void) => void,
 * }}
 */
import { browser } from "@web/core/browser/browser";
import { exprToBoolean } from "@web/core/utils/format/strings";
export function useListOptionalFields(keyOptionalFields, keyDebugOpenView, ctx) {
    const { getAllColumns, getOptionalActiveFields, onSave } = ctx;
    const self = {
        debugOpenView: exprToBoolean(browser.localStorage.getItem(keyDebugOpenView)),

        // Read through to storage rather than snapshotting it: the key is
        // shared by every renderer that resolves to the same view, and by every
        // tab, so a snapshot goes stale as soon as one of them writes. A read
        // costs ~0.02us against a ~50ms list render, which is all the snapshot
        // was buying.
        computeOptionalActiveFields() {
            const localStorageValue = browser.localStorage.getItem(keyOptionalFields);
            const optionalColumns = getAllColumns().filter(
                (col) => col.type === "field" && col.optional,
            );
            const result = {};
            if (localStorageValue !== null) {
                const active = localStorageValue.split(",");
                for (const col of optionalColumns) {
                    result[col.name] = active.includes(col.name);
                }
            } else {
                for (const col of optionalColumns) {
                    result[col.name] = col.optional === "show";
                }
            }
            return result;
        },

        saveOptionalActiveFields() {
            const optionalActiveFields = getOptionalActiveFields();
            const activeFieldNames = Object.keys(optionalActiveFields).filter(
                (fieldName) => optionalActiveFields[fieldName],
            );
            browser.localStorage.setItem(keyOptionalFields, activeFieldNames.join(","));
        },

        /**
         * @param {string} fieldName
         * @param {() => void} render
         */
        toggleOptionalField(fieldName, render) {
            const optionalActiveFields = getOptionalActiveFields();
            optionalActiveFields[fieldName] = !optionalActiveFields[fieldName];
            onSave();
            render();
        },

        /**
         * @param {string} groupId
         * @param {() => void} render
         */
        toggleOptionalFieldGroup(groupId, render) {
            const optionalActiveFields = getOptionalActiveFields();
            const fieldNames = getAllColumns()
                .filter(
                    (col) =>
                        col.type === "field" &&
                        col.relatedPropertyField &&
                        /** @type {any} */ (col.relatedPropertyField).id === groupId,
                )
                .map((col) => col.name);
            const active = !fieldNames.every(
                (fieldName) => optionalActiveFields[fieldName],
            );
            for (const fieldName of fieldNames) {
                optionalActiveFields[fieldName] = active;
            }
            onSave();
            render();
        },

        /**
         * @param {() => void} render
         */
        toggleDebugOpenView(render) {
            self.debugOpenView = !self.debugOpenView;
            browser.localStorage.setItem(
                keyDebugOpenView,
                /** @type {any} */ (self.debugOpenView),
            );
            render();
        },
    };

    return /** @type {any} */ (self);
}
