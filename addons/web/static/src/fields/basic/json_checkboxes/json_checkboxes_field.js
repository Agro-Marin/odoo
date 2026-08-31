// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { _t } from "@web/core/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { fieldHandleFor } from "@web/fields/field_handle";
import { useDebouncedFieldCommit } from "@web/fields/hooks/debounced_field_commit";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JsonCheckboxes extends FieldComponent {
    static template = "web.JsonCheckboxes";
    static components = { CheckBox };
    static props = {
        ...standardFieldProps,
        stacked: { type: Boolean, optional: true },
    };

    /** @type {ReturnType<typeof useDebouncedFieldCommit>} */
    debouncedCommitChanges;
    /** @type {Map<string, boolean>} */
    pendingToggles;

    setup() {
        this.checkboxes = useState(deepCopy(this.field.value || {}));
        /**
         * @type {Map<string, boolean>}
         */
        this.pendingToggles = new Map();
        this.debouncedCommitChanges = useDebouncedFieldCommit(
            () => this.commitChanges(),
            100,
        );

        useRecordObserver((record) => {
            const value = deepCopy(fieldHandleFor(record, this.props.name).value || {});
            for (const key of Object.keys(this.checkboxes)) {
                if (!(key in value)) {
                    delete this.checkboxes[key];
                }
            }
            Object.assign(this.checkboxes, value);
            for (const [key, checked] of this.pendingToggles) {
                if (key in this.checkboxes) {
                    this.checkboxes[key].checked = checked;
                } else {
                    this.pendingToggles.delete(key);
                }
            }
        });
    }

    /**
     * @returns {Promise<void>|undefined}
     */
    commitChanges() {
        if (!this.pendingToggles.size) {
            return;
        }
        this.pendingToggles.clear();
        return this.field.update(deepCopy(this.checkboxes));
    }

    /**
     * @param {string} key
     * @param {boolean} checked
     */
    onChange(key, checked) {
        this.checkboxes[key].checked = checked;
        this.pendingToggles.set(key, checked);
        this.debouncedCommitChanges();
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const jsonCheckboxes = {
    component: JsonCheckboxes,
    displayName: _t("Checkbox List"),
    supportedOptions: [
        {
            label: _t("Stacked"),
            name: "stacked",
            type: "boolean",
            help: _t(
                "If checked, the checkboxes will be displayed in a column. Otherwise, they will be inlined.",
            ),
        },
    ],
    supportedTypes: ["json"],
    extractProps({ options }) {
        const stacked = Boolean(options.stacked);
        return {
            stacked,
        };
    },
};

registerField("json_checkboxes", jsonCheckboxes);
